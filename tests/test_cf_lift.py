"""Lift test (sar_sim/cf_lift.py) against the simulated drone.

Run: python3 -m unittest discover -s tests -p "test_cf_lift.py"
"""
import os
import sys
import threading
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tests"))
from test_cf_bridge import use_fake_cflib  # noqa: E402


class LiftTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        use_fake_cflib()
        global WORLD, lift
        from cflib.crazyflie import WORLD
        from sar_sim import cf_lift as lift
        lift.TAIL_S = 0.4                       # shorter zero tail in tests

    def go(self, peak=40000, ramp=1.0, answer="lift", stop_after=None, **world):
        WORLD.reset(decks={}, log_rate=4.0, **world)
        stop = threading.Event()
        if stop_after is not None:
            threading.Timer(stop_after, stop.set).start()
        lines = []
        result = lift.run("usb://0", peak, ramp, ask=lambda _p: answer, stop=stop,
                          enter_stops=False, out=lines.append)
        cf = WORLD.drones[-1]
        thrusts = [p[4] for p in cf.setpoints if p[0] == "setpoint"]
        return result, cf, thrusts, lines

    def test_full_ramp_reaches_the_top_then_settles_and_hands_back(self):
        result, cf, thrusts, _ = self.go(peak=30000)
        self.assertEqual(result, "done")
        self.assertEqual(thrusts[0], 0)                          # unlock first
        self.assertEqual(max(thrusts), 30000)
        self.assertEqual(thrusts[-1], 0)
        self.assertEqual(cf.setpoints[-1], ("notify",))          # zero tail, then hand back
        self.assertEqual(cf.commands, [])                        # never the position flight code

    def test_enter_stops_the_climb_early(self):
        result, _, thrusts, _ = self.go(peak=40000, ramp=4.0, stop_after=1.5)
        self.assertEqual(result, "stopped")
        self.assertLess(max(thrusts), 40000 * 0.6)              # stopped well before the top

    def test_thrust_never_passes_the_cap(self):
        _, _, thrusts, _ = self.go(peak=65000)
        self.assertLessEqual(max(thrusts), lift.CAP)

    def test_locked_drone_is_refused(self):
        result, _, thrusts, lines = self.go(info=68)
        self.assertEqual(result, "locked")
        self.assertEqual(thrusts, [])
        self.assertTrue(any("LOCKED" in l for l in lines))

    def test_not_ready_and_low_battery_are_refused(self):
        self.assertEqual(self.go(info=4)[0], "not ready")
        self.assertEqual(self.go(vbat=3.5)[0], "battery")

    def test_tilt_cuts_the_motors(self):
        result, _, thrusts, _ = self.go(tilt=40.0)
        self.assertEqual(result, "tilt")
        self.assertEqual(max(thrusts), 0)

    def test_anything_but_lift_cancels(self):
        result, _, thrusts, _ = self.go(answer="yes")
        self.assertEqual(result, "cancelled")
        self.assertEqual(thrusts, [])


if __name__ == "__main__":
    unittest.main()
