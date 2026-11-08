"""Hand test (sar_sim/cf_handtest.py) against the simulated drone: thrust stays under the cap.

Run: python3 -m unittest discover -s tests -p "test_cf_handtest.py"
"""
import os
import sys
import threading
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tests"))
from test_cf_bridge import use_fake_cflib  # noqa: E402


class HandTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        use_fake_cflib()
        global WORLD, handtest
        from cflib.crazyflie import WORLD
        from sar_sim import cf_handtest as handtest

    def go(self, answer="spin", thrust=18000, hold=0.3, stop=None, **world):
        WORLD.reset(decks={}, log_rate=4.0, **world)
        lines = []
        result = handtest.run("usb://0", thrust, hold, ask=lambda _p: answer, stop=stop,
                              enter_stops=False, out=lines.append)
        cf = WORLD.drones[-1]
        thrusts = [p[4] for p in cf.setpoints if p[0] == "setpoint"]
        return result, cf, thrusts, lines

    def test_spins_gently_then_stops(self):
        result, cf, thrusts, lines = self.go()
        self.assertEqual(result, "done")
        self.assertEqual(thrusts[0], 0)                          # unlock first
        self.assertLessEqual(max(thrusts), 18000)
        self.assertGreater(max(thrusts), 17000)
        self.assertEqual(cf.setpoints[-1], ("notify",))
        self.assertEqual(thrusts[-1], 0)                          # zero tail before handing back
        self.assertTrue(any("Lowest battery under load" in l for l in lines), lines)
        self.assertEqual(cf.commands, [])                        # never a takeoff or go_to

    def test_thrust_never_goes_above_the_hard_cap(self):
        _, _, thrusts, _ = self.go(thrust=60000)
        self.assertLessEqual(max(thrusts), handtest.HARD_CAP)
        self.assertLess(handtest.HARD_CAP, handtest.HOVER)

    def test_default_is_the_slowest_spin(self):
        self.assertLessEqual(handtest.DEFAULT, handtest.HOVER / 5)
        WORLD.reset(decks={}, log_rate=4.0)
        handtest.run("usb://0", hold_s=0.2, ask=lambda _p: "spin", enter_stops=False, out=lambda *_: None)
        thrusts = [p[4] for p in WORLD.drones[-1].setpoints if p[0] == "setpoint"]
        self.assertLessEqual(max(thrusts), 6000)

    def test_anything_but_spin_cancels(self):
        result, cf, thrusts, _ = self.go(answer="yes")
        self.assertEqual(result, "cancelled")
        self.assertEqual(thrusts, [])

    def test_low_or_missing_battery_refuses(self):
        result, cf, thrusts, lines = self.go(vbat=3.4)
        self.assertEqual(result, "battery")
        self.assertEqual(thrusts, [])

    def test_stop_cuts_the_motors_early(self):
        stop = threading.Event()
        threading.Timer(1.0, stop.set).start()
        t0 = time.monotonic()
        result, cf, thrusts, _ = self.go(hold=5.0, stop=stop)
        self.assertEqual(result, "stopped")
        self.assertLess(time.monotonic() - t0, 6.5)             # battery read + ~1 s spin + 2.5 s zero tail
        self.assertEqual(cf.setpoints[-1], ("notify",))


if __name__ == "__main__":
    unittest.main()
