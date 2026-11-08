"""Fly a Crazyflie by keyboard, no positioning deck: YOU are the pilot.

    python3 -m sar_sim.cf_keyfly --uri ble://Crazyflie       # Bluetooth (Mac, Linux, Windows)
    python3 -m sar_sim.cf_keyfly --uri usb://0               # on the USB cable
    python  -m sar_sim.cf_keyfly --uri ble://Crazyflie       # Windows PowerShell

The drone keeps itself level. Nothing holds its height or position: it drifts,
and it sinks as the battery drains. Watch it and correct with the keys.

    T          take off (thrust spools up to --base over 2 s, just under hover:
               press R until it lifts)
    R / F      more / less thrust (climb / sink)
    W / S      nudge forward / back      (a short tilt, then level again)
    A / D      nudge left / right
    Q / E      turn left / right
    Space / L  land (thrust eases to zero over 2 s)
    X          KILL: motors off now (it drops)
    Ctrl+C     land

Each key press is one nudge; hold a key to repeat it. If W moves it backward,
rerun with --flip-pitch (A/D: --flip-roll).

Safety: refuses a locked drone or a battery under 3.7 V; you type "fly" to arm;
thrust never goes above 45000 of 65535; tilting past 35 degrees cuts the
motors; it lands by itself after --max-time seconds or if the battery sags
under 3.1 V; at the end it sends zero thrust for 2.5 s so older firmware
(2023.11) doesn't lock itself.
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
import time

from sar_sim.cf_lift import CAP, MIN_VBAT, TILT_DEG, status

BASE, STEP, TILT, NUDGE_S, YAW_RATE = 36000, 500, 6.0, 0.35, 45.0
SPOOL_S, LAND_S, TAIL_S, MAX_TIME, FLY_VBAT, MIN_FLY_THRUST = 2.0, 2.0, 2.5, 90.0, 3.1, 20000
HZ = 50
CONTROLS = ("T take off | R/F thrust up/down | W/S forward/back | A/D left/right | "
            "Q/E turn | Space/L land | X kill | Ctrl+C land")


class Keys:
    """Non-blocking key presses from the terminal (Windows, macOS, Linux)."""

    def __enter__(self):
        self.saved = None
        if os.name != "nt":
            import termios
            import tty
            self.fd = sys.stdin.fileno()
            self.saved = termios.tcgetattr(self.fd)
            tty.setcbreak(self.fd)                       # keys arrive at once; Ctrl+C still works
        return self

    def read(self):
        chars = []
        if os.name == "nt":
            import msvcrt
            while msvcrt.kbhit():
                c = msvcrt.getwch()
                if c in ("\x00", "\xe0"):                # arrow / function keys: ignore
                    msvcrt.getwch()
                else:
                    chars.append(c)
        else:
            import select
            while select.select([self.fd], [], [], 0)[0]:
                chunk = os.read(self.fd, 64)
                if not chunk:
                    break
                chars.extend(chunk.decode("utf-8", "ignore"))
        return [c.lower() for c in chars]

    def __exit__(self, *_):
        if self.saved is not None:
            import termios
            termios.tcsetattr(self.fd, termios.TCSANOW, self.saved)


def run(uri="ble://Crazyflie", base=BASE, step=STEP, tilt=TILT, max_time=MAX_TIME,
        flip_pitch=False, flip_roll=False, ask=input, read_keys=None, out=print, clock=time.monotonic):
    """Returns 'landed', 'killed', 'tilt', 'timeout', 'battery', 'cancelled', 'locked' or 'not ready'."""
    import cflib.crtp
    from cflib.crazyflie import Crazyflie
    from cflib.crazyflie.log import LogConfig
    from cflib.crazyflie.syncCrazyflie import SyncCrazyflie

    base = max(MIN_FLY_THRUST, min(int(base), CAP))
    cache = os.path.join(tempfile.gettempdir(), "t15-cflib-cache")
    os.makedirs(cache, exist_ok=True)
    cflib.crtp.init_drivers()
    if uri.startswith("ble://"):
        from sar_sim import ble_link
        ble_link.register()
        out("Connecting over Bluetooth (about 15-30 s)...")
    cf = Crazyflie(rw_cache=cache)
    scf = SyncCrazyflie(uri, cf=cf)
    scf.open_link()
    got = {}
    spun, result, thrust = False, "landed", 0.0
    try:
        toc = getattr(cf.log.toc, "toc", {})
        for i, names in enumerate([("pm.vbat", "supervisor.info", "stabilizer.thrust"),
                                   ("stabilizer.roll", "stabilizer.pitch", "motor.m1")]):
            names = [n for n in names if n.split(".")[1] in toc.get(n.split(".")[0], {})]
            if names:
                lc = LogConfig(name=f"t15fly{i}", period_in_ms=100)
                for n in names:
                    lc.add_variable(n)
                lc.data_received_cb.add_callback(lambda _t, d, _l: got.update(d))
                cf.log.add_config(lc)
                lc.start()
        end = clock() + 5.0
        while clock() < end and "pm.vbat" not in got:
            time.sleep(0.1)
        time.sleep(0.5)
        st, vb = status(got.get("supervisor.info")), float(got.get("pm.vbat", 0.0))
        out(f"Battery {vb:.2f} V, drone {st}")
        if st == "LOCKED":
            out("The drone is LOCKED: turn it off and on, keep it flat and still, rerun.")
            return "locked"
        if st == "not ready":
            out("Not ready yet: keep it flat and still for a few seconds, then rerun.")
            return "not ready"
        if vb < MIN_VBAT:
            out("Battery too low or not connected.")
            return "battery"
        out(CONTROLS)
        out(f"Take-off thrust {base}. Nothing holds height or position: you fly it.")
        if ask('Type "fly" and press Enter to arm (anything else cancels): ').strip().lower() != "fly":
            out("Cancelled. Nothing was spun.")
            return "cancelled"

        for _ in range(6):                               # zero thrust first: unlocks the thrust
            cf.commander.send_setpoint(0, 0, 0, 0)       # protection (a few times, for slow links)
            time.sleep(0.05)
        spun = True
        sp, sr = (-1.0 if flip_pitch else 1.0), (-1.0 if flip_roll else 1.0)
        target = 0.0
        roll = pitch = yaw = 0.0
        nudge_until = 0.0
        flying_since = None
        land_from = land_t0 = None
        t0 = clock()
        nxt = 0.0
        out("Armed. Press T to take off.")
        while True:
            now = clock()
            t = now - t0
            killed = False
            for k in (read_keys() if read_keys else []):
                if k == "x":
                    killed = True
                    break
                if k in (" ", "l", "\x03") and flying_since is not None and land_from is None:
                    land_from, land_t0 = thrust, now
                    out("Landing...")
                elif k == "t" and flying_since is None:
                    flying_since, target = now, float(base)
                    out("Taking off.")
                elif flying_since is not None and land_from is None:
                    if k == "r":
                        target = min(float(CAP), target + step)
                    elif k == "f":
                        target = max(float(MIN_FLY_THRUST), target - step)
                    elif k in ("w", "s", "a", "d", "q", "e"):
                        roll = sr * {"a": -tilt, "d": tilt}.get(k, 0.0)
                        pitch = sp * {"w": tilt, "s": -tilt}.get(k, 0.0)
                        yaw = {"q": -YAW_RATE, "e": YAW_RATE}.get(k, 0.0)
                        nudge_until = now + NUDGE_S
            if killed:
                out("KILL: motors off.")
                result, thrust = "killed", 0.0
                break
            if now >= nudge_until:
                roll = pitch = yaw = 0.0
            ang = max(abs(got.get("stabilizer.roll", 0.0)), abs(got.get("stabilizer.pitch", 0.0)))
            if ang > TILT_DEG:
                out(f"Tilted {ang:.0f} degrees: motors cut.")
                result, thrust = "tilt", 0.0
                break
            if flying_since is not None and land_from is None:
                vnow = float(got.get("pm.vbat", 9.9))
                if now - flying_since > max_time:
                    out(f"{max_time:.0f} s up: landing by itself.")
                    result, land_from, land_t0 = "timeout", thrust, now
                elif 0 < vnow < FLY_VBAT and now - flying_since > SPOOL_S:
                    out(f"Battery {vnow:.2f} V under load: landing.")
                    result, land_from, land_t0 = "battery", thrust, now
            if land_from is not None:
                thrust = land_from * max(0.0, 1.0 - (now - land_t0) / LAND_S)
                roll = pitch = yaw = 0.0
                if thrust <= 0:
                    break
            elif flying_since is not None:
                ramp = min(1.0, (now - flying_since) / SPOOL_S)
                thrust = min(target, base * ramp) if ramp < 1.0 else target
            thrust = max(0.0, min(float(CAP), thrust))
            cf.commander.send_setpoint(roll, pitch, yaw, int(thrust))
            if t >= nxt:
                out(f"  t={t:5.1f} s  thrust {int(thrust):5d}  motor1 {got.get('motor.m1', '?')}  "
                    f"battery {float(got.get('pm.vbat', 0.0)):.2f} V")
                nxt += 1.0
            time.sleep(1.0 / HZ)
    except KeyboardInterrupt:
        if spun and thrust > 0:                          # Ctrl+C: ease down, don't drop
            t1, start = clock(), thrust
            try:
                while thrust > 0:
                    thrust = start * max(0.0, 1.0 - (clock() - t1) / LAND_S)
                    cf.commander.send_setpoint(0, 0, 0, int(thrust))
                    time.sleep(1.0 / HZ)
            except KeyboardInterrupt:
                pass
        result = "landed"
    finally:
        try:
            if spun:
                end = clock() + TAIL_S                   # zero thrust so old firmware doesn't lock
                while clock() < end:
                    cf.commander.send_setpoint(0, 0, 0, 0)
                    time.sleep(0.05)
                cf.commander.send_notify_setpoint_stop()
        finally:
            scf.close_link()
    if spun:
        out(f"Motors stopped ({result}). Drone {status(got.get('supervisor.info'))}.")
    return result


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--uri", default="ble://Crazyflie", help="ble://Crazyflie, usb://0 or radio://...")
    ap.add_argument("--base", type=int, default=BASE, help=f"take-off thrust (hover is ~36000-42000; cap {CAP})")
    ap.add_argument("--step", type=int, default=STEP, help="thrust change per R/F press")
    ap.add_argument("--tilt", type=float, default=TILT, help="degrees per W/A/S/D nudge (max 15)")
    ap.add_argument("--max-time", type=float, default=MAX_TIME, help="lands by itself after this many seconds")
    ap.add_argument("--flip-pitch", action="store_true", help="W moves it backward? use this")
    ap.add_argument("--flip-roll", action="store_true", help="A moves it right? use this")
    args = ap.parse_args(argv)
    with Keys() as keys:
        run(args.uri, args.base, max(100, min(args.step, 2000)), max(1.0, min(args.tilt, 15.0)),
            args.max_time, args.flip_pitch, args.flip_roll, ask=_ask_cooked(keys), read_keys=keys.read)


def _ask_cooked(keys):
    """input() needs the normal terminal mode for one line, then cbreak again."""
    def ask(prompt):
        if keys.saved is None:
            return input(prompt)
        import termios
        import tty
        termios.tcsetattr(keys.fd, termios.TCSANOW, keys.saved)
        try:
            return input(prompt)
        finally:
            tty.setcbreak(keys.fd)
    return ask


if __name__ == "__main__":
    main()
