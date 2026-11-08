"""Same-origin workspace, simulator routing and authenticated vision lifecycle."""
import json
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from mission_control.camera import PiCamera
from mission_control.server import make_server
from mission_control.state import Coordinator
from tests.test_mission_control import TOKENS


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.camera = PiCamera()
        self.server = make_server(Coordinator(), TOKENS, port=0, camera=self.camera)
        self.worker = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.worker.start()
        self.url = f'http://127.0.0.1:{self.server.server_port}'

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.worker.join(2)

    def request(self, path, body=None, token=None, origin=None):
        headers = {'Content-Type': 'application/json'}
        if token:
            headers['Authorization'] = 'Bearer ' + TOKENS[token]
        if origin:
            headers['Origin'] = origin
        return urlopen(Request(self.url+path, data=body, headers=headers), timeout=12)

    def test_overview_and_embedded_views_keep_correct_framing_policy(self):
        with self.request('/') as response:
            page = response.read().decode()
            self.assertIn("frame-ancestors 'none'", response.headers['Content-Security-Policy'])
        for name in ('simulation', 'ble', 'vision', 'decisions'):
            self.assertIn('frame-' + name, page)
        for path in ('/control?embedded=1', '/trace?embedded=1', '/vision?embedded=1'):
            with self.request(path) as response:
                self.assertEqual(response.status, 200)
                self.assertIn("frame-ancestors 'self'", response.headers['Content-Security-Policy'])

    def test_system_explainer_is_available_without_starting_live_devices(self):
        for path, kind in (('/about', 'text/html'), ('/about.js', 'text/javascript'), ('/about.css', 'text/css')):
            with self.request(path) as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(response.headers.get_content_type(), kind)
                if path == '/about':
                    self.assertIn("frame-ancestors 'self'", response.headers['Content-Security-Policy'])
        self.assertIsNone(self.camera.process)
        self.assertIsNone(self.server.vision.process)

    def test_vision_state_and_controls_require_operator_authentication(self):
        for path, body in (('/api/vision', None), ('/api/vision/frame', None),
                           ('/api/vision/start', b'{}'), ('/api/vision/stop', b'{}')):
            for role in (None, 'jetson'):
                with self.assertRaises(HTTPError) as error:
                    self.request(path, body, token=role)
                self.assertEqual(error.exception.code, 401)
                error.exception.close()
        with self.request('/api/vision', token='operator') as response:
            data = json.load(response)
            self.assertFalse(data['running'])
            self.assertFalse(data['fresh'])
            self.assertNotIn('frame', data)
        self.assertIsNone(self.server.vision.process)

    def test_raw_camera_conditional_frames_and_training_authentication(self):
        self.camera.publish(b'\xff\xd8fixture\xff\xd9', 'test-publisher')
        with self.request('/api/camera/frame', token='operator') as response:
            tag = response.headers['ETag']
        request = Request(self.url+'/api/camera/frame', headers={
            'Authorization': 'Bearer '+TOKENS['operator'], 'If-None-Match': tag})
        with self.assertRaises(HTTPError) as error:
            urlopen(request)
        self.assertEqual(error.exception.code, 304)
        error.exception.close()
        for path, body in (('/api/training', None), ('/api/training/sample', b'{}'), ('/api/training/start', b'{}')):
            with self.assertRaises(HTTPError) as error:
                self.request(path, body, token='jetson')
            self.assertEqual(error.exception.code, 401)
            error.exception.close()

    def test_stale_or_stopped_results_never_return_a_detection_frame(self):
        now = [100.0]
        camera = self.camera
        camera.clock = lambda: now[0]
        camera.publish(b'\xff\xd8fixture\xff\xd9', 'test-publisher')
        vision = self.server.vision
        import time
        with vision.lock:
            vision.running = True
            vision.result = dict(frame=b'\xff\xd8annotated\xff\xd9', detections=[{'family': 'PERSON_DETECTOR'}])
            vision.received = time.monotonic()
        with self.request('/api/vision/frame', token='operator') as response:
            self.assertEqual(response.read(), b'\xff\xd8annotated\xff\xd9')
        now[0] += 2
        with self.request('/api/vision', token='operator') as response:
            self.assertFalse(json.load(response)['fresh'])
        with self.assertRaises(HTTPError) as error:
            self.request('/api/vision/frame', token='operator')
        self.assertEqual(error.exception.code, 503)
        error.exception.close()
        with self.request('/api/vision/stop', b'{}', token='operator'):
            pass
        self.assertIsNone(vision.result)

    def test_cross_origin_vision_and_simulator_mutations_are_refused(self):
        for path in ('/api/vision/start', '/simulation/control'):
            with self.assertRaises(HTTPError) as error:
                self.request(path, b'{}', token='operator', origin='https://elsewhere.example')
            self.assertEqual(error.exception.code, 403)
            error.exception.close()

    def test_real_simulator_proxy_stream_and_controls(self):
        with self.request('/simulation/') as response:
            page = response.read().decode()
            csp = response.headers['Content-Security-Policy']
        self.assertIn('/sim-theme.css', page)
        self.assertIn('/simulation/stream', page)
        self.assertIn('/simulation/control', page)
        self.assertIn('/simulation/leaflet/leaflet.js', page)
        self.assertIn("script-src 'self' 'nonce-", csp)
        with self.request('/simulation/stream') as response:
            for _ in range(20):
                line = response.readline()
                if line.startswith(b'data: '):
                    data = json.loads(line[6:])
                    if 'grid' in data:
                        break
            self.assertIn('grid', data)
            self.assertEqual(len(data['drones']), 4)
        with self.request('/simulation/control', b'{"cmd":"pause"}') as response:
            self.assertEqual(response.status, 204)
