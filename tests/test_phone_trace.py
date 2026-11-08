"""Live trace page, radio source labeling and a real pseudo-terminal receiver path."""
import json
import os
import pty
import tempfile
import threading
import time
import termios
import tty
import unittest
import signal
import socket
import subprocess
import sys
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from discovery.server import Discovery, serial_worker
from mission_control.server import make_server
from mission_control.state import Coordinator
from mission_control.trace import ReceiverFeed
from mission_control.camera import PiCamera
from mission_control.phone_activity import PhoneActivity
from tests.test_mission_control import TOKENS


class OperatorReceiverCLITests(unittest.TestCase):
    def test_operator_server_reads_its_own_serial_receiver(self):
        from pathlib import Path
        from mission_control.protocol import init_credentials, load_credentials
        master, slave = pty.openpty()
        tty.setraw(slave)
        os.set_blocking(master, False)
        with socket.socket() as reservation:
            reservation.bind(('127.0.0.1', 0))
            port = reservation.getsockname()[1]
        try:
            with tempfile.TemporaryDirectory() as directory:
                credentials = init_credentials(Path(directory) / 'credentials.json')
                token = load_credentials(credentials)['operator']
                process = subprocess.Popen([sys.executable, '-m', 'mission_control.server',
                    '--port', str(port), '--serial', os.ttyname(slave),
                    '--credentials', str(credentials)], stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE)
                try:
                    deadline = time.monotonic() + 8
                    data = None
                    while time.monotonic() < deadline:
                        self.assertIsNone(process.poll(), 'Operator receiver exited before serving')
                        os.write(master, b'#HEARTBEAT,scanning=1,passive=1,discovery=1\n'
                            b'#BLE,-55,aa:bb:cc:dd:ee:ff,0,020106\n')
                        try:
                            request = Request(f'http://127.0.0.1:{port}/api/bluetooth',
                                headers={'Authorization': 'Bearer ' + token})
                            with urlopen(request, timeout=.5) as response:
                                data = json.load(response)
                            if data['discovery']['signals']:
                                break
                        except OSError:
                            pass
                        time.sleep(.1)
                    self.assertIsNotNone(data)
                    self.assertEqual(data['discovery']['status'], 'scanning')
                    self.assertEqual(data['discovery']['signals'][0]['rssi'], -55)
                    self.assertEqual(data['beacons']['status'], 'off')
                    self.assertEqual(data['trace_signals'], [])
                finally:
                    process.send_signal(signal.SIGINT)
                    _, errors = process.communicate(timeout=5)
                self.assertEqual(process.returncode, 0, errors.decode())
        finally:
            os.close(master)
            os.close(slave)


