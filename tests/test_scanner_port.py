"""The bridge's scanner pty must only ever carry whole lines, even when the reader lags."""
import os
import re
import select
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from sar_sim.cf_bridge import ScannerPort  # noqa: E402

LINE = re.compile(r"^#BLE,-\d+,5a:00:00:00:[0-9a-f]{2}:[0-9a-f]{2},1,03FF4C00$")


def make_lines(n):
    return [f"#BLE,-{40 + i % 50},5a:00:00:00:{i // 256:02x}:{i % 256:02x},1,03FF4C00" for i in range(n)]


class ChokedPort(ScannerPort):
    """A pty that takes a few bytes, then nothing, like a full macOS pty."""

    def __init__(self, path):
        super().__init__(path)
        self.sent, self.calls = b"", 0

    def _write(self, data):
        self.calls += 1
        n = 0 if self.calls % 3 == 0 else min(len(data), 17)
        self.sent += data[:n]
        return n


class ScannerPortTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def test_partial_writes_never_split_a_line(self):
        port = ChokedPort(os.path.join(self.dir, "choked"))
        self.addCleanup(port.close)
        lines = make_lines(400)
        for line in lines:
            port.write_line(line)
        got = port.sent.decode().split("\n")[:-1]        # last piece may still be pending
        self.assertGreater(len(got), 20)
        self.assertGreater(port.dropped, 0)
        for line in got:
            self.assertIn(line, lines)
        idx = [lines.index(l) for l in got]
        self.assertEqual(idx, sorted(idx))                # in order, nothing glued together

    def test_real_pty_with_a_slow_reader(self):
        path = os.path.join(self.dir, "real")
        port = ScannerPort(path)
        self.addCleanup(port.close)
        fd = os.open(path, os.O_RDONLY | os.O_NOCTTY | os.O_NONBLOCK)
        self.addCleanup(os.close, fd)
        data = b""
        for i, line in enumerate(make_lines(3000)):
            port.write_line(line)
            if i % 400 == 399:                            # reader wakes up only now and then
                while select.select([fd], [], [], 0)[0]:
                    try:
                        chunk = os.read(fd, 65536)
                    except BlockingIOError:
                        break
                    if not chunk:
                        break
                    data += chunk
        got = data.decode().split("\n")[:-1]
        self.assertEqual([l for l in got if not LINE.match(l)], [])
        self.assertGreater(len(got), 10)

    def test_full_pty_with_no_reader(self):
        path = os.path.join(self.dir, "full")
        port = ScannerPort(path)
        self.addCleanup(port.close)
        for line in make_lines(6000):                     # ~330 KB: more than any pty holds
            port.write_line(line)
        self.assertGreater(port.dropped, 0)
        fd = os.open(path, os.O_RDONLY | os.O_NOCTTY | os.O_NONBLOCK)
        self.addCleanup(os.close, fd)
        data = b""
        while select.select([fd], [], [], 0.2)[0]:
            try:
                chunk = os.read(fd, 65536)
            except BlockingIOError:
                break
            if not chunk:
                break
            data += chunk
        got = data.decode().split("\n")
        self.assertEqual([l for l in got[:-1] if not LINE.match(l)], [])
        self.assertGreater(len(got), 10)


if __name__ == "__main__":
    unittest.main()
