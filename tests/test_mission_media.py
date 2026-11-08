"""Actual HTTP media transport and bounded camera/BLE adapters; no hardware."""
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from mission_control.camera import PiCamera, MAX_FRAME
from mission_control.feeds import BluetoothFeed
from mission_control.server import make_server
from mission_control.state import Coordinator
from tests.test_mission_control import TOKENS


class CameraTests(unittest.TestCase):
    def test_fragmented_frames_newest_frame_only_and_staleness(self):
        now = [0.0]
        camera = PiCamera(lambda: now[0])
        self.assertIsNone(camera.snapshot()['frame'])
        camera.ingest(b'noise\xff')
        camera.ingest(b'\xd8frame-one\xff')
        camera.ingest(b'\xd9\xff\xd8frame-two\xff\xd9')
        self.assertEqual(camera.snapshot()['frame'], b'\xff\xd8frame-two\xff\xd9')
        self.assertEqual(camera.snapshot()['sequence'], 2)
        now[0] = 1.1
        self.assertIsNone(camera.snapshot()['frame'])
        self.assertEqual(camera.snapshot()['detail'], 'Camera signal lost')

    def test_oversized_camera_buffer_is_dropped_and_recovers(self):
        camera = PiCamera()
        camera.ingest(b'\xff\xd8' + b'x' * MAX_FRAME)
        self.assertLessEqual(len(camera.pending), 1)
        camera.ingest(b'\xff\xd8recovered\xff\xd9')
        self.assertEqual(camera.snapshot()['sequence'], 1)

    def test_missing_pi_tool_fails_without_starting_a_webcam(self):
        with patch('mission_control.camera.shutil.which', return_value=None):
            with self.assertRaisesRegex(ValueError, 'rpicam-vid not found'):
                PiCamera().start()

    def test_camera_child_process_is_consumed_and_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / 'fake-rpicam'
            executable.write_text('#!/usr/bin/env python3\nimport sys,time\nsys.stdout.buffer.write(b"\\xff\\xd8fixture\\xff\\xd9");sys.stdout.buffer.flush()\ntime.sleep(20)\n')
            executable.chmod(0o700)
            camera = PiCamera()
            with patch('mission_control.camera.shutil.which', return_value=str(executable)):
                camera.start()
            try:
                deadline = time.monotonic() + 2
                while camera.snapshot()['frame'] is None and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertEqual(camera.snapshot()['frame'], b'\xff\xd8fixture\xff\xd9')
            finally:
                camera.close()
            self.assertIsNotNone(camera.process.poll())
            self.assertFalse(camera.worker.is_alive())
            self.assertIsNone(camera.snapshot()['frame'])


class MediaHTTPTests(unittest.TestCase):
    def setUp(self):
        self.camera = PiCamera()
        self.server = make_server(Coordinator(), TOKENS, port=0, camera=self.camera)
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval':0.02}, daemon=True)
        self.thread.start()
        self.url = f'http://127.0.0.1:{self.server.server_port}'

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)

    def get(self, path, role='operator'):
        return urlopen(Request(self.url + path, headers={'Authorization':'Bearer ' + TOKENS[role]}), timeout=2)

    def test_camera_frames_require_operator_auth_and_are_never_cached(self):
        for role in ('jetson', 'rover', 'crazyflie'):
            with self.assertRaises(HTTPError) as error:
                self.get('/api/camera/frame', role)
            self.assertEqual(error.exception.code, 401)
            error.exception.close()
        with self.assertRaises(HTTPError) as error:
            self.get('/api/camera/frame')
        self.assertEqual(error.exception.code, 503)
        error.exception.close()
        self.camera.ingest(b'\xff\xd8fixture\xff\xd9')
        with self.get('/api/camera/frame') as response:
            self.assertEqual(response.read(), b'\xff\xd8fixture\xff\xd9')
            self.assertEqual(response.headers['Content-Type'], 'image/jpeg')
            self.assertEqual(response.headers['X-Camera-Source'], 'PI CAMERA')
            self.assertEqual(response.headers['Cache-Control'], 'no-store')

    def test_real_discovery_service_bridge_preserves_unverified_and_verified(self):
        from discovery.server import Discovery, make_server as make_discovery
        discovery = Discovery(source='SIMULATED')
        discovery.ingest('#HEARTBEAT,scanning=1,passive=1,discovery=1')
        discovery.ingest('#BLE,-55,aa:bb:cc:dd:ee:ff,0,020106')
        source = make_discovery(discovery, port=0)
        worker = threading.Thread(target=source.serve_forever, kwargs={'poll_interval':0.02}, daemon=True)
        worker.start()
        try:
            feed = BluetoothFeed(f'http://127.0.0.1:{source.server_port}').snapshot()
            self.assertTrue(feed['connected'])
            self.assertEqual(feed['discovery']['signals'][0]['rssi'], -55)
            self.assertEqual(feed['discovery']['source'], 'SIMULATED')
            self.assertEqual(feed['beacons']['status'], 'off')
            self.assertEqual(feed['beacons']['sightings'], [])
            self.assertNotIn('aa:bb:cc:dd:ee:ff', json.dumps(feed))
        finally:
            source.shutdown(); source.server_close(); worker.join(2)

    def test_bluetooth_endpoint_is_operator_only_and_offline_is_explicit(self):
        with self.assertRaises(HTTPError) as error:
            self.get('/api/bluetooth', 'jetson')
        self.assertEqual(error.exception.code, 401)
        error.exception.close()
        with patch('mission_control.feeds.urlopen', side_effect=OSError('offline')):
            with self.get('/api/bluetooth') as response:
                data = json.load(response)
        self.assertFalse(data['connected'])
        self.assertIsNone(data['discovery'])

    def test_media_script_and_blob_csp_are_served(self):
        with self.get('/media.js') as response:
            self.assertIn(b'captureCanvas.captureStream', response.read())
            self.assertIn("media-src 'self' blob:", response.headers['Content-Security-Policy'])


if __name__ == '__main__':
    unittest.main()