class TraceTests(unittest.TestCase):
    def setUp(self):
        self.discovery = Discovery(source='SIMULATED')
        self.camera = PiCamera()
        self.server = make_server(Coordinator(), TOKENS, port=0,
                                  bluetooth=ReceiverFeed(self.discovery), camera=self.camera)
        self.worker = threading.Thread(target=self.server.serve_forever,
                                       kwargs={'poll_interval':.02}, daemon=True)
        self.worker.start()
        self.url = f'http://127.0.0.1:{self.server.server_port}'

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.worker.join(2)

    def read(self, path, authorized=True):
        request = Request(self.url+path, headers={'Authorization':'Bearer '+TOKENS['operator']} if authorized else {})
        return urlopen(request, timeout=2)

    def test_trace_assets_are_served_and_explain_manual_markers(self):
        for path in ('/trace', '/trace.js', '/trace.css'):
            with self.read(path, authorized=False) as response:
                self.assertEqual(response.status, 200)
                data = response.read()
            if path == '/trace':
                self.assertIn(b'Schematic or manually placed, not measured coordinates', data)
                self.assertIn(b'no vision', data)

    def test_viewer_requires_token_to_read_actual_bluetooth_data(self):
        with self.assertRaises(HTTPError) as error:
            self.read('/api/bluetooth', authorized=False)
        self.assertEqual(error.exception.code, 401)
        error.exception.close()
        with self.read('/api/bluetooth') as response:
            data = json.load(response)
        self.assertEqual(data['discovery']['source'], 'SIMULATED')
        self.assertEqual(data['discovery']['signals'], [])
        self.assertEqual(data['beacons']['status'], 'off')

    def test_unverified_signal_is_never_promoted_to_authenticated_beacon(self):
        self.discovery.ingest('#HEARTBEAT,scanning=1,passive=1,discovery=1')
        self.discovery.ingest('#BLE,-55,aa:bb:cc:dd:ee:ff,0,020106')
        with self.read('/api/bluetooth') as response:
            data = json.load(response)
        self.assertEqual(data['discovery']['signals'][0]['rssi'], -55)
        self.assertEqual(data['beacons']['sightings'], [])
        self.assertNotIn('aa:bb:cc:dd:ee:ff', json.dumps(data))

    def test_receiver_loss_does_not_keep_signal_live(self):
        now = [0.0]
        discovery = Discovery(clock=lambda:now[0], source='SIMULATED')
        feed = ReceiverFeed(discovery)
        discovery.ingest('#HEARTBEAT,scanning=1,passive=1,discovery=1')
        discovery.ingest('#BLE,-55,aa:bb:cc:dd:ee:ff,0,020106')
        now[0] += 6
        snapshot = feed.snapshot()
        self.assertEqual(snapshot['discovery']['status'], 'unavailable')
        self.assertTrue(snapshot['discovery']['signals'][0]['stale'])

    def test_camera_sharing_is_authenticated_and_readable_on_the_same_server(self):
        frame = b'\xff\xd8browser-camera-fixture\xff\xd9'
        headers = {'Content-Type':'image/jpeg', 'X-Camera-Publisher':'fixture-publisher'}
        with self.assertRaises(HTTPError) as error:
            urlopen(Request(self.url+'/api/camera/publish', frame, headers))
        self.assertEqual(error.exception.code, 401)
        error.exception.close()
        headers['Authorization'] = 'Bearer '+TOKENS['operator']
        with urlopen(Request(self.url+'/api/camera/publish', frame, headers)) as response:
            self.assertTrue(json.load(response)['ok'])
        with self.read('/api/camera/frame') as response:
            self.assertEqual(response.read(), frame)
            self.assertEqual(response.headers['X-Camera-Source'], 'SHARED DEVICE CAMERA')
        headers['X-Camera-Publisher'] = 'second-publisher'
        with self.assertRaises(HTTPError) as error:
            urlopen(Request(self.url+'/api/camera/publish', frame, headers))
        self.assertEqual(error.exception.code, 400)
        error.exception.close()

    def test_camera_publisher_expiry_and_source_ownership(self):
        now = [100.0]
        camera = PiCamera(clock=lambda:now[0])
        frame = b'\xff\xd8fixture\xff\xd9'
        camera.publish(frame, 'publisher-one')
        now[0] += 1.1
        self.assertIsNone(camera.snapshot()['frame'])
        now[0] += 1
        camera.publish(frame, 'publisher-two')
        self.assertIsNotNone(camera.snapshot()['frame'])
        camera.process = object()
        with self.assertRaises(ValueError):
            camera.publish(frame, 'publisher-two')

    def test_camera_publisher_rejects_invalid_frames(self):
        for frame in (b'', b'not a jpeg', b'\xff\xd8partial', b'\xff\xd8'+b'x'*(2*1024*1024)+b'\xff\xd9'):
            with self.assertRaises(ValueError):
                self.camera.publish(frame, 'fixture-publisher')

    def test_real_serial_reader_to_http_preserves_signal_not_location(self):
        master, slave = pty.openpty()
        tty.setraw(slave, when=termios.TCSANOW)
        os.set_blocking(master, False)
        stop = threading.Event()
        worker = threading.Thread(target=serial_worker,
            args=(self.discovery, os.ttyname(slave), stop), daemon=True)
        worker.start()
        try:
            deadline = time.monotonic()+4
            while not self.discovery.snapshot()['signals'] and time.monotonic()<deadline:
                try:
                    os.write(master,b'#HEARTBEAT,scanning=1,passive=1,discovery=1\n#BLE,-55,aa:bb:cc:dd:ee:ff,0,020106\n')
                except BlockingIOError:
                    pass
                time.sleep(.05)
            with self.read('/api/bluetooth') as response:
                data = json.load(response)
            self.assertEqual(data['discovery']['status'], 'scanning', data['discovery']['detail'])
            signal = data['discovery']['signals'][0]
            self.assertEqual(signal['rssi'], -55)
            self.assertNotIn('position_m', signal)
            self.assertNotIn('bearing', signal)
        finally:
            stop.set(); worker.join(3); os.close(master); os.close(slave)


