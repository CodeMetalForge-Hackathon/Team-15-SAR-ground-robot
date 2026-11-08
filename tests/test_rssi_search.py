"""RSSI decisions and the real HTTP discovery feed, without flight hardware."""
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from crazyflie import demo_mission as m
from crazyflie.rssi_search import DiscoveryRSSI, SearchUnavailable, search


class SearchTests(unittest.TestCase):
    def run_search(self, source):
        link = m.FakeLink()
        events = []
        emit = lambda event, **fields: events.append((event, fields))
        result = m.fly(link, lambda: link.now, emit, (0.6, 0, 0.127), 0.127, source)
        return result, link, events

    def test_signal_changes_selected_direction(self):
        for x in (-0.6, 0.6):
            result, link, _ = self.run_search(m.SimulatedRSSI((x, 0, 0.127)))
            self.assertEqual(result, (x, 0, 0.127))
            self.assertEqual(link.commands[-1], ('land',))

    def test_flat_signal_produces_no_candidate(self):
        class Flat:
            def read(self, *_): return -60.0
            def discard(self, *_): pass
        result, link, events = self.run_search(Flat())
        self.assertIsNone(result)
        self.assertTrue(any(event == 'rssi_uncertain' for event, _ in events))
        self.assertEqual(link.commands[-1], ('land',))

    def test_sparse_or_disconnected_feed_returns_home(self):
        for disconnected in (False, True):
            class Missing:
                def read(self, *_):
                    if disconnected:
                        raise SearchUnavailable('Disconnected')
                    return None
                def discard(self, *_): pass
            result, link, events = self.run_search(Missing())
            self.assertIsNone(result)
            self.assertTrue(any(event == 'search_unavailable' for event, _ in events))
            self.assertEqual(link.position[:3], (0, 0, 0))

    def test_temporary_peak_rejected_by_confirmation(self):
        class Peak:
            def __init__(self): self.visit = 0
            def discard(self, *_): self.visit += 1
            def read(self, *_): return -40.0 if self.visit == 2 else -60.0
        result, _, _ = self.run_search(Peak())
        self.assertIsNone(result)

    def test_http_dedup_stale_device_selection_and_disconnect(self):
        payload = dict(source='LIVE-HW', status='scanning', signals=[
            dict(id='target', count=1, age_s=0.1, rssi=-70),
            dict(id='other', count=100, age_s=0, rssi=-20)])
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(json.dumps(payload).encode())
            def log_message(self, *_): pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            source = DiscoveryRSSI(f'http://127.0.0.1:{server.server_port}', 'target')
            self.assertEqual(source.read(None, None), -70)
            self.assertIsNone(source.read(None, None))
            payload['signals'][0].update(count=2, age_s=2)
            self.assertIsNone(source.read(None, None))
            payload['signals'][0].update(count=3, age_s=0, rssi=-65)
            self.assertEqual(source.read(None, None), -65)
            payload['signals'][0]['count'] = 1
            with self.assertRaises(SearchUnavailable): source.read(None, None)
            payload['status'] = 'disconnected'
            with self.assertRaises(SearchUnavailable): source.read(None, None)
        finally:
            server.shutdown()
            server.server_close()
            worker.join()

    def test_unsafe_search_duration_refused(self):
        with self.assertRaises(SystemExit):
            m.main(['--dry-run', '--search-rounds', '2'])

    def test_rover_uses_selected_candidate(self):
        import contextlib
        import io
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(m.main(['--dry-run']), 0)
        rows = [json.loads(row) for row in output.getvalue().splitlines()]
        move = next(row for row in rows if row['event'] == 'rover_move')
        self.assertAlmostEqual(move['target_xy_inches'][0], 0.6 / m.INCH)
        self.assertAlmostEqual(move['target_xy_inches'][1], -8)
        # Default fixture is strongest at +x, not +y.
