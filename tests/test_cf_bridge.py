"""Crazyflie bridge + CrazyflieLink against a simulated drone (tests/fake_cflib).

The fake drone runs the real drone scanner app (compiled for this PC), so
these tests cover flying, the safety landings, and scanner lines reaching
the pseudo-serial port. They use real time (about 30 s in total), with
shorter landings and grace periods than the real defaults.
Run: python3 -m unittest discover -s tests -p "test_cf_bridge.py"
"""
import json
import math
import os
import select
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAKE = os.path.join(ROOT, "tests", "fake_cflib")
HOST = os.path.join(ROOT, "tests", "relay_host")
URI = "radio://0/80/2M/E7E7E7E7E7"


def use_fake_cflib():
    for name in [m for m in sys.modules if m == "cflib" or m.startswith("cflib.")]:
        del sys.modules[name]
    if FAKE not in sys.path:
        sys.path.insert(0, FAKE)
    sys.path.insert(1, ROOT)


def build_relay(tmp):
    cc = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")
    if not cc:
        raise unittest.SkipTest("no C compiler")
    so = os.path.join(tmp, "librelay.so")
    subprocess.run([cc, "-shared", "-fPIC", "-O1", "-I", os.path.join(HOST, "stubs"), "-o", so,
                    os.path.join(HOST, "shim.c")], check=True)
    return so


class Client:
    """A bare program talking to the bridge, for the crash/quiet tests."""

    def __init__(self, port):
        self.s = socket.create_connection(("127.0.0.1", port), timeout=3)
        self.f = self.s.makefile("rb")

    def call(self, **msg):
        self.s.sendall((json.dumps(msg) + "\n").encode())
        return json.loads(self.f.readline())

    def close(self):
        self.f.close()
        self.s.close()


class BridgeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        use_fake_cflib()
        cls.tmp = tempfile.mkdtemp()
        cls.so = build_relay(cls.tmp)
        global WORLD, Bridge, CrazyflieLink, parse_advertisement
        from cflib.crazyflie import WORLD
        from sar_sim.cf_bridge import Bridge
        from sar_sim.backends.crazyflie_backend import CrazyflieLink
        from discovery.server import parse_advertisement

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def start(self, **world):
        WORLD.reset(relay_so=self.so, log_rate=4.0, **world)
        self.logs = []
        self.ports = tempfile.mkdtemp()
        self.bridge = Bridge([URI], port=0, scanner_dir=self.ports, log=self.logs.append,
                             land_s=0.6, pilot_timeout=1.0).start()
        self.addCleanup(self.bridge.close)
        self.addCleanup(shutil.rmtree, self.ports, True)
        return self.bridge

    def link(self):
        return CrazyflieLink(URI, bridge=f"127.0.0.1:{self.bridge.port}", land_s=0.6)

    @property
    def cf(self):
        return WORLD.drones[-1]

    def wait_for(self, cond, timeout, msg):
        # Generous limits: returns as soon as cond() is true, so passing runs stay fast,
        # but a busy laptop running the whole suite doesn't cause false failures.
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if cond():
                return
            time.sleep(0.05)
        self.fail(msg + f"; bridge log: {self.logs}")

    # ---- flying --------------------------------------------------------------
    def test_fly_then_exit_lands_and_stops_motors(self):
        self.start()
        with self.link() as link:
            self.assertGreater(link.vbat, 3.9)
            link.takeoff(0.5, 1.0)
            link.wait(1.3)
            self.assertAlmostEqual(link.pose()[2], 0.5, delta=0.03)
            link.go_to(0.3, -0.2, 0.5, 0.0, 1.0)
            link.wait(1.3)
            x, y, z, _ = link.pose()
            self.assertAlmostEqual(x, 0.3, delta=0.03)
            self.assertAlmostEqual(y, -0.2, delta=0.03)
        self.wait_for(lambda: not self.cf.motors, 6, "motors still on after landing")
        self.assertFalse(self.cf.crashed)
        self.assertEqual([c[0] for c in self.cf.commands], ["takeoff", "go_to", "land", "stop"])
        # older firmware locks if commands just stop: zero thrust for a while, then hand back
        self.wait_for(lambda: self.cf.setpoints and self.cf.setpoints[-1] == ("notify",), 5, "no zero tail")
        zeros = [p for p in self.cf.setpoints if p[0] == "setpoint"]
        self.assertGreater(len(zeros), 20)
        self.assertTrue(all(p[4] == 0 for p in zeros))

    def test_exception_inside_flight_still_lands(self):
        self.start()
        with self.assertRaises(ZeroDivisionError):
            with self.link() as link:
                link.takeoff(0.4, 1.0)
                link.wait(1.1)
                1 / 0
        self.wait_for(lambda: not self.cf.motors, 6, "no landing after an exception")
        self.assertFalse(self.cf.crashed)

    def test_fence_and_battery_refusals(self):
        self.start(vbat=3.3)
        with self.link() as link:
            with self.assertRaises(RuntimeError):      # 3.3 V resting: refuse takeoff
                link.takeoff(0.5, 1.0)
        self.assertEqual(self.cf.commands, [])
        WORLD.drones[-1].vbat = 4.0
        time.sleep(0.5)                                # next battery log arrives
        with self.link() as link:
            link.takeoff(0.5, 1.0)
            with self.assertRaises(RuntimeError):      # outside the 1.5 m fence
                link.go_to(2.0, 0.0, 0.5, 0.0, 1.0)
            with self.assertRaises(RuntimeError):
                link.go_to(0.0, 0.0, math.nan, 0.0, 1.0)
        self.wait_for(lambda: not self.cf.motors, 8, "no landing")

    def test_second_program_cannot_take_over_a_flying_drone(self):
        self.start()
        with self.link() as link:
            link.takeoff(0.5, 1.0)
            other = Client(self.bridge.port)
            reply = other.call(op="go_to", id=1, x=0.5, y=0.0, z=0.5, d=1.0)
            other.close()
            self.assertFalse(reply["ok"])
            self.assertIn("another program", reply["error"])
            link.wait(0.5)

    def test_no_position_deck_refuses_to_start(self):
        WORLD.reset(relay_so=self.so, decks={"bcZRanger2": "1"}, log_rate=4.0)
        logs = []
        bridge = Bridge([URI], port=0, scanner_dir=None, log=logs.append)
        with self.assertRaises(RuntimeError) as err:
            bridge.start()
        self.assertIn("positioning deck", str(err.exception))
        self.assertIn("['bcZRanger2']", str(err.exception))      # says what IS attached
        self.assertFalse(any("link lost" in m for m in logs), logs)  # closing is not a lost link

    def test_bench_mode_needs_no_deck_and_never_flies(self):
        WORLD.reset(relay_so=self.so, decks={}, log_rate=4.0, beacon=(0.5, 0.0))
        self.logs, self.ports = [], tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.ports, True)
        self.bridge = Bridge(["usb://0"], port=0, scanner_dir=self.ports, log=self.logs.append,
                             bench=True).start()
        self.addCleanup(self.bridge.close)
        c = Client(self.bridge.port)
        self.addCleanup(c.close)
        hello = c.call(op="hello")
        self.assertTrue(hello["bench"])
        self.assertEqual(hello["drones"][0]["decks"], [])
        self.wait_for(lambda: c.call(op="state", id=1)["vbat"] is not None, 2, "no battery reading")
        st = c.call(op="state", id=1)
        self.assertTrue(st["ok"])
        self.assertGreater(st["vbat"], 3.9)
        for msg in (dict(op="takeoff", id=1, h=0.5), dict(op="go_to", id=1, x=0, y=0, z=0.5)):
            reply = c.call(**msg)
            self.assertFalse(reply["ok"])
            self.assertIn("bench mode", reply["error"])
        self.assertEqual(self.cf.commands, [])                   # nothing reached the motors
        self.wait_for(lambda: os.path.exists(os.path.join(self.ports, "t15-scanner-1")), 2, "no port")

    # ---- safety landings -----------------------------------------------------
    def test_program_crash_lands_the_drone(self):
        self.start()
        c = Client(self.bridge.port)
        self.assertTrue(c.call(op="takeoff", id=1, h=0.5, d=1.0)["ok"])
        time.sleep(0.5)
        c.close()                                      # the flying program dies
        self.wait_for(lambda: any(c[0] == "land" for c in self.cf.commands), 4.0, "no landing")
        self.wait_for(lambda: not self.cf.motors, 8, "motors still on")
        self.assertFalse(self.cf.crashed)

    def test_quiet_program_lands_the_drone(self):
        self.start()
        c = Client(self.bridge.port)
        c.call(op="takeoff", id=1, h=0.5, d=1.0)
        t0 = time.monotonic()
        self.wait_for(lambda: any(c[0] == "land" for c in self.cf.commands), 6.0, "no landing")
        self.assertGreater(time.monotonic() - t0, 0.9)  # waited the 1 s test grace period
        c.close()

    def test_low_battery_in_flight_lands(self):
        self.start(drain=1.0)                          # fake: lose 1 V per second
        with self.link() as link:
            link.takeoff(0.5, 1.0)
            end = time.monotonic() + 6.0
            while time.monotonic() < end and not any(c[0] == "land" for c in self.cf.commands):
                link.wait(0.1)
        self.assertTrue(any("battery" in m for m in self.logs), self.logs)

    def test_radio_loss_drone_app_lands_on_its_own(self):
        self.start()
        c = Client(self.bridge.port)
        c.call(op="takeoff", id=1, h=0.5, d=1.0)
        for _ in range(6):                             # a healthy pilot, until the radio dies
            time.sleep(0.2)
            c.call(op="ping")
        WORLD.drop_link_at = time.monotonic()          # host can no longer reach the drone
        self.wait_for(lambda: self.cf.app_landings == 1, 8.0, "drone app did not land")
        self.wait_for(lambda: not self.cf.motors, 8.0, "drone app did not stop the motors")
        self.assertFalse(self.cf.crashed)
        self.assertNotIn("land", [k for k, *_ in self.cf.commands])   # the host's land never arrived
        c.close()

    # ---- scanner lines -------------------------------------------------------
    def test_scanner_lines_reach_the_serial_port(self):
        self.start(beacon=(0.5, 0.0))
        path = os.path.join(self.ports, "t15-scanner-1")
        fd = os.open(path, os.O_RDONLY | os.O_NOCTTY | os.O_NONBLOCK)
        self.addCleanup(os.close, fd)
        data, end = b"", time.monotonic() + 3.5
        while time.monotonic() < end:
            if select.select([fd], [], [], 0.1)[0]:
                data += os.read(fd, 65536)
        lines = data.decode().splitlines()
        self.assertTrue(any(l.startswith("#HEARTBEAT,scanning=1,") and l.endswith(",passive=1,discovery=1")
                            for l in lines), lines[:5])
        target = [parse_advertisement(l) for l in lines if "c0:ff:ee:00:00:01" in l]
        self.assertGreater(len(target), 5)               # 5 per second per address
        self.assertEqual(target[0][2], "T15-Target")
        others = [l for l in lines if l.startswith("#BLE,") and "5a:00" in l]
        self.assertTrue(others and all(parse_advertisement(l)[3] for l in others))  # Apple flag kept

    def test_direct_mode_without_a_bridge(self):
        WORLD.reset(relay_so=self.so, log_rate=4.0)
        with CrazyflieLink(URI, bridge="127.0.0.1:1", land_s=0.6) as link:
            link.takeoff(0.4, 1.0)
            link.wait(1.2)
            self.assertAlmostEqual(link.pose()[2], 0.4, delta=0.03)
        self.assertEqual([c[0] for c in self.cf.commands], ["takeoff", "land", "stop"])
        self.assertFalse(self.cf.motors)


if __name__ == "__main__":
    unittest.main()