class PhoneActivityTests(unittest.TestCase):
    def setUp(self):
        from ble_id import BeaconMonitor
        from ble_keys import TEST_KEYS
        from ble_state import init_state
        from ble_verify import counter_at
        self.directory = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.directory.name, 'state.json')
        self.wall, self.mono = 1794077187.0, 1000.0
        self.counter = counter_at(self.wall)
        self.keys = TEST_KEYS
        init_state(self.path, scope='TESTKEY-phone-activity')
        self.discovery = Discovery(clock=lambda:self.mono, source='SIMULATED')
        self.discovery.ingest('#HEARTBEAT,scanning=1,passive=1,discovery=1')
        self.monitor = BeaconMonitor(TEST_KEYS, self.path, scope='TESTKEY-phone-activity',
            mode='test-keys', source='SIMULATED', receiver_ready=self.discovery.ready,
            wall=lambda:self.wall, mono=lambda:self.mono)
        self.feed = ReceiverFeed(self.discovery, self.monitor)
        self.feed.activity = PhoneActivity(self.monitor, clock=lambda:self.mono)

    def tearDown(self):
        os.close(self.monitor.owner)
        self.directory.cleanup()

    def row(self, rssi=-60, counter=None, key=None):
        from ble_sim import row
        from ble_verify import make_token
        return row(rssi, make_token(key or self.keys[1], self.counter if counter is None else counter, alias=1))

    def test_duplicate_rf_reports_do_not_refresh_verified_sighting(self):
        self.feed.ingest(self.row())
        self.wall += 1; self.mono += 1
        self.feed.ingest(self.row(rssi=-40))
        sighting = self.monitor.snapshot()['sightings'][0]
        activity = self.feed.activity.snapshot()[0]
        self.assertEqual(sighting['verified_tokens'], 1)
        self.assertEqual(sighting['last_verified_age_s'], 1)
        self.assertEqual(sighting['rssi'], -60)
        self.assertEqual(activity['rssi'], -40)
        self.assertEqual(activity['count'], 2)
        self.assertEqual(activity['mode'], 'test-keys')

    def test_forged_future_and_stale_tokens_never_create_phone_activity(self):
        for line in (self.row(key=b'\xa5'*32), self.row(counter=self.counter+2),self.row(counter=self.counter-2)):
            self.feed.ingest(line)
        self.assertEqual(self.feed.activity.snapshot(), [])

    def test_persist_failure_blocks_rf_publication(self):
        from unittest.mock import patch
        with patch('ble_id.save_state', side_effect=OSError('disk failure')):
            self.feed.ingest(self.row())
        self.assertTrue(self.monitor.halted)
        self.assertEqual(self.feed.activity.snapshot(), [])

    def test_prior_replay_state_without_published_sighting_is_not_enough(self):
        self.monitor.ingest(self.row())
        self.monitor.sightings.clear()  # Models a restart with persisted high-water state.
        self.feed.ingest(self.row())
        self.assertEqual(self.feed.activity.snapshot(), [])

    def test_old_tokens_do_not_keep_activity_alive(self):
        self.feed.ingest(self.row())
        self.wall += 90; self.mono += 90
        self.discovery.ingest('#HEARTBEAT,scanning=1,passive=1,discovery=1')
        self.feed.ingest(self.row())
        self.assertEqual(self.feed.activity.snapshot(), [])

    def test_new_rotating_token_keeps_same_trace_alias(self):
        self.feed.ingest(self.row())
        self.wall += 30; self.mono += 30
        self.discovery.ingest('#HEARTBEAT,scanning=1,passive=1,discovery=1')
        self.feed.ingest(self.row(counter=self.counter+1))
        activity = self.feed.activity.snapshot()
        self.assertEqual(len(activity), 1)
        self.assertEqual(activity[0]['id'], 'enrolled-1')
        self.assertEqual(self.monitor.snapshot()['sightings'][0]['verified_tokens'], 2)


if __name__ == '__main__':
    unittest.main()
