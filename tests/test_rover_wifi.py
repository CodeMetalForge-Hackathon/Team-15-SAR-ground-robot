"""Real TCP transport tests with a loopback fake receiver; no physical motors."""
import contextlib
import io
import json
import os
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest

from rover.keyboard_control import WiFiLink
from rover.wifi_setup import save_profile

KEY = '0123456789abcdef'


class Receiver:
    def __init__(self, reject=False, disconnect=False):
        self.reject, self.disconnect = reject, disconnect
        self.commands = []
        self.error = None
        self.sock = socket.socket()
        self.sock.bind(('127.0.0.1', 0))
        self.sock.listen()
        self.port = self.sock.getsockname()[1]
        self.thread = threading.Thread(target=self.run, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def run(self):
        try:
            conn, _ = self.sock.accept()
            with conn:
                conn.settimeout(3)
                pending = b''
                while True:
                    data = conn.recv(4096)
                    if not data:
                        return
                    pending += data
                    while b'\n' in pending:
                        line, pending = pending.split(b'\n', 1)
                        line = line.decode()
                        self.commands.append(line)
                        if line.startswith('AUTH'):
                            conn.sendall(b'ERR AUTH\n' if self.reject else b'OK AUTH\n')
                            if self.reject:
                                return
                        elif line == 'HELLO':
                            # Deliberately fragment the status line.
                            conn.sendall(b'ROVERC_USB_V1 RE')
                            time.sleep(0.01)
                            conn.sendall(b'ADY=1 LOCKED=0\nMOTOR_STATUS I2C=1 VALUES=0,0,0,0\n')
                        elif line == 'STOP':
                            conn.sendall(b'OK STOP\n')
                        elif line.startswith('MOVE'):
                            if self.disconnect:
                                return
                            conn.sendall(b'OK MOVE\n')
        except BaseException as exc:
            self.error = exc

    def __exit__(self, *_):
        self.thread.join(3)
        self.sock.close()
        if self.error:
            raise self.error
        if self.thread.is_alive():
            raise RuntimeError('Fake receiver did not terminate')


class WiFiTests(unittest.TestCase):
    def test_auth_handshake_commands_and_stop_on_exit(self):
        with Receiver() as receiver, contextlib.redirect_stdout(io.StringIO()):
            with WiFiLink('127.0.0.1', receiver.port, KEY) as link:
                link.send('MOVE w 20')
                deadline = time.monotonic() + 1
                while link.pending_moves and time.monotonic() < deadline:
                    time.sleep(0.01)
                    link.poll()
                self.assertFalse(link.pending_moves)
        self.assertEqual(receiver.commands[0], 'AUTH ' + KEY)
        self.assertIn('MOVE w 20', receiver.commands)
        self.assertEqual(receiver.commands[-1], 'STOP')

    def test_wrong_pairing_key_is_rejected(self):
        with Receiver(reject=True) as receiver:
            with self.assertRaisesRegex(RuntimeError, 'AUTH'):
                with WiFiLink('127.0.0.1', receiver.port, KEY):
                    self.fail('Rejected authentication must not enter control')
        self.assertEqual(len(receiver.commands), 1)

    def test_disconnect_during_control_is_reported(self):
        with Receiver(disconnect=True) as receiver, contextlib.redirect_stdout(io.StringIO()):
            with WiFiLink('127.0.0.1', receiver.port, KEY) as link:
                link.send('MOVE w 20')
                deadline = time.monotonic() + 1
                with self.assertRaisesRegex(RuntimeError, 'disconnected'):
                    while time.monotonic() < deadline:
                        time.sleep(0.01)
                        link.poll()

    def test_invalid_key_never_opens_socket(self):
        with self.assertRaises(ValueError):
            with WiFiLink('127.0.0.1', 1, 'bad\nkey'):
                self.fail('Bad key must be rejected before connecting')

    def test_profile_is_private_and_atomic(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / 'private' / 'connection.json'
            save_profile(file, {'ap_password': KEY})
            self.assertEqual(json.loads(file.read_text())['ap_password'], KEY)
            if os.name != 'nt':
                self.assertEqual(file.stat().st_mode & 0o777, 0o600)
            self.assertEqual(len(list(file.parent.iterdir())), 1)

    def test_refused_connection_explains_network_modes(self):
        from unittest.mock import patch
        with patch('rover.keyboard_control.socket.create_connection', side_effect=ConnectionRefusedError(61, 'refused')):
            with self.assertRaisesRegex(RuntimeError, 'device-to-device traffic'):
                WiFiLink('192.168.4.1', token=KEY).__enter__()

    def test_handshake_explains_base_missing_and_motor_lock(self):
        for reply, message in ((b'ROVERC_USB_V1 READY=0 LOCKED=0\n', 'base not detected'),
                               (b'ROVERC_USB_V1 READY=1 LOCKED=1\n', 'Motor lock')):
            with self.subTest(reply=reply):
                link = WiFiLink('unused', token=KEY)
                link.buffer = reply
                with self.assertRaisesRegex(RuntimeError, message):
                    link.wait_reply('ROVERC_USB_V1 READY=1 LOCKED=0')
