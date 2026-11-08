"""Tethered or free lift test: thrust rises slowly until the drone hops, Enter settles it.

    python3 -m sar_sim.cf_lift --uri usb://0             # on the USB cable
    python3 -m sar_sim.cf_lift --uri ble://Crazyflie     # over Bluetooth (pip install bleak)
    python3 -m sar_sim.cf_lift --uri radio://0/80/2M/E7E7E7E7E7

No positioning deck needed, and none is used: there is NO position or height
control. It can drift, and it climbs if you wait. Press Enter the moment it
lifts; thrust then ramps down over 0.7 s.

Safety:
  * It refuses to start if the drone reports it is locked or not ready, or
    the battery reads under 3.7 V.
  * You type "lift" to start. Enter or Ctrl+C stops it. Tilting past 35
    degrees cuts the motors.
  * Thrust never goes above 45000 of 65535 (default top 40000; a Crazyflie 2.x
    hovers near 36000-42000).
  * At the end it sends zero thrust for 2.5 s. Older firmware (2023.11) locks
    itself if the commands just stop, and then needs a restart.
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
import threading
import time

PEAK, CAP, RAMP_S, TOP_S, SETTLE_S, TAIL_S = 40000, 45000, 10.0, 1.0, 0.7, 2.5
TILT_DEG, MIN_VBAT = 35.0, 3.7


def status(info):
    if info is None:
        return "?"
    if int(info) & 64:
        return "LOCKED"
    return "ready" if int(info) & 8 else "not ready"


def run(uri="usb://0", peak=PEAK, ramp_s=RAMP_S, ask=input, stop=None, enter_stops=True, out=print):
    """Returns 'done', 'stopped', 'tilt', 'cancelled', 'locked', 'not ready' or 'battery'."""
    import cflib.crtp
    from cflib.crazyflie import Crazyflie
    from cflib.crazyflie.log import LogConfig
    from cflib.crazyflie.syncCrazyflie import SyncCrazyflie

    peak = max(0, min(int(peak), CAP))
    stop = stop or threading.Event()
    cache = os.path.join(tempfile.gettempdir(), "t15-cflib-cache")
    os.makedirs(cache, exist_ok=True)
    cflib.crtp.init_drivers()
    if uri.startswith("ble://"):
        from sar_sim import ble_link
        ble_link.register()
        if not any(n.endswith(".json") for n in os.listdir(cache)):
            out("Tip: connect once over USB first (python3 -m sar_sim.cf_lift --uri usb://0, then cancel)"
                " so the drone's variable lists are cached; some drone firmware can't send them over Bluetooth.")
        out("Connecting over Bluetooth (about 15-30 s)...")
    cf = Crazyflie(rw_cache=cache)
    scf = SyncCrazyflie(uri, cf=cf)
    scf.open_link()
    got = {}
    result, spun = "done", False
    try:
        toc = getattr(cf.log.toc, "toc", {})
        for i, names in enumerate([("pm.vbat", "supervisor.info", "stabilizer.thrust"),
                                   ("stabilizer.roll", "stabilizer.pitch", "motor.m1")]):
            names = [n for n in names if n.split(".")[1] in toc.get(n.split(".")[0], {})]
            if names:
                lc = LogConfig(name=f"t15lift{i}", period_in_ms=100)
                for n in names:
                    lc.add_variable(n)
                lc.data_received_cb.add_callback(lambda _t, d, _l: got.update(d))
                cf.log.add_config(lc)
                lc.start()
        end = time.monotonic() + 5.0
        while time.monotonic() < end and "pm.vbat" not in got:
            time.sleep(0.1)
        time.sleep(0.5)
        st, vb = status(got.get("supervisor.info")), float(got.get("pm.vbat", 0.0))
        out(f"Battery {vb:.2f} V, drone {st}")
        if st == "LOCKED":
            out("The drone is LOCKED: turn it off and on (or unplug USB and battery), keep it still, rerun.")
            return "locked"
        if st == "not ready":
            out("Not ready yet: keep it flat and still for a few seconds, then rerun.")
            return "not ready"
        if vb < MIN_VBAT:
            out("Battery too low or not connected.")
            return "battery"
        out(f"Thrust rises slowly toward {peak} over {ramp_s:.0f} s. PRESS ENTER THE MOMENT IT LIFTS.")
        if ask('Type "lift" and press Enter to start (anything else cancels): ').strip().lower() != "lift":
            out("Cancelled. Nothing was spun.")
            return "cancelled"
        if enter_stops:
            threading.Thread(target=lambda: (sys.stdin.readline(), stop.set()), daemon=True).start()
        cur = 0.0
        for _ in range(6):                               # zero thrust first: unlocks the thrust
            cf.commander.send_setpoint(0, 0, 0, 0)       # protection (sent a few times, for slow links)
            time.sleep(0.05)
        spun = True
        t0, nxt = time.monotonic(), 0.0
        while True:
            t = time.monotonic() - t0
            if stop.is_set():
                result = "stopped"
                break
            tilt = max(abs(got.get("stabilizer.roll", 0.0)), abs(got.get("stabilizer.pitch", 0.0)))
            if tilt > TILT_DEG:
                out(f"Tilted {tilt:.0f} degrees: motors cut.")
                result, cur = "tilt", 0.0
                break
            if t > ramp_s + TOP_S:
                break
            cur = peak * min(1.0, t / ramp_s)
            cf.commander.send_setpoint(0, 0, 0, int(cur))
            if t >= nxt:
                out(f"  t={t:4.1f} s  thrust {int(cur):5d}  motor1 {got.get('motor.m1', '?')}  "
                    f"battery {float(got.get('pm.vbat', 0.0)):.2f} V  drone {status(got.get('supervisor.info'))}")
                nxt += 0.5
            time.sleep(0.02)
        t1, start = time.monotonic(), cur              # settle down instead of dropping
        while cur > 0:
            cur = start * max(0.0, 1.0 - (time.monotonic() - t1) / SETTLE_S)
            cf.commander.send_setpoint(0, 0, 0, int(cur))
            time.sleep(0.02)
    except KeyboardInterrupt:
        result = "stopped"
    finally:
        try:
            if spun:
                end = time.monotonic() + TAIL_S        # zero thrust so old firmware doesn't lock
                while time.monotonic() < end:
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
    ap.add_argument("--uri", default="usb://0", help="usb://0, ble://Crazyflie or radio://...")
    ap.add_argument("--peak", type=int, default=PEAK, help=f"top thrust (capped at {CAP})")
    ap.add_argument("--ramp", type=float, default=RAMP_S, help="seconds to reach the top")
    args = ap.parse_args(argv)
    run(args.uri, args.peak, max(3.0, args.ramp))


if __name__ == "__main__":
    main()
