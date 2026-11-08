"""Signed status transitions, replay resistance, durability and trace integration."""
import os
import tempfile
import unittest
from unittest.mock import patch

from ble_id import BeaconMonitor
from ble_keys import TEST_KEYS
from ble_sim import row
from ble_state import init_state, load_state, StateError
from ble_verify import counter_at
from discovery.server import Discovery
from mission_control.sos_monitor import SOSMonitor
from mission_control.trace import ReceiverFeed
from sos_verify import make_status_token, verify_status, MAX_WINDOW


class ProtocolTests(unittest.TestCase):
    counter = 59802572

    def token(self, rev=0, sos=False, counter=None):
        return make_status_token(TEST_KEYS[1], self.counter if counter is None else counter,
                                 alias=1, revision=rev, sos=sos)

    def verify(self, token, seen=None):
        return verify_status(token, TEST_KEYS, seen or {}, now=self.counter*30)

    def test_cross_language_reference_vectors(self):
        self.assertEqual(self.token().hex(), '02017210798093ffd77654ef38e8c8ed')
        self.assertEqual(self.token(1, True).hex(), '020172107983424b3137dc7c1ed5aa69')
        self.assertEqual(self.token(2).hex(), '02017210798403acdd8cf2d2cf388a19')

    def test_set_and_clear_in_same_window_reject_older_status(self):
        seen = {}
        for rev, sos in ((0, False), (1, True), (2, False)):
            decision, seen = self.verify(self.token(rev, sos), seen)
            self.assertEqual(decision.kind, 'verified')
            self.assertEqual(decision.sos, sos)
        for rev, sos in ((0, False), (1, True), (2, False)):
            decision, unchanged = self.verify(self.token(rev, sos), seen)
            self.assertEqual(decision.kind, 'replay')
            self.assertEqual(unchanged, seen)

    def test_flag_tampering_and_time_outliers(self):
        altered = bytearray(self.token()); altered[5] ^= 1
        self.assertEqual(self.verify(altered)[0].kind, 'forged')
        for offset, reason in ((-2, 'stale'), (2, 'future')):
            self.assertEqual(self.verify(self.token(counter=self.counter+offset))[0].reason, reason)

    def test_bounds_and_version_isolation(self):
        for counter, revision, sos in ((MAX_WINDOW+1, 0, False), (1,16,False), (1,0,1)):
            with self.assertRaises(ValueError):
                make_status_token(TEST_KEYS[1],counter,alias=1,revision=revision,sos=sos)
        from ble_verify import make_token
        self.assertEqual(self.verify(make_token(TEST_KEYS[1],self.counter,alias=1))[0].reason,'unsupported_version')


class MonitorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.wall, self.mono = 1794077187.0, 1000.0
        self.counter = counter_at(self.wall)
        self.scope = 'TESTKEY-sos-tests'
        self.discovery = Discovery(clock=lambda:self.mono, source='SIMULATED')
        self.heartbeat()
        self.v1path = self.tmp.name+'/v1.json'
        self.path = self.tmp.name+'/v2.json'
        init_state(self.v1path, scope=self.scope)
        init_state(self.path, scope=self.scope+':SOSv2')
        self.beacons = BeaconMonitor(TEST_KEYS,self.v1path,scope=self.scope,mode='test-keys',
            source='SIMULATED',receiver_ready=self.discovery.ready,wall=lambda:self.wall,mono=lambda:self.mono)
        self.status = self.monitor()
        self.feed = ReceiverFeed(self.discovery,self.beacons,self.status)

    def monitor(self):
        return SOSMonitor(self.beacons,self.path,wall=lambda:self.wall,mono=lambda:self.mono)

    def heartbeat(self):
        self.discovery.ingest('#HEARTBEAT,scanning=1,passive=1,discovery=1')

    def tearDown(self):
        os.close(self.status.owner); os.close(self.beacons.owner); self.tmp.cleanup()

    def send(self, revision=0, sos=True, counter=None, rssi=-50):
        self.feed.ingest(row(rssi,make_status_token(TEST_KEYS[1],self.counter if counter is None else counter,
                                                  alias=1,revision=revision,sos=sos)))

    def sighting(self):
        return self.status.snapshot()['sightings'][0]

    def test_duplicate_updates_rf_without_refreshing_status(self):
        self.send()
        self.mono += 2; self.wall += 2
        self.send(rssi=-30)
        self.assertEqual(self.sighting()['last_verified_age_s'],2)
        self.assertEqual(self.sighting()['verified_tokens'],1)
        signal=self.feed.snapshot()['trace_signals'][0]
        self.assertEqual((signal['count'],signal['rssi'],signal['protocol_version']),(2,-30,2))

    def test_old_normal_or_conflicting_same_revision_cannot_clear_sos(self):
        self.send(1,True)
        self.send(0,False)
        self.send(1,False)  # Even a correctly signed conflicting bit cannot replace equal order.
        self.assertTrue(self.sighting()['sos'])
        self.assertEqual(self.status.snapshot()['trace_signals'][0]['count'],1)
        self.send(2,False)
        self.send(1,True)
        self.assertFalse(self.sighting()['sos'])

    def test_disk_failure_withholds_status_and_halts(self):
        self.send(0,False)
        with patch('mission_control.sos_monitor.save_state',side_effect=OSError('disk failure')):
            self.send(1,True)
        self.assertFalse(self.sighting()['sos'])
        self.assertEqual(self.status.snapshot()['status'],'halted')
        self.assertFalse(self.sighting()['status_fresh'])
        self.send(2,True)
        self.assertEqual(self.sighting()['verified_tokens'],1)

    def test_save_happens_before_publish(self):
        import mission_control.sos_monitor as module
        original=module.save_state
        def saving(*args,**kwargs):
            self.assertEqual(self.status.sightings,{})
            return original(*args,**kwargs)
        with patch.object(module,'save_state',side_effect=saving):
            self.send()
        self.assertEqual(load_state(self.path,scope=self.scope+':SOSv2')[1],self.counter<<4)
        self.assertEqual(load_state(self.v1path,scope=self.scope),{})

    def test_receiver_loss_keeps_last_sos_as_stale(self):
        self.send()
        self.mono += 80; self.wall += 80
        self.assertTrue(self.sighting()['sos'])
        self.assertFalse(self.sighting()['status_fresh'])
        self.heartbeat(); self.send()
        self.assertEqual(self.sighting()['verified_tokens'],1)
        self.assertTrue(self.sighting()['sos'])

    def test_restart_does_not_publish_replay_or_reset_state(self):
        self.send()
        os.close(self.status.owner)
        self.status=self.monitor(); self.feed.sos=self.status
        self.send()
        self.assertEqual(self.status.snapshot()['sightings'],[])
        self.send(1,True)
        self.assertTrue(self.sighting()['sos'])

    def test_v1_cannot_override_v2_status_or_identity(self):
        from ble_verify import make_token
        self.send()
        self.feed.ingest(row(-20,make_token(TEST_KEYS[1],self.counter,alias=1)))
        signal=self.feed.snapshot()['trace_signals'][0]
        self.assertTrue(signal['sos']); self.assertEqual(signal['protocol_version'],2)

    def test_missing_and_wrong_scope_fail_closed(self):
        with self.assertRaises(StateError):
            SOSMonitor(self.beacons,self.tmp.name+'/missing.json')
        with self.assertRaises(StateError):
            SOSMonitor(self.beacons,self.v1path+'-wrong')
        other=self.tmp.name+'/wrong.json'; init_state(other,scope=self.scope)
        with self.assertRaises(StateError):
            SOSMonitor(self.beacons,other)

    def test_invalid_clock_halts_without_publishing(self):
        self.wall=float('nan'); self.send()
        self.assertEqual(self.status.snapshot()['status'],'halted')
        self.assertEqual(self.status.snapshot()['sightings'],[])


if __name__ == '__main__':
    unittest.main()
