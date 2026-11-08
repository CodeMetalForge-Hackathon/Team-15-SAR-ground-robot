#!/usr/bin/env python3
"""RoverC Pro USB/Wi-Fi keyboard control; default is a hardware-free dry-run."""
import argparse
import os
import socket
import json
import getpass
from collections import deque
from pathlib import Path
import sys
import time

if __package__:
    from crazyflie.keyboard_control import Keyboard
else:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from crazyflie.keyboard_control import Keyboard

CONTROLS = 'WASD move | Z/C rotate | +/- motor power | I status | X stop | Space/Q stop and exit'


class Replies:
    def handle(self, data):
        self.buffer += data
        self.parse_replies()

    def parse_replies(self):
        if len(self.buffer) > 8192:
            raise RuntimeError('Invalid oversized receiver response')
        while b'\n' in self.buffer:
            raw, self.buffer = self.buffer.split(b'\n', 1)
            reply = raw.decode('ascii', 'replace').strip()
            if reply:
                print('M5:', reply, flush=True)
            if reply == 'OK MOVE' and self.pending_moves:
                self.pending_moves.popleft()
            if reply.startswith('ERR') or (reply.startswith('ROVERC_USB_V1') and
                    reply != 'ROVERC_USB_V1 READY=1 LOCKED=0'):
                raise RuntimeError('Receiver rejected commands: ' + reply)
        if self.pending_moves and time.monotonic() > self.pending_moves[0]:
            raise RuntimeError('No MOVE acknowledgement from M5; stopping')


class USBLink(Replies):
    def __init__(self, port):
        import serial
        options = {'exclusive': True} if os.name != 'nt' else {}
        self.serial = serial.Serial(port=None, baudrate=115200, timeout=0.1,
                                    write_timeout=1.0, **options)
        self.serial.port = port
        self.serial.dtr = False
        self.serial.rts = False
        self.pending_moves = deque()
        self.buffer = b''

    def __enter__(self):
        self.serial.open()
        try:
            time.sleep(2)  # tolerate reset/boot after opening USB
            self.serial.reset_input_buffer()
            self.send('STOP')
            self.send('HELLO')
            end = time.monotonic() + 8
            retry_at = time.monotonic() + 1
            while time.monotonic() < end:
                response = self.serial.readline(200).decode('ascii', 'replace').strip()
                if response == 'ROVERC_USB_V1 READY=1 LOCKED=0':
                    return self
                if response.startswith('ROVERC_USB_V1'):
                    raise RuntimeError('M5 reported ' + response + '; check base power or reset front-button lock')
                if time.monotonic() >= retry_at:
                    self.send('HELLO')
                    retry_at = time.monotonic() + 1
            raise RuntimeError('Rover receiver not ready; check firmware, base power and front-button lock')
        except BaseException:
            self.__exit__(*sys.exc_info())
            raise

    def send(self, text):
        self.serial.write((text + '\n').encode('ascii'))
        if text.startswith('MOVE '):
            self.pending_moves.append(time.monotonic() + 0.75)

    def poll(self):
        available = self.serial.in_waiting
        if available:
            self.buffer += self.serial.read(min(available, 4096))
        self.parse_replies()

    def __exit__(self, exc_type, exc, traceback):
        try:
            if self.serial.is_open:
                try:
                    self.send('STOP')
                except OSError:
                    if exc_type is None:
                        raise
        finally:
            self.serial.close()


