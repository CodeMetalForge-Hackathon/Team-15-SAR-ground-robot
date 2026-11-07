"""Exercise real capture I/O against a synthetic pseudo-terminal, not BLE."""
import errno
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path


@unittest.skipUnless(sys.platform == 'darwin', 'capture is a macOS tool')
class CaptureTests(unittest.TestCase):
    def test_deadline_and_complete_capture(self):
        master, slave = os.openpty()
        port = os.ttyname(slave)
        os.close(slave)
        done = threading.Event()

        def feed():
            while not done.wait(.1):
                try:
                    os.write(master, b'#HEARTBEAT,scanning=1,millis=1000\n')
                except OSError as exc:
                    if exc.errno != errno.EIO:
                        raise

        thread = threading.Thread(target=feed)
        thread.start()
        try:
            with tempfile.TemporaryDirectory(prefix='C1_SYNTHETIC_SERIAL_') as tmp:
                output = Path(tmp) / 'capture.tsv'
                command = [sys.executable, str(Path(__file__).with_name('capture_serial.py')),
                           port, '1', str(output)]
                start = time.monotonic()
                p = subprocess.run(command, capture_output=True, text=True, timeout=10)
                elapsed = time.monotonic() - start
                self.assertEqual(p.returncode, 0, p.stderr)
                self.assertGreaterEqual(elapsed, 1)
                self.assertLess(elapsed, 5)
                text = output.read_text()
                self.assertIn('# capture_end_monotonic=', text)
                self.assertIn('\t#HEARTBEAT,scanning=1,', text)
                self.assertIn('Saved ', p.stdout)
        finally:
            done.set()
            thread.join()
            os.close(master)

    def test_occupied_serial_port_is_rejected(self):
        master, slave = os.openpty()
        try:
            with tempfile.TemporaryDirectory(prefix='C1_SYNTHETIC_BUSY_') as tmp:
                command = [sys.executable, str(Path(__file__).with_name('capture_serial.py')),
                           os.ttyname(slave), '1', str(Path(tmp) / 'capture.tsv')]
                p = subprocess.run(command, capture_output=True, text=True, timeout=10)
                self.assertEqual(p.returncode, 1)
                self.assertIn('serial port busy', p.stderr)
        finally:
            os.close(slave)
            os.close(master)


if __name__ == '__main__':
    unittest.main(verbosity=2)
