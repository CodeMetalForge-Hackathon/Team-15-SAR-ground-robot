#!/usr/bin/env python3
"""Configure RoverC Wi-Fi via USB; keep credentials outside the repository."""
import argparse
import getpass
import json
import os
from pathlib import Path
import sys
import tempfile
import time


def request(port, command, prefix):
    port.write((command + '\n').encode('utf-8'))
    end = time.monotonic() + 4
    while time.monotonic() < end:
        text = port.readline(1024).decode('utf-8', 'replace').strip()
        if text.startswith('ERR'):
            raise RuntimeError(text)
        if text.startswith(prefix):
            return json.loads(text) if prefix == '{' else text
    raise RuntimeError('No Wi-Fi configuration response; check receiver firmware and USB')


def save_profile(path, data):
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as out:
            json.dump(data, out)
            out.write('\n')
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--serial', required=True)
    action = p.add_mutually_exclusive_group()
    action.add_argument('--join', action='store_true', help='Prompt for shared 2.4 GHz Wi-Fi credentials')
    action.add_argument('--forget', action='store_true', help='Remove saved shared-network credentials')
    action.add_argument('--status', action='store_true', help='Only show status; do not export pairing key')
    p.add_argument('--profile', type=Path, default=Path.home() / '.codex/roverc/connection.json')
    args = p.parse_args(argv)
    try:
        import serial
        port = serial.Serial(port=None, baudrate=115200, timeout=0.2, write_timeout=1,
                             **({'exclusive': True} if os.name != 'nt' else {}))
        port.port, port.dtr, port.rts = args.serial, False, False
        port.open()
        try:
            time.sleep(2)
            port.reset_input_buffer()
            request(port, 'STOP', 'OK STOP')
            if args.join:
                name = input('Shared 2.4 GHz Wi-Fi name: ').strip()
                password = getpass.getpass('Wi-Fi password (blank for open network): ')
                if not 1 <= len(name.encode('utf-8')) <= 32 or not (len(password) == 0 or 8 <= len(password.encode('utf-8')) <= 63):
                    raise ValueError('SSID must be 1–32 bytes; password empty or 8–63 bytes')
                config = json.dumps(dict(ssid=name, password=password), ensure_ascii=False, separators=(',', ':'))
                if len(config.encode('utf-8')) + 10 >= 383:
                    raise ValueError('Encoded network configuration too long')
                request(port, 'WIFI_JOIN ' + config, 'OK WIFI_JOIN')
                print('Joining shared network; waiting up to 20 seconds…')
                deadline = time.monotonic() + 22
                while time.monotonic() < deadline:
                    status = request(port, 'WIFI_STATUS', '{')
                    if status['station_status'] != 'joining':
                        break
                    time.sleep(0.5)
            elif args.forget:
                request(port, 'WIFI_FORGET', 'OK WIFI_FORGET')
            if args.status:
                status = request(port, 'WIFI_STATUS', '{')
            else:
                status = request(port, 'WIFI_CREDENTIALS', '{')
                save_profile(args.profile, status)
                print('Private pairing profile saved:', args.profile)
            print('Rover network:', status['ap_ssid'], '| AP address:', status['ap_ip'])
            print('Shared network:', status['station_status'], '| address:', status['station_ip'])
            print('AP password/pairing key is shown on the M5 screen; credentials are not printed here.')
            if args.join and status['station_status'] != 'connected':
                print('Shared-network join failed; rover-hosted Wi-Fi remains available.', file=sys.stderr)
                return 1
            return 0
        finally:
            port.close()
    except (ImportError, OSError, ValueError, KeyError, RuntimeError) as exc:
        print('Wi-Fi setup failed:', exc, file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
