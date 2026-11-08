"""Synthetic negative controls for evidence grading; NOT hardware evidence."""
import datetime as dt
import hashlib
import hmac
import json
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from analyze_c1 import A1, assess

BASE = 1_800_000_000  # fixed Unix time on a 30-second boundary


def token(counter):
    header = b'\x01\x01' + counter.to_bytes(4, 'big')
    digest = hmac.new(bytes(range(32)), b'OLF/BLE-ID/v1' + header, hashlib.sha256).digest()[:10]
    return str(uuid.UUID(bytes=header + digest))


def write_capture(root, stage, duration, tokens):
    events = [(float(i), '#HEARTBEAT,scanning=1,millis=1000') for i in range(1, duration)]
    for offset, identifier in tokens:
        raw = '0201061107' + uuid.UUID(identifier).bytes[::-1].hex()
        events += [(offset, f'-60,,{identifier}'), (offset + .01, f'#RAW,{raw},{identifier}')]
    lines = [f'# capture_start_monotonic=1000 requested_s={duration}']
    for offset, text in sorted(events):
        stamp = dt.datetime.fromtimestamp(BASE + offset, dt.timezone.utc).isoformat(timespec='milliseconds')
        lines.append(f'{stamp.replace("+00:00", "Z")}\t{1000 + offset:.6f}\t{text}')
    lines.append(f'# capture_end_monotonic={1000 + duration}')
    path = root / f'capture_{stage}.tsv'
    path.write_text('\n'.join(lines) + '\n')
    return path


class AnalyzerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='C1_SYNTHETIC_')
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        write_capture(self.root, 'A_stopped', 30, [])
        write_capture(self.root, 'B_static', 60, [(1, A1)])
        write_capture(self.root, 'C_rotating', 120,
                      [(offset + 1, token((BASE + offset) // 30)) for offset in (0, 30, 60, 90)])

    def passes(self):
        return assess(self.root)['C1_E1_capture_pass']

    def test_valid_synthetic_run(self):
        self.assertTrue(self.passes())

    def test_beacon_while_stopped_fails(self):
        write_capture(self.root, 'A_stopped', 30, [(1, A1)])
        self.assertFalse(self.passes())

    def test_empty_negative_control_fails(self):
        (self.root / 'capture_A_stopped.tsv').write_text('')
        self.assertFalse(self.passes())

    def test_truncated_capture_fails(self):
        write_capture(self.root, 'C_rotating', 2, [(1, token(BASE // 30))])
        self.assertFalse(self.passes())

    def test_tampered_rotation_fails(self):
        good = token(BASE // 30)
        bad = good[:-1] + ('0' if good[-1] != '0' else '1')
        write_capture(self.root, 'C_rotating', 120, [(1, bad)])
        self.assertFalse(self.passes())

    def test_cached_batch_is_not_rotation(self):
        write_capture(self.root, 'C_rotating', 120,
                      [(1, token(BASE // 30 + delta)) for delta in (-1, 0, 1)])
        self.assertFalse(self.passes())

    def test_uuid_in_manufacturer_data_is_not_service(self):
        p = self.root / 'capture_B_static.tsv'
        p.write_text(p.read_text().replace('1107', '11ff'))
        self.assertFalse(self.passes())

    def test_scanner_stopped_fails(self):
        p = self.root / 'capture_A_stopped.tsv'
        p.write_text(p.read_text().replace('scanning=1', 'scanning=0'))
        self.assertFalse(self.passes())

    def test_bad_line_fails(self):
        p = self.root / 'capture_B_static.tsv'
        p.write_text(p.read_text() + 'not a serial evidence row\n')
        self.assertFalse(self.passes())

    def test_cli_failure_is_nonzero(self):
        (self.root / 'capture_A_stopped.tsv').write_text('')
        command = [sys.executable, str(Path(__file__).with_name('analyze_c1.py')), str(self.root)]
        p = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(p.returncode, 1)
        self.assertFalse(json.loads(p.stdout)['C1_E1_capture_pass'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
