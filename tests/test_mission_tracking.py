"""Jetson-frame alignment, provenance, stale poses and actual HTTP path delivery."""
import json
import math
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.request import Request, urlopen

from mission_control.adapters import Simulator
from mission_control.agent import Agent
from mission_control.server import make_server
from mission_control.state import Coordinator, Conflict
from mission_control.tracking import Tracks, PoseFile
from tests.test_mission_control import TOKENS


class TrackingTests(unittest.TestCase):
    def setUp(self):
        self.now = 100.0
        self.tracks = Tracks(lambda: self.now)

    def observe(self, position, frame='jetson', name='crazyflie', boot='firstboot', **fields):
        self.tracks.observe(name, dict(boot=boot, mode='LIVE', telemetry=dict(
            position_m=position, position_frame=frame, **fields)))
        return self.tracks.snapshot()['tracks'][name]

    def test_boot_frame_is_not_assumed_to_be_jetson_frame(self):
        self.assertEqual(self.observe([1, 0, .5], 'boot')['status'], 'unaligned')
        self.assertEqual(self.tracks.snapshot()['tracks']['crazyflie']['points'], [])
        self.tracks.align('crazyflie', [2, 3, .1], 90)
        track = self.observe([1, 0, .5], 'boot')
        self.assertAlmostEqual(track['latest']['x'], 2)
        self.assertAlmostEqual(track['latest']['y'], 4)
        self.assertAlmostEqual(track['latest']['z'], .6)

    def test_no_rover_position_is_reported_without_localization(self):
        track = self.observe(None, name='rover')
        self.assertEqual(track['status'], 'no_position')
        self.assertIsNone(track['latest'])

    def test_native_jetson_pose_does_not_get_transformed_twice(self):
        self.tracks.align('crazyflie', [100, 100, 100], 90)
        self.assertEqual(self.observe([1, 2, 3])['latest']['x'], 1)

    def test_nonfinite_bool_stale_and_unknown_frames_are_not_plotted(self):
        for position, fields in [([math.nan, 0, 0], {}), ([True, 0, 0], {}),
                                 ([1, 2, 3], {'position_age_s':3})]:
            with self.subTest(position=position):
                self.assertEqual(self.observe(position, **fields)['status'], 'invalid')
        self.assertEqual(self.observe([1, 2, 3], 'unknown')['status'], 'unaligned')

    def test_duplicate_pose_does_not_refresh_measurement(self):
        self.observe([1, 2, 3], position_sample_id=10)
        self.now += 3
        track = self.observe([1, 2, 3], position_sample_id=10)
        self.assertEqual(track['status'], 'stale')
        self.assertEqual(len(track['points']), 1)

    def test_tracking_gap_starts_new_segment_and_restart_invalidates_alignment(self):
        self.tracks.align('crazyflie', [0, 0, 0], 0)
        first = self.observe([0, 0, 0], 'boot')['latest']
        self.now += 3
        second = self.observe([1, 0, 0], 'boot')['latest']
        self.assertNotEqual(first['segment'], second['segment'])
        self.now += .3
        track = self.observe([0, 0, 0], 'boot', boot='secondboot')
        self.assertEqual(track['status'], 'unaligned')
        self.assertIsNone(track['calibration'])
        self.assertEqual(track['points'], [])

    def test_history_is_bounded_and_realign_clears_only_affected_vehicle(self):
        self.observe([0, 0, 0], name='rover')
        for index in range(650):
            self.now += .25
            self.observe([index/100, 0, 0])
        self.assertEqual(len(self.tracks.snapshot()['tracks']['crazyflie']['points']), 600)
        self.tracks.align('crazyflie', [0, 0, 0], 0)
        self.assertEqual(len(self.tracks.snapshot()['tracks']['rover']['points']), 1)
        self.assertEqual(len(self.tracks.snapshot()['tracks']['crazyflie']['points']), 0)

    def test_pose_file_requires_fresh_timestamp_and_coordinates(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory)/'pose.json'
            reader = PoseFile(file, lambda:100)
            self.assertIsNone(reader.read()['position_m'])
            file.write_text(json.dumps(dict(position_m=[1, 2, 0], sampled_at=99.5, frame='jetson')))
            self.assertEqual(reader.read()['position_age_s'], .5)
            for stamp in (96, 101):
                file.write_text(json.dumps(dict(position_m=[1, 2, 0], sampled_at=stamp, frame='jetson')))
                self.assertIsNone(reader.read()['position_m'])

    def test_simulated_rover_motion_is_labeled_and_not_a_real_motor_estimate(self):
        rover = Simulator('rover')
        rover.execute('pulse', {'direction':'w', 'power':20})
        self.assertAlmostEqual(rover.telemetry()['position_m'][0], .05)
        self.assertEqual(rover.telemetry()['position_source'], 'SIMULATED')


class TrackingHTTPTests(unittest.TestCase):
    def test_agent_pose_reaches_authenticated_paths_endpoint(self):
        now = [100.0]
        state = Coordinator(lambda:now[0])
        server = make_server(state, TOKENS, port=0)
        worker = threading.Thread(target=server.serve_forever, kwargs={'poll_interval':.02}, daemon=True)
        worker.start()
        url = f'http://127.0.0.1:{server.server_port}'
        try:
            simulator = Simulator('crazyflie')
            agent = Agent('crazyflie', TOKENS['crazyflie'], url, simulator)
            agent.step()
            simulator.execute('takeoff', {'height':.5})
            now[0] += .3
            agent.step()
            request = Request(url+'/api/tracks', headers={'Authorization':'Bearer '+TOKENS['operator']})
            with urlopen(request) as response:
                data = json.load(response)
            self.assertEqual(data['origin'], [0, 0, 0])
            self.assertEqual(data['tracks']['crazyflie']['latest']['z'], .5)
            self.assertEqual(data['tracks']['crazyflie']['source'], 'SIMULATED')
            with urlopen(url+'/paths.js') as response:
                self.assertEqual(response.status, 200)
        finally:
            server.shutdown(); server.server_close(); worker.join(2)

    def test_alignment_needs_operator_lease_and_pause(self):
        state = Coordinator()
        with self.assertRaises(Conflict):
            state.operator('frame', dict(node='rover', translation_m=[0,0,0], yaw_deg=0))
        session = state.operator('claim', {})['session']
        data = dict(session=session, node='rover', translation_m=[1,2,0], yaw_deg=0)
        state.operator('frame', data)
        self.assertEqual(state.tracking.frames['rover']['translation_m'], [1,2,0])
        state.operator('resume', dict(session=session))
        with self.assertRaises(Conflict):
            state.operator('frame', data)


if __name__ == '__main__':
    unittest.main()