class WiFiLink(Replies):
    def __init__(self, host, port=5000, token=None):
        self.host, self.port, self.token = host, port, token
        self.sock = None
        self.buffer = b''
        self.pending_moves = deque()

    def wait_reply(self, expected):
        end = time.monotonic() + 4
        while time.monotonic() < end:
            while b'\n' in self.buffer:
                raw, self.buffer = self.buffer.split(b'\n', 1)
                reply = raw.decode('ascii', 'replace').strip()
                if reply == expected:
                    return
                if reply.startswith('ROVERC_USB_V1') and 'LOCKED=1' in reply:
                    raise RuntimeError('Motor lock is active. Release the front M5 button and reset with the side reset/power button; reconnect Wi-Fi afterward.')
                if reply.startswith('ROVERC_USB_V1') and 'READY=0' in reply:
                    raise RuntimeError('Rover base not detected. Turn on the base rear switch, check battery and controller seating, then retry. With older receiver firmware, reset the M5 after powering the base.')
                if reply.startswith(('ERR', 'ROVERC_USB_V1')):
                    raise RuntimeError('Wi-Fi handshake rejected: ' + reply)
            data = self.sock.recv(4096)
            if not data:
                raise RuntimeError('Wi-Fi receiver disconnected during handshake')
            self.buffer += data
            if len(self.buffer) > 8192:
                raise RuntimeError('Invalid Wi-Fi handshake response')
        raise RuntimeError('Wi-Fi receiver handshake timed out')

    def __enter__(self):
        if not isinstance(self.token, str) or len(self.token) != 16 or any(c not in '0123456789abcdef' for c in self.token):
            raise ValueError('Pairing key must be the 16-character key shown on the M5')
        try:
            self.sock = socket.create_connection((self.host, self.port), timeout=2)
        except ConnectionRefusedError as exc:
            raise RuntimeError(
                f'Cannot reach rover TCP port {self.host}:{self.port}. For 192.168.4.1, '
                'join the rover-hosted Wi-Fi first. For a shared network, use the LAN IP '
                'shown on the M5 and ensure the network allows device-to-device traffic.'
            ) from exc
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        try:
            self.send('AUTH ' + self.token)
            self.wait_reply('OK AUTH')
            self.send('STOP')
            self.send('HELLO')
            self.wait_reply('ROVERC_USB_V1 READY=1 LOCKED=0')
            self.sock.setblocking(False)
            return self
        except BaseException:
            self.sock.close()
            self.sock = None
            raise

    def send(self, text):
        self.sock.sendall((text + '\n').encode('ascii'))
        if text.startswith('MOVE '):
            self.pending_moves.append(time.monotonic() + 0.75)

    def poll(self):
        for _ in range(4):
            try:
                data = self.sock.recv(4096)
            except BlockingIOError:
                break
            if not data:
                raise RuntimeError('Wi-Fi link disconnected; receiver pulse timeout requests stop')
            self.handle(data)
        self.parse_replies()

    def __exit__(self, exc_type, exc, traceback):
        try:
            if self.sock:
                try:
                    self.send('STOP')
                except OSError:
                    if exc_type is None:
                        raise
        finally:
            if self.sock:
                self.sock.close()
                self.sock = None


class DryLink:
    def __enter__(self): return self
    def send(self, text): print('SIMULATED:', text, flush=True)
    def __exit__(self, *_): self.send('STOP')


def control(link, read_key, sleep=time.sleep, power=20):
    """Each movement key sends a 250 ms firmware-limited pulse, not a distance."""
    while True:
        if hasattr(link, 'poll'):
            link.poll()
        key = read_key()
        if key in ('q', ' ', '\x03', '\x04'):
            return
        if key == 'x':
            link.send('STOP')
            print('Sent: STOP', flush=True)
        elif key == 'i':
            link.send('HELLO')
            print('Sent: status request', flush=True)
        elif key in ('+', '=', '-', '_'):
            power = max(5, min(50, power + (5 if key in ('+', '=') else -5)))
            print(f'Motor power: {power}/100 (applies to next pulse)', flush=True)
        elif key in ('w', 'a', 's', 'd', 'z', 'c'):
            link.send(f'MOVE {key} {power}')
            print(f'Sent: MOVE {key} {power} (250 ms pulse)', flush=True)
        sleep(0.02)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--dry-run', action='store_true')
    mode.add_argument('--wifi', metavar='HOST', help='Live rover IP; AP default is 192.168.4.1')
    parser.add_argument('--port', type=int, default=5000)
    parser.add_argument('--profile', type=Path, default=Path.home() / '.codex/roverc/connection.json',
                        help='Private pairing profile written by wifi_setup.py')
    mode.add_argument('--serial', help='Live M5StickC Plus serial device; requires receiver firmware')
    parser.add_argument('--power', type=int, default=20)
    args = parser.parse_args(argv)
    if not 5 <= args.power <= 50:
        parser.error('Motor power must be 5–50')
    if not 1 <= args.port <= 65535:
        parser.error('Port must be 1–65535')
    if not sys.stdin.isatty():
        parser.error('Use an interactive terminal')
    if args.wifi:
        token = None
        if args.profile.exists():
            if os.name != 'nt' and args.profile.stat().st_mode & 0o077:
                parser.error('Pairing profile must be private: chmod 600 on the profile file')
            try:
                token = json.loads(args.profile.read_text())['ap_password']
            except (ValueError, KeyError):
                parser.error('Invalid pairing profile; rerun wifi_setup.py')
        if token is None:
            token = getpass.getpass('Pairing key shown on M5 screen: ').strip()
        link = WiFiLink(args.wifi, args.port, token)
    elif args.serial:
        try:
            link = USBLink(args.serial)
        except ImportError:
            parser.error('Install pyserial in your Python environment first')
    else:
        link = DryLink()
    print(CONTROLS)
    print('Each movement key requests a 250 ms pulse; hold/repeat to continue. No movement on startup.')
    control_started = False
    try:
        with Keyboard() as keyboard:
            with link:
                control_started = True
                print('CONNECTED. Click this terminal, then press + to check keyboard input.', flush=True)
                control(link, keyboard.read, power=args.power)
        return 0
    except KeyboardInterrupt:
        return 130
    except (OSError, RuntimeError, ValueError) as exc:
        detail = 'Stop acknowledgement is not confirmed.' if control_started else 'No movement commands were sent by this session.'
        print(f'Rover connection failed: {exc}. {detail}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
