"""Bluetooth link (sar_sim/ble_link.py) against a simulated Bluetooth Crazyflie.

The fake drone (tests/fake_bleak) follows the radio firmware's own rules,
for both the 2023.11 and the 2024.2+ ways of writing long packets.
Run: python3 -m unittest discover -s tests -p "test_ble_link.py"
"""
import os
import sys
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAKE = os.path.join(ROOT, "tests", "fake_bleak")


def use_fake_bleak():
    for name in [m for m in sys.modules if m == "bleak" or m.startswith("bleak.")]:
        del sys.modules[name]
    if FAKE not in sys.path:
        sys.path.insert(0, FAKE)
    if ROOT not in sys.path:
        sys.path.insert(1, ROOT)


class Pk:
    """Just enough of cflib's CRTPPacket for send_packet()."""

    def __init__(self, raw):
        self.header, self.data = raw[0], bytes(raw[1:])
        self.port, self.channel = (raw[0] & 0xF0) >> 4, raw[0] & 3


class BleLinkTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        use_fake_bleak()
        global bleak, ble_link
        import bleak
        from sar_sim import ble_link

    def connect(self, mode="old", name="Crazyflie"):
        drone = bleak.FakeDrone(mode=mode, name=name)
        bleak.DRONES[:] = [drone]
        drv = ble_link.BleDriver()
        drv.packet_factory = lambda header, data: bytes([header]) + bytes(data)
        self.errors = []
        drv.connect("ble://Crazyflie", None, self.errors.append)
        self.addCleanup(drv.close)
        return drv, drone

    def wait(self, cond, timeout=3.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if cond():
                return True
            time.sleep(0.01)
        return False

    # ---- the byte formats ------------------------------------------------------
    def test_reassembler_reads_the_firmwares_own_test_vectors(self):
        r = ble_link.Reassembler()
        self.assertEqual(r.feed(bytes([0x80, 0xF3])), b"\xf3")             # testBuildsSingleBytePacket
        nineteen = bytes(range(19))
        self.assertEqual(r.feed(bytes([0xB2]) + nineteen), nineteen)       # largest unfragmented, pid 1
        twenty = bytes(range(20))
        self.assertIsNone(r.feed(bytes([0xD3]) + twenty[:19]))             # smallest fragmented, pid 2
        self.assertEqual(r.feed(bytes([0x40]) + twenty[19:]), twenty)

    def test_bytes_captured_from_aurora_s_drone(self):
        """Real crtpDown notifications from the team drone (radio firmware 2024.2), Nov 2026."""
        r = ble_link.Reassembler(ble_link.FW2024_2)
        cap = ["9f0032333030334120616e642049206861766520", "9f3032344b42206f6620666c00",   # long console
               "8600617368210a",                                                         # "ash!\n"
               "98fc4142434445464748494a4b4c4d4e4f505152", "985455565765",               # long echo
               "86fc68656c6c6f",                                                         # "hello" echo
               "850063652e0a"]                                                           # "ce.\n"
        out = [r.feed(bytes.fromhex(h)) for h in cap]
        self.assertEqual([o for o in out if o is not None],
                         [b"\x00ash!\n", b"\xfchello", b"\x00ce.\n"])          # short ones intact
        self.assertEqual(r.damaged, 2)                                          # long ones dropped

    def test_reassembler_drops_a_packet_with_a_missing_piece(self):
        r = ble_link.Reassembler()
        self.assertIsNone(r.feed(bytes([0xD3]) + bytes(19)))
        self.assertIsNone(r.feed(bytes([0x20, 0x01])))                     # wrong pid
        self.assertEqual(r.feed(bytes([0x80, 0x07])), b"\x07")             # recovers on the next packet

    def test_uplink_matches_the_protocol_document_example(self):
        pk = bytes([0xFF]) + bytes(range(1, 21))                           # 21 bytes, as in ble.md
        (c1, w1), (c2, w2) = ble_link.uplink_writes(pk, 0, "full")
        self.assertEqual((c1, c2), (ble_link.CRTP_UP, ble_link.CRTP_UP))
        self.assertEqual(w1[0], 0x95)                                      # "First write: 95 ff 01 ..."
        self.assertEqual(w1[1:], pk[:19])
        self.assertEqual(w2, bytes([0x00]) + pk[19:])                      # "Second write: 00 19 20"
        self.assertEqual(ble_link.uplink_writes(pk, 0, "minus1")[0][1][0], 0x94)
        self.assertEqual(ble_link.uplink_writes(pk[:20], 0, None), [(ble_link.CRTP, pk[:20])])

    # ---- against the simulated drone -------------------------------------------------
    def test_finds_the_right_long_packet_rule_for_each_firmware(self):
        for mode, want, dialect in (("old", "minus1", "len1"), ("new", "full", "len1"),
                                    ("2024.2", "full", "2024.2")):
            drv, _ = self.connect(mode)
            self.assertEqual((drv.long_mode, drv.rx.dialect), (want, dialect), mode)
            self.assertEqual(drv.lossy, mode == "2024.2")
            drv.close()

    def test_2024_2_firmware_short_answers_work_long_ones_are_dropped_not_damaged(self):
        drv, drone = self.connect("2024.2")
        short, long_ = bytes([0x52, 1, 2, 3]), bytes([0x02]) + bytes(range(25))
        drone.downlink.extend([short, long_, bytes([0x22, 9]), long_, short])
        got = [drv.receive_packet(1.0) for _ in range(3)]
        self.assertEqual(got, [short, bytes([0x22, 9]), short])          # long ones never reach cflib
        self.assertIsNone(drv.receive_packet(0.3))
        self.assertEqual(drv.rx.damaged, 2)

    def test_2024_2_firmware_rebuilds_the_connect_handshake(self):
        drv, drone = self.connect("2024.2")
        drv.send_packet(Pk(bytes([0xFD])))                                # link source request
        pk = drv.receive_packet(2.0)
        self.assertEqual(pk, bytes([0xF1]) + b"Bitcraze Crazyflie" + bytes(12))

    def test_2024_2_firmware_says_to_cache_over_usb_when_a_list_is_damaged(self):
        drv, drone = self.connect("2024.2")
        drone.downlink.append(bytes([0x50]) + bytes(25))                  # a long log-TOC answer
        self.assertTrue(self.wait(lambda: any("over USB" in e for e in self.errors)))

    def test_long_uplinks_still_work_on_2024_2_firmware(self):
        drv, drone = self.connect("2024.2")
        goto = bytes([0x8C, 0x07, 0x00, 0x00]) + bytes(range(20))
        drv.send_packet(Pk(goto))
        self.assertTrue(self.wait(lambda: goto in drone.received))

    def test_long_packets_arrive_intact_on_both_firmwares(self):
        goto = bytes([0x8C, 0x07, 0x00, 0x00]) + bytes(range(20))          # a 24-byte high-level go_to
        for mode in ("old", "new", "2024.2"):
            drv, drone = self.connect(mode)
            drv.send_packet(Pk(goto))
            self.assertTrue(self.wait(lambda: goto in drone.received), mode)
            drv.close()

    def test_answers_are_collected_by_polling(self):
        drv, drone = self.connect("old")
        answers = [bytes([0x52, 1, 2, 3]), bytes([0x52]) + bytes(range(25)), bytes([0x22, 9])]
        drone.downlink.extend(answers)
        got = [drv.receive_packet(2.0) for _ in answers]
        self.assertEqual(got, answers)                                     # in order, long one rebuilt
        self.assertEqual(self.errors, [])

    def test_setpoints_are_merged_so_the_newest_one_wins(self):
        drv, drone = self.connect("old")
        drone.received.clear()
        for k in range(60):                                                # far faster than Bluetooth
            drv.send_packet(Pk(bytes([0x30]) + bytes(12) + k.to_bytes(2, "little")))
        self.assertTrue(self.wait(lambda: drone.received and drone.received[-1][-2:] == (59).to_bytes(2, "little")))
        setpoints = [p for p in drone.received if p[0] == 0x30]
        self.assertLess(len(setpoints), 60)                                # old ones were replaced

    def test_the_zero_thrust_unlock_is_never_merged_away(self):
        """The drone ignores thrust until it gets a zero-thrust setpoint (thrust lock)."""
        drv, drone = self.connect("2024.2")
        drone.received.clear()
        sp = lambda thrust: bytes([0x30]) + bytes(12) + thrust.to_bytes(2, "little")
        drv.send_packet(Pk(sp(0)))                                         # the unlock
        for k in range(1, 40):                                             # then a fast ramp
            drv.send_packet(Pk(sp(k * 1000)))
        self.assertTrue(self.wait(lambda: drone.received and drone.received[-1] == sp(39000)))
        thrusts = [int.from_bytes(p[13:15], "little") for p in drone.received if p[0] == 0x30]
        self.assertEqual(thrusts[0], 0)                                    # unlock arrived first
        drv.send_packet(Pk(sp(0)))                                         # and a stop is kept too
        drv.send_packet(Pk(sp(5000)))
        self.assertTrue(self.wait(lambda: drone.received[-1] == sp(5000)))
        self.assertIn(sp(0), drone.received[len(thrusts):])

    def test_other_packets_are_never_merged_or_reordered(self):
        drv, drone = self.connect("new")
        drone.received.clear()
        params = [bytes([0x22, k, 0]) for k in range(30)]
        for p in params:
            drv.send_packet(Pk(p))
        self.assertTrue(self.wait(lambda: len(drone.received) == 30))
        self.assertEqual(drone.received, params)

    def test_link_loss_is_reported(self):
        drv, drone = self.connect("old")
        drone.client.drop()
        self.assertTrue(self.wait(lambda: any("lost" in e or "failed" in e for e in self.errors)))

    def test_no_drone_in_range_fails_clearly(self):
        bleak.DRONES[:] = []
        drv = ble_link.BleDriver()
        with self.assertRaises(ConnectionError) as err:
            drv.connect("ble://Crazyflie", None, None)
        self.assertIn("phone app", str(err.exception))

    def test_has_everything_cflib_uses_on_a_link(self):
        drv = ble_link.BleDriver()
        for name in ("close", "get_name", "receive_packet", "send_packet", "needs_resending"):
            self.assertTrue(hasattr(drv, name), name)              # cflib reads link.<name>
        self.assertFalse(drv.needs_resending)

    def test_other_uris_are_left_to_other_drivers(self):
        with self.assertRaises(Exception):
            ble_link.BleDriver().connect("radio://0/80/2M/E7E7E7E7E7", None, None)

    def test_scan_lists_crazyflies_only(self):
        bleak.DRONES[:] = [bleak.FakeDrone(name="Crazyflie-A1B2C3", address="AA"),
                           bleak.FakeDrone(name="SomePhone", address="BB")]
        self.assertEqual(ble_link.BleDriver().scan_interface(), [["ble://AA", "Crazyflie-A1B2C3"]])


if __name__ == "__main__":
    unittest.main()
