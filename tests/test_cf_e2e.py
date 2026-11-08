"""End to end, with Mabelle's own programs and a simulated drone (about 70 s).

  fake Crazyflie (real drone scanner app inside) -> bridge -> /tmp/t15-scanner-1
  -> her discovery server + BLE-ID checker (test keys)
  -> her crazyflie/demo_mission.py --live-drone, flying through CrazyflieLink

Checks that her RSSI search finds the side the phone is on, that the drone
lands with its motors off, and that her checker verifies the phone's token.
Opt-in because it is slow:
  T15_E2E=1 python3 -m unittest discover -s tests -p "test_cf_e2e.py" -v
"""
import builtins
import contextlib
import io
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tests"))
from test_cf_bridge import URI, build_relay, use_fake_cflib  # noqa: E402

SCOPE = "TESTKEY-t15-e2e"


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def get(url):
    with urllib.request.urlopen(url, timeout=2) as r:
        return json.loads(r.read())


ANSWERS = {"ready to fly": "yes", "human visible after": "yes", "Is a human visible": "yes",
           "phone visible": "yes", "condition": "injured"}


def fake_input(prompt=""):
    for key, answer in ANSWERS.items():
        if key in prompt:
            return answer
    return ""                                          # "press Enter" steps


@unittest.skipUnless(os.environ.get("T15_E2E"), "slow end-to-end test; set T15_E2E=1")
class EndToEnd(unittest.TestCase):
    def test_her_demo_flies_through_the_bridge(self):
        use_fake_cflib()
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        from cflib.crazyflie import WORLD
        from sar_sim.cf_bridge import Bridge
        from ble_keys import TEST_KEYS
        from ble_sim import row
        from ble_verify import counter_at, make_token

        def token_row(rssi):                           # her phone app's rotating token, alias 1
            return row(rssi, make_token(TEST_KEYS[1], counter_at(time.time()), alias=1))

        WORLD.reset(relay_so=build_relay(tmp), beacon=(1.0, 0.0), token_row=token_row)
        log = []
        bridge = Bridge([URI], port=0, scanner_dir=tmp, log=log.append).start()
        self.addCleanup(bridge.close)

        state = os.path.join(tmp, "state.json")
        env = dict(os.environ, PYTHONPATH=ROOT)
        subprocess.run([sys.executable, "-m", "ble_id", "init-state", "--state", state, "--scope", SCOPE],
                       cwd=ROOT, env=env, check=True, capture_output=True)
        port = free_port()
        server = subprocess.Popen([sys.executable, "-m", "discovery.server", "--serial",
                                   os.path.join(tmp, "t15-scanner-1"), "--port", str(port),
                                   "--test-keys", "--state", state, "--scope", SCOPE],
                                  cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(server.wait, 5)
        self.addCleanup(server.terminate)
        url = f"http://127.0.0.1:{port}"

        signal_id, end = None, time.monotonic() + 20
        while time.monotonic() < end and signal_id is None:
            time.sleep(0.5)
            try:
                d = get(url + "/api/discovery")
            except OSError:
                continue
            if d["status"] == "scanning":
                signal_id = next((s["id"] for s in d["signals"] if s["name"] == "T15-Target"), None)
        self.assertIsNotNone(signal_id, "discovery server never saw the target phone")

        sys.path.insert(0, os.path.join(ROOT, "crazyflie"))
        import demo_mission
        os.environ["T15_CF_BRIDGE"] = f"127.0.0.1:{bridge.port}"
        out, old_input = io.StringIO(), builtins.input
        builtins.input = fake_input
        try:
            with contextlib.redirect_stdout(out):
                code = demo_mission.main(["--live-drone", "--height-m", "0.5", "--signal-id", signal_id,
                                          "--scanner-on-drone", "--discovery-url", url, "--uri", URI,
                                          "--sample-seconds", "3", "--min-samples", "6"])
        finally:
            builtins.input = old_input
            os.environ.pop("T15_CF_BRIDGE", None)
        events = [json.loads(l) for l in out.getvalue().splitlines() if l.startswith("{")]
        names = [e["event"] for e in events]
        report = "\n".join(out.getvalue().splitlines()[-30:])
        self.assertEqual(code, 0, report)
        hotter = next(e for e in events if e["event"] == "hotter")
        self.assertGreater(hotter["candidate_xyz_m"][0], 0.3, report)     # the phone is at +x
        rover = next(e for e in events if e["event"] == "rover_move")
        self.assertGreater(rover["target_xy_inches"][0], 10, report)
        self.assertIn("drone_grounded", names)

        cf = WORLD.drones[-1]
        end = time.monotonic() + 4
        while cf.motors and time.monotonic() < end:
            time.sleep(0.1)
        self.assertFalse(cf.motors, "motors still on")
        self.assertFalse(cf.crashed)
        self.assertTrue(all(abs(t[0]) <= 1.5 and abs(t[1]) <= 1.5 for k, t, _ in cf.commands if k == "go_to"))

        beacons = get(url + "/api/beacons")
        self.assertEqual(beacons["status"], "verifying", beacons.get("detail"))
        self.assertEqual([s["alias"] for s in beacons["sightings"]], [1], beacons["counts"])
        print(f"\n  e2e: candidate {hotter['candidate_xyz_m']} m, rover target "
              f"{[round(v, 1) for v in rover['target_xy_inches']]} in, verified alias 1 "
              f"({beacons['sightings'][0]['verified_tokens']} tokens), counts {beacons['counts']}")


if __name__ == "__main__":
    unittest.main()
