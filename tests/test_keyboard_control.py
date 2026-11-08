"""Manual flight commands, responsiveness and bounds without a real radio."""
import unittest

from crazyflie.demo_mission import FakeLink
from crazyflie.keyboard_control import control


class KeyboardControlTests(unittest.TestCase):
    def run_control(self, schedule, link=None):
        link = link or FakeLink()
        events = []
        pending = list(schedule)

        def read():
            if pending and link.now >= pending[0][0]:
                return pending.pop(0)[1]
            if link.now > 125:
                self.fail('Control loop failed to stop at the flight deadline')
            return None

        with link:
            control(link, lambda: link.now, read,
                    lambda event, **fields: events.append((event, fields)))
        return link, events

    def test_wasd_altitude_and_home(self):
        link, _ = self.run_control([(0, 't'), (3, 'w'), (4, 'a'), (5, 's'),
                                    (6, 'd'), (7, 'r'), (8, 'f'), (9, 'w'),
                                    (10, 'h'), (12, 'q')])
        points = [c[1:4] for c in link.commands if c[0] == 'go_to']
        self.assertEqual(points[:4], [(0.1, 0, 0.5), (0.1, 0.1, 0.5),
                                      (0, 0.1, 0.5), (0, 0, 0.5)])
        self.assertAlmostEqual(points[4][2], 0.6)
        self.assertEqual(points[-1], (0, 0, 0.5))
        self.assertEqual(link.commands[-1], ('land',))

    def test_no_motion_before_takeoff(self):
        link, _ = self.run_control([(0, 'w'), (0.1, 'r'), (0.2, 'q')])
        self.assertEqual(link.commands, [('land',)])

    def test_land_interrupts_takeoff_and_drops_busy_movement(self):
        link, _ = self.run_control([(0, 't'), (0.1, 'w'), (0.2, ' ')])
        self.assertLess(link.now, 0.3)
        self.assertEqual([c[0] for c in link.commands], ['takeoff', 'land'])

    def test_movement_is_not_queued(self):
        link, _ = self.run_control([(0, 't'), (0.1, 'w'), (0.2, 'w'), (3, 'q')])
        self.assertFalse(any(c[0] == 'go_to' for c in link.commands))

    def test_low_battery_and_deadline_land(self):
        low = FakeLink()
        low.vbat = 3.2
        link, _ = self.run_control([(0, 't')], low)
        self.assertEqual(link.commands, [('land',)])
        link, events = self.run_control([(0, 't')])
        self.assertLess(link.now, 120.1)
        self.assertTrue(any(e == 'landing_requested' for e, _ in events))

    def test_bounds_and_bad_pose(self):
        class Edge(FakeLink):
            def pose(self): return (1.49, 0, 0.5, 0)
        link, events = self.run_control([(0, 't'), (3, 'w'), (4, 'q')], Edge())
        self.assertEqual(next(c for c in link.commands if c[0] == 'go_to')[1], 1.5)
        self.assertTrue(any(e == 'geofence_clamped' for e, _ in events))
        class Bad(FakeLink):
            def pose(self): return (float('nan'), 0, 0.5, 0)
        link, _ = self.run_control([(0, 't'), (3, 'w')], Bad())
        self.assertEqual(link.commands[-1], ('land',))
        self.assertFalse(any(c[0] == 'go_to' for c in link.commands))

    def test_backend_error_still_lands(self):
        class Broken(FakeLink):
            def go_to(self, *_): raise RuntimeError('Radio error')
        link = Broken()
        with self.assertRaises(RuntimeError):
            self.run_control([(0, 't'), (3, 'w')], link)
        self.assertEqual(link.commands[-1], ('land',))


    def test_speed_changes_duration_without_changing_step(self):
        link, events = self.run_control([(0, 't'), (3, 'w'), (4, '+'),
                                         (4.1, 'w'), (5, '-'), (5.1, '-'),
                                         (5.2, 'w'), (7, 'q')])
        moves = [fields for event, fields in events if event == 'manual_waypoint']
        self.assertEqual([round(m['speed_m_s'], 2) for m in moves], [0.2, 0.25, 0.15])
        self.assertLess(moves[1]['duration_s'], moves[0]['duration_s'])
        self.assertGreater(moves[2]['duration_s'], moves[0]['duration_s'])
        self.assertAlmostEqual(moves[-1]['xyz_m'][0], 0.3)

    def test_speed_limits_and_adjustment_while_busy(self):
        schedule = [(0, 't')] + [(0.1 + i * 0.05, '=') for i in range(10)]
        schedule += [(1 + i * 0.05, '-') for i in range(12)] + [(3, 'w'), (6, 'q')]
        _, events = self.run_control(schedule)
        changes = [fields['speed_m_s'] for event, fields in events if event == 'speed_changed']
        self.assertEqual(max(changes), 0.3)
        self.assertEqual(min(changes), 0.05)
        move = next(fields for event, fields in events if event == 'manual_waypoint')
        self.assertEqual(move['speed_m_s'], 0.05)
        self.assertAlmostEqual(move['duration_s'], 2.0)
