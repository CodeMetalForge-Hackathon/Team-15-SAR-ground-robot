"""crazyflie/fly_to_phone.py: route, safety aborts, ground-scanner finding, mission control handoff."""
import json
import math
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "crazyflie"))

import fly_to_phone as ftp  # noqa: E402
from mission_control.protocol import NODES  # noqa: E402
from mission_control.server import make_server  # noqa: E402
from mission_control.state import Coordinator  # noqa: E402

TOKENS = {role: "PUBLIC_SYNTHETIC_TEST_TOKEN_FOR_" + role for role in ("operator", *NODES)}


def cfg(*extra):
    p = ftp.build_parser()
    args = p.parse_args(list(extra))
    ftp.validate(args, p)
    return args


def run(link=None, scanner=None, *extra):
    link = link or ftp.SimLink(speedup=math.inf)
    scanner = scanner if scanner is not None else ftp.SimScanner()
    m = ftp.Mission(link, cfg(*extra), scanner=scanner)
    with link:
        out = m.run()
    m.finish(out)
    return m, link


class Route(unittest.TestCase):
    def test_rises_five_inches_flies_five_feet_and_returns(self):
        m, link = run()
        self.assertEqual(m.outcome, "completed")
        kinds = [c[0] for c in link.commands]
        self.assertEqual(kinds, ["takeoff", "go_to", "go_to", "land"])
        self.assertAlmostEqual(link.commands[0][1], 5 * 0.0254)
        out, back = link.commands[1], link.commands[2]
        self.assertAlmostEqual(out[1], 5 * 0.3048)
        self.assertAlmostEqual(out[2], 0.0)
        self.assertAlmostEqual(back[1], 0.0)
        self.assertTrue(m.finding["detected"])
        self.assertIn("Phone found", m.summary_line())

    def test_waits_for_phone_and_stays_down_if_absent(self):
        m, link = run(None, ftp.SimScanner(present=False), "--wait-for-phone", "3")
        self.assertEqual(m.outcome, "no_phone")
        self.assertEqual(link.commands, [])
        self.assertIn("did not fly", m.summary_line())


class Safety(unittest.TestCase):
    def test_low_battery_lands_in_place_without_flying_back(self):
        class Sagging(ftp.SimLink):
            @property
            def vbat(self):
                return 3.1 if self.now > 6 else 4.0
        m, link = run(Sagging(speedup=math.inf))
        self.assertEqual(m.outcome, "aborted")
        self.assertEqual([c[0] for c in link.commands], ["takeoff", "go_to", "land"])
        self.assertIn("Battery", m.detail if m.phase == "aborted" else m.events[-2]["detail"])

    def test_low_battery_refuses_takeoff(self):
        link = ftp.SimLink(speedup=math.inf, vbat=3.5)
        m, link = run(link)
        self.assertEqual(m.outcome, "aborted")
        self.assertEqual(link.commands, [])

    def test_drift_out_of_corridor_aborts(self):
        class Drifting(ftp.SimLink):
            def pose(self):
                x, y, z, yaw = super().pose()
                return (x, y + (0.7 if self.now > 4 else 0.0), z, yaw)
        m, link = run(Drifting(speedup=math.inf))
        self.assertEqual(m.outcome, "aborted")
        self.assertIn("corridor", " ".join(e["detail"] for e in m.events))
        self.assertEqual(link.commands[-1], ("land",))

    def test_lost_pose_aborts(self):
        class Blind(ftp.SimLink):
            def pose(self):
                return (math.nan,) * 4 if self.now > 3 else super().pose()
        m, _ = run(Blind(speedup=math.inf))
        self.assertEqual(m.outcome, "aborted")

    def test_bridge_fence_refusal_explains_fix(self):
        class Fenced(ftp.SimLink):
            def go_to(self, x, *a):
                if x > 1.5:
                    raise RuntimeError(f"bridge refused go_to: ({x:.2f}, 0.00, 0.13) is outside the fence")
                super().go_to(x, *a)
        m, link = run(Fenced(speedup=math.inf))
        self.assertEqual(m.outcome, "aborted")
        self.assertIn("--fence 2.0", " ".join(e["detail"] for e in m.events))
        self.assertEqual(link.commands[-1], ("land",))

    def test_rejects_unsafe_arguments(self):
        for bad in (["--forward-ft", "9"], ["--height-in", "1"], ["--speed", "1"], ["--live-drone"]):
            with self.assertRaises(SystemExit):
                cfg(*bad)


class GroundScannerParsing(unittest.TestCase):
    def test_verified_alias_and_unverified_signal(self):
        g = ftp.GroundScanner("http://127.0.0.1:1", alias=2)
        g._get = lambda path: dict(mode_label="TEST KEYS", sightings=[
            dict(alias=1, label="Enrolled beacon 001", rssi=-50, last_verified_age_s=0.2, stale=False),
            dict(alias=2, label="Enrolled beacon 002", rssi=-70, last_verified_age_s=1.0, stale=False)])
        r = g.read_once()
        self.assertEqual((r["alias"], r["rssi"], r["verified"]), (2, -70, True))
        u = ftp.GroundScanner("http://127.0.0.1:1", signal_id="abc")
        u._get = lambda path: dict(signals=[dict(id="abc", label="Signal 01", rssi=-66, age_s=0.4,
                                                 stale=False, classification="Possible Apple device")])
        r = u.read_once()
        self.assertFalse(r["verified"])
        u._get = lambda path: dict(signals=[dict(id="abc", rssi=-66, age_s=9, stale=True)])
        self.assertIsNone(u.read_once())


