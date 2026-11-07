import json
import os
import pty
import threading
import time
import unittest
from urllib.request import urlopen

from discovery.server import CAPACITY, Discovery, make_server, parse_advertisement, serial_worker

HEARTBEAT = "#HEARTBEAT,scanning=1,millis=1000,passive=1,discovery=1"
PACKET = "#BLE,-58,aa:bb:cc:dd:ee:ff,1,02010605ff4c000102050954657374"


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.now = 100.0
        self.state = Discovery(lambda: self.now)
        self.state.ingest(HEARTBEAT)

    def test_ad_fields_and_no_uuid_required(self):
        address, rssi, name, apple = parse_advertisement(PACKET)
        self.assertEqual((rssi, name, apple), (-58, "Test", True))
        self.assertEqual(address, "aa:bb:cc:dd:ee:ff/1")
        self.assertFalse(parse_advertisement(PACKET.replace("4c00", "004c"))[3])
        self.assertIsNone(parse_advertisement("-58,Test,01010390-0000-0000-0000-000000000000"))

    def test_malformed_data_never_becomes_a_signal(self):
        for line in [PACKET.replace("-58", "nan"), PACKET.replace("-58", "-200"),
                     PACKET.replace("aa:bb", "xx:bb"), PACKET + "0", PACKET + ",extra",
                     "#BLE,-58,aa:bb:cc:dd:ee:ff,1,05ff4c", PACKET.replace(",1,", ",9,")]:
            self.state.ingest(line)
        self.assertEqual(self.state.snapshot()["malformed"], 7)
        self.assertEqual(self.state.snapshot()["signals"], [])

    def test_aggregation_staleness_and_expiry(self):
        self.state.ingest(PACKET)
        self.state.ingest(PACKET.replace("-58", "-64"))
        signal = self.state.snapshot()["signals"][0]
        self.assertEqual((signal["count"], signal["rssi"], len(signal["history"])), (2, -64, 1))
        self.now += 6
        self.assertTrue(self.state.snapshot()["signals"][0]["stale"])
        self.assertEqual(self.state.snapshot()["status"], "unavailable")
        self.now += 55
        self.assertEqual(self.state.snapshot()["signals"], [])

    def test_addresses_not_exposed_and_sessions_not_linkable(self):
        self.state.ingest(PACKET)
        other = Discovery(lambda: self.now)
        other.ingest(HEARTBEAT)
        other.ingest(PACKET)
        self.assertNotIn("aa:bb:cc", json.dumps(self.state.snapshot()))
        self.assertNotEqual(self.state.snapshot()["signals"][0]["id"], other.snapshot()["signals"][0]["id"])

    def test_heartbeat_required_and_legacy_receiver_rejected(self):
        state = Discovery(lambda: self.now)
        state.ingest(PACKET)
        state.ingest("#HEARTBEAT,scanning=1,millis=1000")
        state.ingest(PACKET)
        self.assertEqual(state.snapshot()["packets"], 0)
        state.ingest(HEARTBEAT)
        state.ingest(PACKET)
        state.ingest("#SCAN_ERROR,start_failed")
        state.ingest(PACKET)
        self.assertEqual(state.snapshot()["packets"], 1)
        self.assertEqual(state.snapshot()["status"], "unavailable")

    def test_capacity_and_history_bounds(self):
        for i in range(CAPACITY + 10):
            self.state.ingest(PACKET.replace("aa:bb:cc:dd:ee:ff", f"aa:bb:cc:dd:{i//256:02x}:{i%256:02x}"))
        self.assertEqual(len(self.state.snapshot()["signals"]), CAPACITY)
        for i in range(100):
            self.now += .5
            self.state.ingest(HEARTBEAT)
            self.state.ingest(PACKET)
        history = next(s for s in self.state.snapshot()["signals"] if s["label"] == "Signal 267")["history"]
        self.assertLessEqual(len(history), 61)
        self.assertTrue(all(t <= 30 for t, r in history))

    def test_http_live_state_and_fixed_asset_paths(self):
        self.state.ingest(PACKET)
        server = make_server(self.state, port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        try:
            with urlopen(base + "/api/discovery") as response:
                self.assertEqual(response.headers["Cache-Control"], "no-store")
                self.assertEqual(json.load(response)["packets"], 1)
            with urlopen(base + "/") as response:
                self.assertIn(b"Nearby signals", response.read())
            with self.assertRaises(Exception) as caught:
                urlopen(base + "/../ble_state.py")
            self.assertEqual(caught.exception.code, 404)
            caught.exception.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_actual_serial_reader_with_fragmented_input(self):
        master, slave = pty.openpty()
        stop, state = threading.Event(), Discovery()
        thread = threading.Thread(target=serial_worker, args=(state, os.ttyname(slave), stop), daemon=True)
        thread.start()
        try:
            # Reader intentionally drains old bytes for two seconds.
            time.sleep(2.15)
            os.write(master, b"discard partial\n" + HEARTBEAT.encode() + b"\n")
            os.write(master, PACKET[:25].encode())
            time.sleep(.02)
            os.write(master, PACKET[25:].encode() + b"\n")
            deadline = time.monotonic() + 2
            while state.snapshot()["packets"] == 0 and time.monotonic() < deadline:
                time.sleep(.02)
            self.assertEqual(state.snapshot()["packets"], 1)
            os.close(master)
            master = None
            deadline = time.monotonic() + 2
            while state.snapshot()["status"] != "disconnected" and time.monotonic() < deadline:
                time.sleep(.02)
            self.assertEqual(state.snapshot()["status"], "disconnected")
        finally:
            stop.set()
            thread.join(timeout=3)
            if master is not None:
                os.close(master)
            os.close(slave)


if __name__ == "__main__":
    unittest.main()
