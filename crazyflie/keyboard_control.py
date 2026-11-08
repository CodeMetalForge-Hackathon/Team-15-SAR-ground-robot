#!/usr/bin/env python3
"""Step-based Crazyflie keyboard control. Simulation unless --live-drone is set."""
from __future__ import annotations

import argparse
import importlib
import json
import math
import os
import sys
import time

if __package__:
    from .demo_mission import FakeLink, Flight, ReturnRequired, ask
else:
    from demo_mission import FakeLink, Flight, ReturnRequired, ask

CONTROLS = "T takeoff | W/S forward/back | A/D left/right | R/F up/down | H home | +/- speed | Space/L/Q land | Ctrl+C land"
MIN_SPEED = 0.05
MAX_SPEED = 0.30
SPEED_STEP = 0.05

DIRECTIONS = {'w': (1, 0, 0), 's': (-1, 0, 0), 'a': (0, 1, 0),
              'd': (0, -1, 0), 'r': (0, 0, 1), 'f': (0, 0, -1)}


class Keyboard:
    """Nonblocking terminal input; restore POSIX terminal settings on every exit."""
    def __enter__(self):
        if not sys.stdin.isatty():
            raise ValueError('Keyboard control requires an interactive terminal')
        self.saved = None
        if os.name != 'nt':
            import termios
            import tty
            self.fd = sys.stdin.fileno()
            self.saved = termios.tcgetattr(self.fd)
            tty.setcbreak(self.fd)  # retain Ctrl+C signal handling
        return self

    def read(self):
        chars = []
        if os.name == 'nt':
            import msvcrt
            while msvcrt.kbhit():
                char = msvcrt.getwch()
                if char in ('\x00', '\xe0'):  # discard arrow/function key pairs
                    msvcrt.getwch()
                else:
                    chars.append(char)
        else:
            import select
            while select.select([self.fd], [], [], 0)[0]:
                chunk = os.read(self.fd, 4096)
                if not chunk:
                    return 'q'
                chars.extend(chunk.decode('utf-8', 'ignore'))
        # Prioritize landing over auto-repeat or other queued input.
        if any(char.lower() in (' ', 'q', 'l', '\x03', '\x04') for char in chars):
            return 'q'
        if '\x1b' in chars:
            return None  # do not interpret arrow escape sequences as movement
        return chars[-1].lower() if chars else None

    def __exit__(self, *_):
        if self.saved is not None:
            import termios
            termios.tcsetattr(self.fd, termios.TCSANOW, self.saved)


