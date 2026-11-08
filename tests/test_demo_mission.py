"""Mission branching, coordinate conversion and flight interruption tests."""
import importlib.util
from pathlib import Path
import unittest

from crazyflie import demo_mission as m


class DemoMissionTests(unittest.TestCase):
    def test_origin_translation_and_units(self):
        point = m.drone_target((5, 5), 8, 0.5)
        self.assertAlmostEqual(point[0], 0.127)
        self.assertAlmostEqual(point[1], 0.3302)
        self.assertEqual(point[2], 0.5)

    def test_every_scenario_and_unobserved_is_not_cleared(self):
        for scenario in m.SCENARIOS:
            with self.subTest(scenario=scenario):
                observation = m.observe(scenario, False, lambda *a, **k: None)
                text, assets = m.report(observation)
                self.assertEqual(assets, "drone-only" if scenario == "empty" else "drone-and-rover")
                self.assertNotIn("cleared", text)
                if scenario == "hidden":
                    self.assertTrue(observation["human_visible"])
                    self.assertEqual(observation["condition"], "unknown")

    def test_flight_returns_before_budget_and_lands(self):
        link = m.FakeLink()
        m.fly(link, lambda: link.now, lambda *a, **k: None, (0.6, 0.0, 0.127), 0.127)
        self.assertLess(link.now, 120)
        self.assertEqual(link.commands[-1], ("land",))
        self.assertEqual(link.position[:3], (0.0, 0.0, 0.0))

    def test_low_battery_lands_without_takeoff(self):
        link = m.FakeLink()
        link.vbat = 3.2
        m.fly(link, lambda: link.now, lambda *a, **k: None, (0.1, 0.1, 0.5), 0.5)
        self.assertEqual(link.commands, [("land",)])

    def test_battery_drop_during_hover_lands_without_return(self):
        link = m.FakeLink()
        original_wait = link.wait

        def wait(seconds):
            original_wait(seconds)
            if link.now >= 10:
                link.vbat = 3.2

        link.wait = wait
        m.fly(link, lambda: link.now, lambda *a, **k: None, (0.1, 0.1, 0.5), 0.5)
        self.assertEqual(link.commands[-1], ("land",))
        self.assertEqual(sum(c[0] == "go_to" for c in link.commands), 1)

    def test_soft_and_hard_deadline(self):
        link = m.FakeLink()
        flight = m.Flight(link, lambda: link.now, lambda *a, **k: None)
        link.now = 120
        with self.assertRaises(m.ReturnRequired):
            flight.check()
        flight.check(returning=True)
        link.now = 140
        with self.assertRaises(m.ReturnRequired):
            flight.check(returning=True)

    def test_interrupt_lands_without_another_waypoint(self):
        link = m.FakeLink()

        def interrupt(_):
            raise KeyboardInterrupt

        link.wait = interrupt
        with self.assertRaises(KeyboardInterrupt):
            m.fly(link, lambda: link.now, lambda *a, **k: None, (0.1, 0.1, 0.5), 0.5)
        self.assertEqual([c[0] for c in link.commands], ["takeoff", "land"])

    def test_bad_live_height_refused_before_backend_import(self):
        with self.assertRaises(SystemExit) as error:
            m.main(["--live-drone"])
        self.assertEqual(error.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
