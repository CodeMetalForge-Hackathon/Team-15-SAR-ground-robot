"""Rover command mapping, power limits and connection handshake, no real motors."""
import contextlib
import io
import sys
import types
import unittest
from unittest.mock import patch

from rover.keyboard_control import USBLink, control


class RoverTests(unittest.TestCase):
    def run_keys(self, keys):
        commands = []
        keyboard = iter(keys)
        link = types.SimpleNamespace(send=commands.append)
        with contextlib.redirect_stdout(io.StringIO()):
            control(link, lambda: next(keyboard), sleep=lambda _: None)
        return commands

    def test_mapping_speed_and_stop(self):
        self.assertEqual(self.run_keys(['w', '+', 'a', '-', 's', 'd', 'z', 'c', 'x', 'q']),
                         ['MOVE w 20', 'MOVE a 25', 'MOVE s 20', 'MOVE d 20',
                          'MOVE z 20', 'MOVE c 20', 'STOP'])

    def test_power_bounds(self):
        self.assertEqual(self.run_keys(['+'] * 20 + ['w'] + ['-'] * 30 + ['d', 'q']),
                         ['MOVE w 50', 'MOVE d 5'])

    def test_handshake_and_exit_stop(self):
        class Serial:
            def __init__(self, **kwargs):
                self.is_open = False
                self.writes = []
            def open(self): self.is_open = True
            def close(self): self.is_open = False
            def write(self, data): self.writes.append(data)
            def reset_input_buffer(self): pass
            def readline(self, _): return b'ROVERC_USB_V1 READY=1 LOCKED=0\n'
        with patch.dict(sys.modules, serial=types.SimpleNamespace(Serial=Serial)):
            with patch('rover.keyboard_control.time.sleep'):
                link = USBLink('FAKE')
                with link:
                    self.assertTrue(link.serial.is_open)
                self.assertEqual(link.serial.writes, [b'STOP\n', b'HELLO\n', b'STOP\n'])
                self.assertFalse(link.serial.is_open)

    def test_feedback_ack_error_and_timeout(self):
        from collections import deque
        for response, timeout, expected_error in (
                (b'OK MOVE\n', False, False),
                (b'ERR LOCKED\n', False, True),
                (b'', True, True)):
            with self.subTest(response=response, timeout=timeout):
                link = USBLink.__new__(USBLink)
                link.buffer = b''
                link.pending_moves = deque([0 if timeout else float('inf')])
                link.serial = types.SimpleNamespace(in_waiting=len(response), read=lambda n: response)
                with contextlib.redirect_stdout(io.StringIO()):
                    if expected_error:
                        with self.assertRaises(RuntimeError):
                            link.poll()
                    else:
                        link.poll()
                        self.assertFalse(link.pending_moves)

    def test_status_key_is_not_a_movement(self):
        self.assertEqual(self.run_keys(['i', 'q']), ['HELLO'])

    def test_handshake_retries_and_preserves_not_ready_error(self):
        class Serial:
            def __init__(self, **kwargs):
                self.is_open = False
                self.writes = []
                self.responses = iter([b'', b'ROVERC_USB_V1 READY=1 LOCKED=0\n'])
                self.options = kwargs
            def open(self): self.is_open = True
            def close(self): self.is_open = False
            def write(self, data): self.writes.append(data)
            def reset_input_buffer(self): pass
            def readline(self, _): return next(self.responses)
        with patch.dict(sys.modules, serial=types.SimpleNamespace(Serial=Serial)):
            with patch('rover.keyboard_control.time.sleep'), patch(
                    'rover.keyboard_control.time.monotonic', side_effect=[0, 0, 0, 1.1, 1.1, 1.2]):
                link = USBLink('FAKE')
                with link:
                    self.assertEqual(link.serial.options['write_timeout'], 1.0)
                self.assertEqual(link.serial.writes.count(b'HELLO\n'), 2)

            class NotReady(Serial):
                def readline(self, _): return b'ROVERC_USB_V1 READY=0 LOCKED=0\n'
                def write(self, data):
                    if data == b'STOP\n' and b'HELLO\n' in self.writes:
                        raise OSError('Secondary write timeout during cleanup')
                    super().write(data)
            with patch.dict(sys.modules, serial=types.SimpleNamespace(Serial=NotReady)), patch(
                    'rover.keyboard_control.time.sleep'):
                link = USBLink('FAKE')
                with self.assertRaisesRegex(RuntimeError, 'READY=0'):
                    link.__enter__()
                self.assertFalse(link.serial.is_open)
