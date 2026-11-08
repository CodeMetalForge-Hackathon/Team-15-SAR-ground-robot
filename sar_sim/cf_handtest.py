"""Hand test: spin the motors gently, always below the thrust that lifts the drone.

    python3 -m sar_sim.cf_handtest --uri usb://0

For testing on the table, or in your hand, before the Flow deck and Crazyradio
arrive. It needs no positioning deck and it never takes off. By default the
motors only just turn: thrust 6000 of 65535, about a sixth of hover. A
Crazyflie 2.x needs about 36000 to hover; this script never goes above 25000.
If a motor doesn't start at 6000, step up with --thrust 8000, then 10000.

What it checks: the cable/radio link, that all four motors spin under the
drone's own stabilizer, and how far the battery voltage dips under load.

Safety:
  * You type "spin" to start. Press Enter (or Ctrl+C) to stop the motors at once.
  * Thrust ramps up over 1.5 s, holds, then ramps down. About 4 s in total.
  * If this program dies, the drone's own watchdog stops the motors within 2 s.
  * It refuses to start with a missing or low battery (under 3.7 V).
Hold the drone by its body under the battery, with fingers clear of all four props.
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
import threading
import time

HOVER = 36000          # Crazyflie 2.x base hover thrust (firmware PID_VEL_THRUST_BASE)
HARD_CAP = 25000       # never exceeded, whatever is asked
DEFAULT = 6000         # slowest useful spin: motors just turn
RAMP_UP_S, RAMP_DOWN_S = 1.5, 0.5
MIN_VBAT = 3.7


def run(uri="usb://0", thrust=DEFAULT, hold_s=2.0, ask=input, stop=None, enter_stops=True, out=print):
    """Returns 'done', 'stopped', 'cancelled' or 'battery'."""
    import cflib.crtp
    from cflib.crazyflie import Crazyflie
    from cflib.crazyflie.log import LogConfig
    from cflib.crazyflie.syncCrazyflie import SyncCrazyflie

    thrust = max(0, min(int(thrust), HARD_CAP))
    stop = stop or threading.Event()
    cache = os.path.join(tempfile.gettempdir(), "t15-cflib-cache")
    os.makedirs(cache, exist_ok=True)
    cflib.crtp.init_drivers()
    cf = Crazyflie(rw_cache=cache)
    scf = SyncCrazyflie(uri, cf=cf)
    scf.open_link()
    volts = []
    spun = False
    result = "done"
    try:
        lc = LogConfig(name="t15hand", period_in_ms=100)
        lc.add_variable("pm.vbat", "float")
        lc.data_received_cb.add_callback(lambda _t, d, _l: volts.append(float(d["pm.vbat"])))
        cf.log.add_config(lc)
        lc.start()
        time.sleep(1.5)
        resting = min(volts[-5:]) if volts else 0.0
        out(f"battery resting: {resting:.2f} V")
        if resting < MIN_VBAT:
            out("Battery missing or low: plug it in or charge it, then try again. Nothing was spun.")
            return "battery"
        out(f"Motors will spin to {thrust} of 65535 ({100 * thrust / HOVER:.0f}% of hover thrust): "
            "too little to lift off.")
        out("Hold the drone under the battery, fingers clear of the props, or set it flat on the table.")
        if ask('Type "spin" and press Enter to start (anything else cancels): ').strip().lower() != "spin":
            out("Cancelled. Nothing was spun.")
            return "cancelled"
        if enter_stops:
            threading.Thread(target=lambda: (sys.stdin.readline(), stop.set()), daemon=True).start()
            out("Spinning. Press Enter to stop at any time.")
        sup = getattr(cf, "supervisor", None)
        proto = getattr(getattr(cf, "platform", None), "get_protocol_version", lambda: -1)()
        if proto >= 12 and sup is not None and hasattr(sup, "send_arming_request"):
            sup.send_arming_request(True)          # older firmware arms itself
            time.sleep(0.3)
        mark = len(volts)
        for _ in range(6):                               # zero thrust first: unlocks the thrust
            cf.commander.send_setpoint(0, 0, 0, 0)       # protection (sent a few times, for slow links)
            time.sleep(0.05)
        spun = True
        t0 = time.monotonic()
        total = RAMP_UP_S + hold_s + RAMP_DOWN_S
        next_print = 0.0
        while True:
            t = time.monotonic() - t0
            if stop.is_set():
                result = "stopped"
                break
            if t >= total:
                break
            if t < RAMP_UP_S:
                k = t / RAMP_UP_S
            elif t < RAMP_UP_S + hold_s:
                k = 1.0
            else:
                k = max(0.0, 1.0 - (t - RAMP_UP_S - hold_s) / RAMP_DOWN_S)
            cf.commander.send_setpoint(0, 0, 0, int(thrust * k))
            if t >= next_print:
                v = volts[-1] if volts else float("nan")
                out(f"  t={t:3.1f} s  thrust {int(thrust * k):5d}  battery {v:.2f} V")
                next_print += 0.5
            time.sleep(0.02)
    except KeyboardInterrupt:
        result = "stopped"
    finally:
        try:
            end = time.monotonic() + 2.5               # zero thrust: older firmware locks if commands just stop
            while spun and time.monotonic() < end:
                cf.commander.send_setpoint(0, 0, 0, 0)
                time.sleep(0.05)
            cf.commander.send_notify_setpoint_stop()
        finally:
            scf.close_link()
    under_load = volts[mark:] if spun else []
    if under_load:
        out(f"Motors stopped ({result}). Lowest battery under load: {min(under_load):.2f} V "
            f"(resting {resting:.2f} V, dip {resting - min(under_load):.2f} V).")
    return result


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--uri", default="usb://0")
    ap.add_argument("--thrust", type=int, default=DEFAULT, help=f"peak thrust (capped at {HARD_CAP})")
    ap.add_argument("--hold", type=float, default=2.0, help="seconds at peak thrust (max 5)")
    args = ap.parse_args(argv)
    if args.thrust > HARD_CAP:
        print(f"--thrust {args.thrust} is above the {HARD_CAP} cap; using {HARD_CAP}.")
    run(args.uri, args.thrust, min(max(args.hold, 0.0), 5.0))


if __name__ == "__main__":
    main()
