"""Drone scanner relay: the C app's packets rebuild lines her parsers read the same.

Builds firmware/crazyflie_scanner_app/src/t15_scanner.c for this PC (needs a C
compiler), feeds it scanner lines, decodes the packets with
sar_sim.scanner_codec and compares what discovery/server.py and ble_id.py see.
Run: python3 -m unittest discover -s tests -p "test_cf_relay.py"
"""
import ctypes
import os
import random
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from sar_sim import scanner_codec  # noqa: E402
from discovery.server import parse_advertisement  # noqa: E402
from ble_id import ROW  # noqa: E402

HOST = os.path.join(ROOT, "tests", "relay_host")


def adv_hex(*fields):
    out = b""
    for kind, value in fields:
        out += bytes([len(value) + 1, kind]) + value
    return out.hex().upper()


class Relay:
    def __init__(self, lib):
        self.lib = lib
        lib.relay_line.argtypes = [ctypes.c_char_p]
        lib.relay_time.argtypes = [ctypes.c_uint32]
        lib.relay_params.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                     ctypes.c_uint32, ctypes.c_uint16, ctypes.c_int]
        self.t = 0

    def params(self, rssi=-100, hz=5, cap=60, focus=None, wd=3000):
        a, b = scanner_codec.focus_params(focus)
        self.lib.relay_params(rssi, hz, cap, a, b, wd)

    def at(self, ms):
        self.t = ms
        self.lib.relay_time(ms)

    def feed(self, line):
        self.lib.relay_line(line.encode())
        out, buf = [], (ctypes.c_uint8 * 64)()
        while True:
            n = self.lib.relay_take(buf)
            if not n:
                return out
            out.append(bytes(buf[:n]))

    def counts(self):
        c = (ctypes.c_uint16 * 8)()
        self.lib.relay_counts(c)
        return dict(zip("lines sent rate weak bad full long land".split(), c))


class RelayTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cc = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")
        if not cc:
            raise unittest.SkipTest("no C compiler")
        cls.tmp = tempfile.mkdtemp()
        cls.so = os.path.join(cls.tmp, "librelay.so")
        subprocess.run([cc, "-shared", "-fPIC", "-O1", "-Wall", "-Werror", "-I",
                        os.path.join(HOST, "stubs"), "-o", cls.so,
                        os.path.join(HOST, "shim.c")], check=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        # A fresh copy per test: the C file keeps its state in static variables.
        so = os.path.join(self.tmp, f"r{random.getrandbits(40)}.so")
        shutil.copy(self.so, so)
        self.r = Relay(ctypes.CDLL(so))
        self.r.params()
        self.r.at(10_000)

    def one(self, line):
        pkts = self.r.feed(line)
        self.assertLessEqual(len(pkts), 1)
        for p in pkts:
            self.assertLessEqual(len(p), 30)
        return scanner_codec.decode(pkts[0]) if pkts else None

    def test_heartbeat_is_rebuilt_exactly(self):
        for line in ("#HEARTBEAT,scanning=1,millis=123456,passive=1,discovery=1",
                     "#HEARTBEAT,scanning=0,millis=7,passive=1,discovery=1",
                     "#HEARTBEAT,scanning=1,millis=99"):
            self.assertEqual(self.one(line), line)

    def test_scan_events_pass_through(self):
        self.assertEqual(self.one("#SCAN_END,0"), "#SCAN_END,0")
        self.assertEqual(self.one("#SCAN_ERROR,start_failed"), "#SCAN_ERROR,start_failed")

    def test_token_rows_match_her_checker(self):
        rng = random.Random(1)
        for name in ("", "", "Pixel", "a-very-long-device-name"):
            raw = bytes([1, rng.randrange(1, 256)]) + rng.randbytes(14)
            h = raw.hex()
            uuid = f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:]}"
            line = f"{rng.randrange(-99, -30)},{name},{uuid}"
            out = self.one(line)
            a, b = ROW.fullmatch(line), ROW.fullmatch(out)
            self.assertIsNotNone(b, out)
            self.assertEqual(a[1], b[1])                    # rssi
            self.assertEqual(a[3], b[3])                    # the full token
            self.assertEqual(a[2][:11], b[2])               # name, cut to 11
            self.assertEqual(bool(a[2]), bool(b[2]))        # her "name_present" rule still fires
            self.r.at(self.r.t + 300)

    def test_uppercase_uuid_stays_rejected_by_her_checker(self):
        line = "-50,,0123ABCD-0000-0000-0000-000000000000"
        self.assertIsNone(ROW.fullmatch(line))
        self.assertIsNone(ROW.fullmatch(self.one(line)))

    def test_adverts_match_discovery_parser(self):
        rng = random.Random(2)
        cases = [
            adv_hex((1, b"\x06"), (0xFF, b"\x4c\x00\x10\x05\x01")),           # Apple, no name
            adv_hex((1, b"\x06"), (9, b"Beacon-7")),                          # complete name
            adv_hex((8, b"Short")),                                           # short name
            adv_hex((9, "Café of the Longest Name Ever".encode())),           # long UTF-8 name
            adv_hex((9, b"x"), (0xFF, b"\x4c\x00")),                          # name + Apple
            adv_hex((0xFF, b"\x06\x00\x01\x09")),                             # Microsoft: no flag
            adv_hex((3, b"\x0f\x18"), (0x16, b"\x0f\x18\x55")) + "00",        # zero-length stop
            "",                                                               # empty payload
        ]
        for i, payload in enumerate(cases):
            addr = ":".join(f"{rng.randrange(256):02x}" for _ in range(6))
            line = f"#BLE,{rng.randrange(-95, -20)},{addr},{i % 4},{payload}"
            want = parse_advertisement(line)
            got = parse_advertisement(self.one(line))
            self.assertEqual(want[:2], got[:2], line)        # address id and rssi
            self.assertEqual(want[3], got[3], line)          # Apple flag
            wn, gn = want[2].encode(), got[2].encode()
            self.assertLessEqual(len(gn), 19)
            self.assertTrue(wn.startswith(gn), (want, got))
            if len(wn) <= 19:
                self.assertEqual(want[2], got[2])

    def test_malformed_adverts_are_dropped_like_hers(self):
        bad = ["#BLE,-50,aa:bb:cc:dd:ee:ff,0,0A09",                # truncated field
               "#BLE,-50,aa:bb:cc:dd:ee:ff,0,ABC",                 # odd hex
               "#BLE,-50,aa:bb:cc:dd:ee:ff,7,",                    # bad address type
               "#BLE,-50,aa:bb:cc:dd:ee,0,",                       # short address
               "#BLE,30,aa:bb:cc:dd:ee:ff,0,"]                     # rssi out of range
        for line in bad:
            with self.assertRaises(ValueError):
                parse_advertisement(line)
            self.assertEqual(self.r.feed(line), [], line)
        self.assertEqual(self.r.counts()["bad"], len(bad))

    def test_diagnostics_stay_on_the_drone(self):
        for line in ("#RAW,0201,uuid", "#CONFIG,passive=1", "#SCAN_START", ""):
            self.assertEqual(self.r.feed(line), [])

    def test_per_address_rate_limit_and_focus(self):
        a, f = "#BLE,-60,11:22:33:44:55:66,0,", "#BLE,-60,aa:bb:cc:dd:ee:ff,0,"
        self.r.params(hz=5, focus="aa:bb:cc:dd:ee:ff")
        sent_a = sent_f = 0
        for k in range(20):                     # 20 adverts each over 1 s
            self.r.at(20_000 + k * 50)
            sent_a += len(self.r.feed(a))
            sent_f += len(self.r.feed(f))
        self.assertEqual(sent_a, 5)            # 5 per second
        self.assertEqual(sent_f, 10)           # focus: every 100 ms

    def test_weak_adverts_dropped_but_focus_kept(self):
        self.r.params(rssi=-70, focus="aa:bb:cc:dd:ee:ff")
        self.assertEqual(self.r.feed("#BLE,-80,11:22:33:44:55:66,0,"), [])
        self.assertEqual(len(self.r.feed("#BLE,-80,aa:bb:cc:dd:ee:ff,0,")), 1)
        self.assertEqual(self.r.counts()["weak"], 1)

    def test_total_advert_budget(self):
        self.r.params(hz=50, cap=20)
        self.r.at(30_000)
        sent = 0
        for k in range(200):                    # 200 different devices at once
            sent += len(self.r.feed(f"#BLE,-50,00:00:00:00:{k // 256:02x}:{k % 256:02x},0,"))
        self.assertEqual(sent, 20)             # one second of budget
        self.r.at(30_500)
        self.assertEqual(len(self.r.feed("#BLE,-50,01:00:00:00:00:00,0,")), 1)

    def test_watchdog_lands_only_after_keepalive_and_while_flying(self):
        lib = self.r.lib
        self.r.at(1000)
        lib.relay_flying(1)
        self.r.at(9000)
        self.assertEqual(lib.relay_watchdog(), 0)       # never armed: no landing
        lib.relay_keepalive()
        self.r.at(11_500)
        self.assertEqual(lib.relay_watchdog(), 0)       # 2.5 s quiet: still fine
        self.r.at(12_100)
        self.assertEqual(lib.relay_watchdog(), 10)      # 3.1 s quiet: land once
        self.r.at(13_000)
        self.assertEqual(lib.relay_watchdog(), 10)
        self.r.at(15_200)
        self.assertEqual(lib.relay_watchdog(), 11)      # then stop the motors
        self.r.at(30_000)
        self.assertEqual(lib.relay_watchdog(), 11)      # disarmed until the next keep-alive

    def test_watchdog_quiet_when_landed_or_off(self):
        lib = self.r.lib
        lib.relay_keepalive()
        self.r.at(20_000)
        self.assertEqual(lib.relay_watchdog(), 0)       # on the ground
        self.r.params(wd=0)
        lib.relay_flying(1)
        self.assertEqual(lib.relay_watchdog(), 0)       # turned off


if __name__ == "__main__":
    unittest.main()
