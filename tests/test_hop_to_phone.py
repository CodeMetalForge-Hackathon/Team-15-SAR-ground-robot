"""crazyflie/hop_to_phone.py: open-loop hop profile and the live path against the fake Crazyflie."""
import math
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT), str(ROOT / "crazyflie"), str(ROOT / "tests")):
    sys.path.insert(0, p)

import hop_to_phone as hop  # noqa: E402


class Profile(unittest.TestCase):
    def setUp(self):
        self.segs = hop.profile(38000, 5 * 0.0254, 3 * 0.3048, 8.0)

    def test_rise_and_travel_physics(self):
        d = {n: (dur, pitch, a0) for n, dur, pitch, a0, _ in self.segs}
        t_c, t_a = d["rise"][0], d["forward"][0]
        self.assertAlmostEqual(0.15 * hop.G * t_c ** 2, 5 * 0.0254, places=6)       # climb height
        self.assertAlmostEqual(hop.G * math.tan(math.radians(8)) * t_a ** 2, 3 * 0.3048, places=6)
        self.assertEqual(d["forward"][1], 8.0)
        self.assertEqual(d["brake"][1], -8.0)
        self.assertAlmostEqual(d["brake"][0], t_a)

    def test_thrust_is_capped_and_ends_at_zero(self):
        self.assertTrue(all(a0 <= hop.CAP and a1 <= hop.CAP for *_, a0, a1 in self.segs))
        self.assertEqual(self.segs[-1][-1], 0.0)
        big = hop.profile(45000, 0.3, 1.8, 15.0)
        self.assertTrue(all(a0 <= hop.CAP for *_, a0, _ in big))

    def test_reverse_flips_the_tilt(self):
        r = {n: pitch for n, _, pitch, *_ in hop.profile(38000, 0.127, 0.9, 8.0, reverse=True)}
        self.assertEqual((r["forward"], r["brake"]), (-8.0, 8.0))

    def test_profile_only_without_live(self):
        self.assertEqual(hop.main([]), 0)

    def test_live_needs_hover_thrust(self):
        with self.assertRaises(SystemExit):
            hop.main(["--live-drone"])


class LiveAgainstFakeDrone(unittest.TestCase):
    def go(self, answer="hop", **world):
        from test_cf_bridge import use_fake_cflib
        use_fake_cflib()
        import cflib.crtp as crtp
        crtp.CLASSES = getattr(crtp, "CLASSES", [])
        from cflib.crazyflie import WORLD
        WORLD.reset(decks={}, log_rate=4.0, **world)
        with tempfile.TemporaryDirectory() as d:
            code = hop.main(["--live-drone", "--hover-thrust", "38000", "--uri", "ble://Crazyflie",
                             "--report", str(Path(d) / "r.json")], ask=lambda _p: answer)
        sp = [s for s in WORLD.drones[-1].setpoints if s[0] == "setpoint"]
        return code, sp, WORLD.drones[-1].setpoints

    def test_hop_runs_forward_then_brakes_and_lands(self):
        code, sp, allsp = self.go()
        self.assertEqual(code, 0)
        pitches = [s[2] for s in sp]
        self.assertGreater(max(pitches), 7.9)
        self.assertLess(min(pitches), -7.9)
        self.assertLess(pitches.index(max(pitches)), pitches.index(min(pitches)))   # forward before brake
        self.assertTrue(all(s[4] <= hop.CAP for s in sp))
        self.assertEqual(sp[-1][4], 0)
        self.assertEqual(allsp[-1], ("notify",))

    def test_tilt_cuts_the_motors(self):
        code, sp, _ = self.go(tilt=40.0)
        self.assertEqual(code, 1)
        self.assertTrue(all(s[4] == 0 for s in sp[6:]))    # only zero thrust after the unlock

    def test_anything_but_hop_cancels(self):
        code, sp, _ = self.go(answer="no")
        self.assertEqual(code, 1)
        self.assertEqual(sp, [])


if __name__ == "__main__":
    unittest.main()