def control(link, clock, read_key, emit, height=0.5, step=0.1, pace=lambda: None, speed=0.2):
    """Called inside the backend context; return always causes landing on exit.

    One key issues a bounded waypoint. Speed keys affect the next move, even
    while busy. Landing is checked every 50 ms. No accumulated movement queue.
    """
    if not math.isfinite(speed) or not MIN_SPEED <= speed <= MAX_SPEED:
        raise ValueError('Speed must be between 0.05 and 0.30 m/s')
    flight = None
    busy_until = 0.0
    target = (0.0, 0.0, height)
    emit('keyboard_ready', controls=CONTROLS, speed_m_s=speed)
    while True:
        key = read_key()
        if key in (' ', 'q', 'l', '\x03', '\x04'):
            emit('landing_requested')
            return
        if flight is not None:
            try:
                flight.check()
            except ReturnRequired as exc:
                emit('landing_requested', reason=str(exc))
                return
        if key in ('+', '=', '-', '_'):
            change = SPEED_STEP if key in ('+', '=') else -SPEED_STEP
            speed = round(max(MIN_SPEED, min(MAX_SPEED, speed + change)), 2)
            emit('speed_changed', speed_m_s=speed, applies='next movement')
        if clock() >= busy_until:
            if key == 't' and flight is None:
                flight = Flight(link, clock, emit)
                try:
                    flight.check()
                except ReturnRequired as exc:
                    emit('landing_requested', reason=str(exc))
                    return
                link.takeoff(height, 2.0)
                busy_until = clock() + 2.5
                emit('takeoff', height_m=height)
            elif flight is not None and (key in DIRECTIONS or key == 'h'):
                pose = link.pose()
                if (len(pose) < 3 or any(not math.isfinite(v) for v in pose[:3])
                        or abs(pose[0]) > 1.5 or abs(pose[1]) > 1.5
                        or not 0.2 <= pose[2] <= 1.2):
                    emit('landing_requested', reason='Invalid/out-of-bounds position telemetry')
                    return
                if key == 'h':
                    proposed = (0.0, 0.0, pose[2])
                else:
                    proposed = tuple(pose[i] + DIRECTIONS[key][i] * step for i in range(3))
                target = (max(-1.5, min(1.5, proposed[0])),
                          max(-1.5, min(1.5, proposed[1])),
                          max(0.2, min(1.2, proposed[2])))
                if math.dist(target, proposed) > 1e-8:
                    emit('geofence_clamped', requested_xyz_m=list(proposed))
                distance = math.dist(target, pose[:3])
                if distance > 1e-8:
                    duration = max(0.2, distance / speed)
                    link.go_to(*target, 0.0, duration)
                    busy_until = clock() + duration + 0.25
                    emit('manual_waypoint', xyz_m=list(target), duration_s=duration,
                         speed_m_s=speed, average_speed_m_s=distance / duration)
        link.wait(0.05)
        pace()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--dry-run', action='store_true')
    mode.add_argument('--live-drone', action='store_true')
    parser.add_argument('--height-m', type=float, default=0.5)
    parser.add_argument('--step-m', type=float, default=0.1)
    parser.add_argument('--speed-m-s', type=float, default=0.2)
    parser.add_argument('--uri', default='radio://0/80/2M/E7E7E7E7E7')
    parser.add_argument('--backend-module', default='sar_sim.backends.crazyflie_backend')
    args = parser.parse_args(argv)
    if not math.isfinite(args.height_m) or not 0.2 <= args.height_m <= 1.2:
        parser.error('Height must be between 0.2 and 1.2 m')
    if not math.isfinite(args.step_m) or not 0.025 <= args.step_m <= 0.2:
        parser.error('Step must be between 0.025 and 0.2 m')
    if not math.isfinite(args.speed_m_s) or not MIN_SPEED <= args.speed_m_s <= MAX_SPEED:
        parser.error('Speed must be between 0.05 and 0.30 m/s')
    if not sys.stdin.isatty():
        parser.error('Run in an interactive terminal; keyboard input cannot be piped')
    link = FakeLink()
    clock = lambda: link.now
    pace = lambda: time.sleep(0.05)  # simulation must run at keyboard speed
    if args.live_drone:
        try:
            module = importlib.import_module(args.backend_module)
        except ImportError as exc:
            parser.error(f'Guide backend unavailable: {exc}')
        print('LIVE DRONE: confirm positioning deck, URI, origin, clear area and Gavin present.')
        if ask('Preflight complete?', ('yes', 'no')) != 'yes':
            return 1
        link = module.CrazyflieLink(args.uri)
        clock, pace = time.monotonic, lambda: None
    start = clock()

    def emit(event, **fields):
        print(json.dumps(dict(event=event, t_s=round(clock() - start, 3),
                              mode='LIVE-DRONE' if args.live_drone else 'SIMULATED', **fields)), flush=True)

    print(CONTROLS)
    print('Each accepted key moves one step. Terminal must have focus. Press T to take off.')
    try:
        with Keyboard() as keyboard:
            with link:
                control(link, clock, keyboard.read, emit, args.height_m, args.step_m, pace, args.speed_m_s)
        emit('drone_grounded')
        return 0
    except KeyboardInterrupt:
        emit('aborted', message='Backend context requested landing')
        return 130


if __name__ == '__main__':
    sys.exit(main())
