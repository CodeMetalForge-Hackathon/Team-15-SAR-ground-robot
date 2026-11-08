"""Keyboard pilot (sar_sim/cf_keyfly.py) against the simulated drone.

Run: python3 -m unittest discover -s tests -p "test_cf_keyfly.py"
"""
import os
import sys
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tests"))
from test_cf_bridge import use_fake_cflib  # noqa: E402


class Script:
    """Key presses at set times after arming."""

    def __init__(self, steps):
        self.steps, self.t0 = sorted(steps), None

    def __call__(self):
        if self.t0 is None:
            self.t0 = time.monotonic()
        t = time.monotonic() - self.t0
        out = []
        while self.steps and self.steps[0][0] <= t:
            out.append(self.steps.pop(0)[1])
        return out


class KeyflyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        use_fake_cflib()
        global WORLD, fly
        from cflib.crazyflie import WORLD
        from sar_sim import cf_keyfly as fly
        fly.TAIL_S, fly.SPOOL_S, fly.LAND_S = 0.3, 0.5, 0.5     # shorter in tests

    def go(self, steps, answer="fly", max_time=20.0, **world):
        WORLD.reset(decks={}, log_rate=10.0, **world)
        lines = []
        result = fly.run("usb://0", 38000, 500, 6.0, max_time, ask=lambda _p: answer,
                         read_keys=Script(steps), out=lines.append)
        cf = WORLD.drones[-1]
        sps = [p for p in cf.setpoints if p[0] == "setpoint"]
        return result, cf, sps, lines

    def test_take_off_climb_nudge_and_land(self):
        result, cf, sps, _ = self.go([(0.2, "t"), (1.0, "r"), (1.0, "r"), (1.3, "w"), (2.0, " ")])
        self.assertEqual(result, "landed")
        thrusts = [p[4] for p in sps]
        self.assertEqual(thrusts[:6], [0] * 6)                    # unlock first
        self.assertIn(38000, thrusts)                             # spooled up to take-off thrust
        self.assertEqual(max(thrusts), 39000)                     # two R presses
        pitched = [p for p in sps if p[2] != 0]
        self.assertTrue(pitched and all(p[2] == 6.0 for p in pitched))   # W = one short forward tilt
        self.assertLess(len(pitched), 0.6 * fly.HZ)               # ...not a lasting tilt
        self.assertEqual(sps[-1][1:], (0, 0, 0, 0))               # eased down, zero tail
        self.assertEqual(cf.setpoints[-1], ("notify",))
        self.assertEqual(cf.commands, [])                         # never the position flight code

    def test_kill_cuts_at_once(self):
        result, _, sps, _ = self.go([(0.1, "t"), (0.8, "x")])
        self.assertEqual(result, "killed")
        thrusts = [p[4] for p in sps]
        last = max(i for i, v in enumerate(thrusts) if v > 0)
        self.assertEqual(thrusts[last], 38000)                    # straight from flying thrust...
        self.assertTrue(all(v == 0 for v in thrusts[last + 1:]))   # ...to zero: no easing down

    def test_lands_by_itself_after_max_time(self):
        result, _, sps, lines = self.go([(0.1, "t")], max_time=1.0)
        self.assertEqual(result, "timeout")
        self.assertEqual(sps[-1][4], 0)
        self.assertTrue(any("landing by itself" in l for l in lines))

    def test_thrust_never_passes_the_cap(self):
        result, _, sps, _ = self.go([(0.1, "t")] + [(0.7, "r")] * 40 + [(1.2, " ")])
        self.assertLessEqual(max(p[4] for p in sps), fly.CAP)

    def test_tilt_cuts_the_motors(self):
        result, _, sps, _ = self.go([(0.1, "t")], tilt=50.0)
        self.assertEqual(result, "tilt")

    def test_locked_drone_and_cancel_spin_nothing(self):
        result, _, sps, _ = self.go([(0.1, "t")], info=68)
        self.assertEqual((result, sps), ("locked", []))
        result, _, sps, _ = self.go([(0.1, "t")], answer="no")
        self.assertEqual((result, sps), ("cancelled", []))

    def test_keys_before_take_off_do_nothing(self):
        result, _, sps, _ = self.go([(0.1, "r"), (0.2, "w"), (0.6, " "), (0.9, "x")])
        self.assertEqual(result, "killed")
        self.assertTrue(all(p[1:] == (0, 0, 0, 0) for p in sps))


if __name__ == "__main__":
    unittest.main()
