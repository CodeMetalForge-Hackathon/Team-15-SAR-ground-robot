"""fleet_sim.py — fake hardware on a virtual serial port (dress rehearsal).

It pretends to be the ESP32-S3 gateway plus every drone behind it. The
homebase connects to it exactly as it would to the real USB port, so this
tests the serial path end to end before the hardware is ready.

    terminal 1:  python fleet_sim.py --pty
                 -> prints a port, e.g. /dev/pts/5 (Linux) or /dev/ttys004 (Mac)
    terminal 2:  python homebase.py --port /dev/pts/5

Use the same mission flags (--drones, --seed, --n, --cell-m, --key ...) in both.
Ctrl-C here prints how the homebase did against the hidden ground truth.
"""
from __future__ import annotations

import argparse
import os
import select
import sys
import time
import tty

from fleet.scenario import add_mission_args, add_sim_args, build_sim
from link import protocol as P


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pty", action="store_true", required=True, help="serve on a virtual serial port")
    ap.add_argument("--time", type=float, default=900.0)
    add_mission_args(ap)
    add_sim_args(ap)
    args = ap.parse_args()
    key = P.load_key(args.key)
    truth, grid, people, drones, gw = build_sim(args, key)

    master, slave = os.openpty()
    tty.setraw(slave)                      # no echo, no newline mangling: raw bytes like USB
    port = os.ttyname(slave)
    print(f"fake gateway + {len(drones)} drones on  {port}")
    same = [a for a in sys.argv[1:] if a != "--pty"]
    print(f"now run:  python homebase.py --port {port}" + (" " + " ".join(same) if same else ""))
    print(f"(hidden truth: {len(people)} people; loss {args.loss:.0%}"
          f"{', jam ' + args.jam if args.jam else ''})")

    t0 = time.monotonic()
    t_prev = 0.0
    next_status = 0.0
    try:
        while True:
            t = time.monotonic() - t0
            if t > args.time:
                break
            dt = max(1e-3, t - t_prev)
            t_prev = t
            r, _, _ = select.select([master], [], [], 0.02)
            if r:
                try:
                    gw.downlink(t, os.read(master, 4096))
                except OSError:
                    pass
            up = {d.id: d.step(t, dt) for d in drones}
            data = gw.uplink(t, up)
            if data:
                os.write(master, data)
            if t >= next_status:
                found = sum(p.first_detected is not None for p in people)
                states = " ".join(f"D{d.id}:{P.STATE[d.state]}" for d in drones)
                print(f"t={t:6.1f}s | {states} | people detected {found}/{len(people)} | "
                      f"uplink lost {gw.stats['up_lost']}/{gw.stats['up_sent']}")
                next_status = t + 5.0
    except KeyboardInterrupt:
        pass
    print("\n=== ground truth (only the simulator knows this) ===")
    for k, p in enumerate(people):
        seen = f"{p.first_detected:.1f}s" if p.first_detected is not None else "never"
        print(f"  person {k + 1} at ({p.x:.1f}, {p.y:.1f}) m: {p.status}, hr {p.hr} br {p.br}, "
              f"tag {hex(p.tag_id) if p.tag_id else '-'}, first detected {seen}")
    print("  compare with the homebase's results/casualties.json")


if __name__ == "__main__":
    main()