class MissionControlHandoff(unittest.TestCase):
    def setUp(self):
        self.state = Coordinator()
        self.server = make_server(self.state, TOKENS, port=0)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def op(self, path, data=None):
        req = Request(self.url + path, None if data is None else json.dumps(data).encode(),
                      {"Authorization": "Bearer " + TOKENS["operator"], "Content-Type": "application/json"})
        with urlopen(req, timeout=2) as r:
            return json.load(r)

    def fly(self, stop_after=None):
        link = ftp.SimLink(speedup=12)
        m = ftp.Mission(link, cfg(), scanner=ftp.SimScanner())
        mc = ftp.MissionControl(self.url, TOKENS["crazyflie"], "SIMULATED", m.telemetry, period=0.1)
        m.mc = mc
        mc.start()
        phases = []
        if stop_after:
            def stopper():
                time.sleep(stop_after)
                phases.append(self.op("/api/state")["nodes"]["crazyflie"]["telemetry"]["mission"]["phase"])
                self.op("/api/stop", {})
            threading.Thread(target=stopper, daemon=True).start()
        with link:
            out = m.run()
        m.finish(out)
        mc.close(0)
        return m, link, phases

    def test_operator_sees_finding(self):
        m, _, _ = self.fly()
        self.assertEqual(m.outcome, "completed")
        t = self.op("/api/state")["nodes"]["crazyflie"]["telemetry"]
        self.assertTrue(t["ready"])
        self.assertEqual(t["mission"]["phase"], "on_ground")
        self.assertIn("Phone found", t["mission"]["summary"])
        self.assertTrue(t["mission"]["finding"]["detected"])

    def test_operator_stop_lands_the_drone(self):
        m, link, phases = self.fly(stop_after=0.8)
        self.assertIn(phases[0], ("takeoff", "outbound"))
        self.assertEqual(m.outcome, "aborted")
        self.assertIn("Operator", " ".join(e["detail"] for e in m.events))
        self.assertEqual(link.commands[-1], ("land",))
        self.assertLess(len([c for c in link.commands if c[0] == "go_to"]), 2)


class FixedSignal(ftp.SimScanner):
    def __init__(self, values):
        super().__init__()
        self.values = values

    def rssis(self, since=None):
        return list(self.values)


class SignalDistance(unittest.TestCase):
    CAL = ("--rssi-cal", "2:-52", "6:-64")

    def test_calibration_fit(self):
        cal = ftp.make_cal([(2, -52), (6, -64)])
        self.assertAlmostEqual(ftp.distance_ft(-52, cal), 2.0)
        self.assertAlmostEqual(ftp.distance_ft(-64, cal), 6.0)
        self.assertLess(ftp.distance_ft(-55, cal), ftp.distance_ft(-60, cal))

    def test_hop_follows_the_signal(self):
        m, link = run(None, FixedSignal([-58] * 10), "--distance-from-signal", *self.CAL)
        expected = ftp.distance_ft(-58, ftp.make_cal([(2, -52), (6, -64)]))
        self.assertEqual(m.outcome, "completed")
        self.assertAlmostEqual(link.commands[1][1], expected * 0.3048, places=3)
        self.assertEqual(m.estimate["used"], "signal")
        self.assertIn("Signal put the phone at", m.summary_line())

    def test_far_signal_is_clamped(self):
        m, link = run(None, FixedSignal([-80] * 10), "--distance-from-signal", *self.CAL)
        self.assertTrue(m.estimate["clamped"])
        self.assertAlmostEqual(link.commands[1][1], 6.0 * 0.3048, places=3)

    def test_sparse_signal_flies_fixed_distance_and_says_so(self):
        m, link = run(None, FixedSignal([-58, -59]), "--distance-from-signal", *self.CAL)
        self.assertEqual(m.estimate["used"], "fixed")
        self.assertAlmostEqual(link.commands[1][1], 5 * 0.3048, places=3)
        self.assertIn("too sparse", m.summary_line())

    def test_bad_calibration_is_rejected(self):
        for bad in (["2:-60", "6:-50"], ["2:-52", "2.5:-53"], ["x", "6:-60"]):
            with self.assertRaises(SystemExit):
                cfg("--distance-from-signal", "--rssi-cal", *bad)

    def test_calibrate_mode_prints_a_reading(self):
        self.assertEqual(ftp.main(["--calibrate-at", "3", "--fast"]), 0)


class EndToEndCli(unittest.TestCase):
    def test_dry_run_writes_report(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "r.json"
            self.assertEqual(ftp.main(["--fast", "--report", str(path)]), 0)
            rep = json.loads(path.read_text())
            self.assertEqual(rep["outcome"], "completed")
            self.assertEqual(rep["forward_ft"], 5.0)


if __name__ == "__main__":
    unittest.main()
