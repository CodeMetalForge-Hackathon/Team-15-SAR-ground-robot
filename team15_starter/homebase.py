"""homebase.py — runs on the Jetson. Plans for every drone, talks to them
through the ESP32-S3 gateway, and writes the casualty list.

    # no hardware: drones + gateway are simulated, but the bytes are real
    python homebase.py --sim
    python homebase.py --sim --loss 0.3 --jam 60:120       # radio under jamming
    python homebase.py --sim --military --key "team15-secret"
    python homebase.py --sim --gif                          # saves fleet_search.gif

    # live dashboard in the browser (real satellite map), then open http://localhost:8080
    python homebase.py --sim --web
    python homebase.py --sim --web --origin 44.142,-71.681   # put the search on your venue

    # real hardware: ESP32-S3 on USB (Jetson: /dev/ttyACM0, Mac: /dev/cu.usbmodem*)
    python homebase.py --port /dev/ttyACM0 --web

    # dress rehearsal: fake hardware on a virtual serial port
    python fleet_sim.py --pty          # prints a port name, e.g. /dev/pts/5
    python homebase.py --port /dev/pts/5

CV code on the Jetson can send JSON to UDP 127.0.0.1:5515 (see fleet/hub.py on_local).
Outputs: results/casualties.json (priority order) and results/mission_log.jsonl.
"""
from __future__ import annotations

import argparse
import json
import socket
import sys
import time

import numpy as np

from fleet.hub import Homebase
from fleet.scenario import (SeqLease, add_mission_args, add_sim_args, build_sim, build_world,
                            hub_config, load_allies, make_hq, match_people, n_rovers, summarize_truth)
from link import protocol as P
from link.transport import BytePipeTransport, SerialTransport


def make_hub(args, key, seq0=1, log_dir="results"):
    world = build_world(args, hidden=True)
    return Homebase(world, args.drones, hub_config(args), key=key,
                    allies=load_allies(args.allies, args), log_dir=log_dir, seq0=seq0,
                    verbose=not getattr(args, "quiet", False), n_rovers=n_rovers(args),
                    rover_speed=getattr(args, "rover_speed", 2.5),
                    expected=getattr(args, "people", None) if getattr(args, "sim", False) else None)


def run_sim(args, key):
    m = simulate(args, key, log_dir="results", verbose=True, gif=args.gif)
    print("  casualty list -> results/casualties.json")
    return m


def simulate(args, key, log_dir=None, verbose=False, gif=False):
    """One simulated mission. Returns metrics scored against ground truth."""
    truth, grid, people, drones, gw = build_sim(args, key)
    hub = make_hub(args, key, log_dir=log_dir)
    hub.verbose = verbose and not getattr(args, "quiet", False)
    hq = make_hq(args) if n_rovers(args) or getattr(args, "starlink", False) else None
    pipe = BytePipeTransport()
    dt, t, next_tick, next_status, next_frame = 0.1, 0.0, 0.0, 0.0, 0.0
    frames = []
    say = print if verbose else (lambda *a, **k: None)
    say(f"=== simulated mission: {args.drones} drones, {len(people)} hidden people, "
        f"loss {args.loss:.0%}{', jam ' + args.jam if args.jam else ''}"
        f"{', MILITARY' if args.military else ''}{', signed' if key else ''} ===")
    t_found, matched, done = None, {}, False
    while t < args.time:
        up = {d.id: d.step(t, dt) for d in drones}
        pipe.rx += gw.uplink(t, up)                   # what the S3 would write to USB
        for rssi, raw in pipe.recv():
            hub.on_raw(raw, rssi, t)
        if t >= next_tick:
            for pkt in hub.tick(t):
                pipe.send(pkt)
            next_tick += 0.2                           # homebase loop at 5 Hz
        gw.downlink(t, bytes(pipe.tx))                # what the S3 would read from USB
        pipe.tx.clear()
        if hq is not None:
            hq.tick(t, hub)
        if hub.complete:
            for d in drones:
                if getattr(d, "kind", "air") == "air":
                    d.launch_at = 1e12                # mission over: batteries stay on the pad
        if t >= next_status:
            say(hub.status_line(t))
            next_status += 15.0
        if gif and t >= next_frame:
            frames.append(_frame(hub, drones, people))
            next_frame += 1.0
        if t_found is None and all(p.first_detected is not None for p in people):
            t_found = t
        matched = match_people(people, hub.tracks, 1.5 * truth.cell_m) if hub.tracks else {}
        done = len(matched) == len(people) and all(
            tr.confirmed and (tr.assessed or tr.checked) for tr, _ in matched.values())
        if done and not getattr(args, "keep_going", False):
            say(hub.status_line(t))
            say(f"  every person is found, confirmed and checked for vitals at t={t:.1f}s")
            break
        t += dt
    hub.close()
    if verbose:
        summarize_truth(people, hub, drones, gw, t)
    if gif:
        _save_gif(hub, frames, truth)
    # delivery: detections made >= 5 s before the end (younger ones may still be in flight)
    old = [(d.id, i) for d in drones for i, tm in d.made if tm <= t - 5.0]
    got = sum(i in hub.drones[did].det_seen for did, i in old)
    return dict(done=done, t_done=t if done else None, t_found=t_found,
                vitals=sum(tr.assessed for tr, _ in matched.values()) / len(people),
                false_contacts=len(hub.tracks) - len(matched),
                delivered=got / max(1, len(old)),
                uplink_loss=gw.stats["up_lost"] / max(1, gw.stats["up_sent"]),
                emissions=sum(d.stats["tx"] for d in drones), deaths=sum(d.dead for d in drones),
                rtb=hub.stats["rtb"])


def _frame(hub, drones, people):
    m = hub.mass / max(hub.mass.sum(), 1e-12)
    return (m.copy(), [(d.true[:2].copy(), d.est.copy(), d.state) for d in drones],
            [(t.x, t.y, t.confirmed) for t in hub.tracks], [(p.x, p.y) for p in people],
            [hub.drones[d.id].task for d in drones])


def _save_gif(hub, frames, world):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.animation import FuncAnimation, PillowWriter
    g = hub.grid
    fig, ax = plt.subplots(figsize=(5.5, 5.5))
    colors = ["#e4572e", "#29bf12", "#ffc914", "#76b041", "#17bebb"]

    def to_ij(x, y):
        return g.home[1] + x / g.cell_m, g.home[0] - y / g.cell_m

    def draw(k):
        ax.clear()
        m, ds, tracks, people, tasks = frames[k]
        b = m.copy()
        b[world.obstacles] = np.nan
        ax.imshow(b, origin="upper", cmap="viridis")
        for (px, py) in people:
            j, i = to_ij(px, py)
            ax.scatter(j, i, marker="*", s=180, c="white", edgecolors="k", zorder=3)
        for (tx, ty, conf) in tracks:
            j, i = to_ij(tx, ty)
            ax.scatter(j, i, marker="s", s=90, facecolors="none",
                       edgecolors="red" if conf else "orange", linewidths=2, zorder=4)
        for n, (tru, est, st) in enumerate(ds):
            j, i = to_ij(*tru)
            ax.scatter(j, i, s=70, c=colors[n % 5], edgecolors="k", zorder=5)
            ax.annotate(f"D{n + 1} {tasks[n]}", (j, i), color="white", fontsize=7,
                        xytext=(4, 4), textcoords="offset points")
        hj, hi = g.home[1], g.home[0]
        ax.scatter(hj, hi, marker="^", s=120, c="cyan", edgecolors="k", zorder=6)
        ax.set_title(f"t={k}s  contacts {len(tracks)}  (red = confirmed)", fontsize=9)
        ax.set_xticks([]); ax.set_yticks([])

    anim = FuncAnimation(fig, draw, frames=len(frames), interval=100)
    anim.save("fleet_search.gif", writer=PillowWriter(fps=10))
    print(f"  saved fleet_search.gif ({len(frames)} frames)")


def run_hw(args, key):
    lease = SeqLease("results/.home_seq")
    hub = make_hub(args, key, seq0=lease.value)
    link = SerialTransport(args.port, args.baud)
    cv = None
    if args.cv_port:
        cv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        cv.bind(("127.0.0.1", args.cv_port))
        cv.setblocking(False)
    dash = None
    if args.web:
        from fleet.web import Dashboard, parse_origin, snapshot
        dash, origin = Dashboard(args.web_port).start(), parse_origin(args.origin)
        print(f"  dashboard:  http://localhost:{args.web_port}")
    next_pub = 0.0
    print(f"=== homebase on {args.port}: {args.drones} drones"
          f"{', MILITARY' if args.military else ''}{', signed' if key else ''}"
          f"{f', CV on udp {args.cv_port}' if cv else ''}. Ctrl-C to stop. ===")
    t0 = time.monotonic()
    next_tick = next_status = 0.0
    try:
        while True:
            now = time.monotonic() - t0
            for rssi, raw in link.recv():
                hub.on_raw(raw, rssi, now)
            while cv:
                try:
                    data, _ = cv.recvfrom(2048)
                except BlockingIOError:
                    break
                try:
                    hub.on_local(json.loads(data.decode()), now)
                except (ValueError, KeyError) as e:
                    print(f"  bad CV message: {e}")
            if now >= next_tick:
                for pkt in hub.tick(now):
                    link.send(pkt)
                lease.check(hub.seq)
                next_tick = now + 0.2
            if now >= next_status:
                print(hub.status_line(now))
                next_status = now + 5.0
            if dash:
                for c in dash.take_commands():
                    if c.get("cmd") == "recall":
                        hub.recall(now)               # the only browser command that touches real drones
            if dash and now >= next_pub:
                dash.publish(snapshot(hub, now, 1, origin, mode="live"))
                next_pub = now + 0.25
            time.sleep(0.01)
    except KeyboardInterrupt:
        pass
    finally:
        hub.close()
        link.close()
        print("\ncasualty list (highest priority first):")
        for tr in hub.casualties():
            d = tr.as_dict()
            print(f"  #{d['id']} {d['status']:<8} {'CONFIRMED' if d['confirmed'] else 'unconfirmed'} "
                  f"at ({d['x']}, {d['y']}) m  hr {d['hr']} br {d['br']}  tag {d['tag_id']}  via {d['sensors']}")
        print("saved results/casualties.json and results/mission_log.jsonl")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--sim", action="store_true", help="simulate drones + gateway in-process")
    mode.add_argument("--port", help="serial port of the ESP32-S3 gateway")
    mode.add_argument("--cf-sim", action="store_true",
                      help="simulated Crazyflies in a 2 m room, flown through the real bridge (+ dashboard)")
    ap.add_argument("--baud", type=int, default=921600)
    ap.add_argument("--cv-port", type=int, default=5515, help="UDP port for local CV/pose JSON (0 = off)")
    ap.add_argument("--time", type=float, default=900.0, help="sim: stop after this many seconds")
    ap.add_argument("--keep-going", action="store_true", help="sim: don't stop when everyone is found")
    ap.add_argument("--gif", action="store_true", help="sim: save fleet_search.gif")
    ap.add_argument("--quiet", action="store_true", help="hide the event log")
    ap.add_argument("--web", action="store_true", help="live dashboard at http://localhost:WEB_PORT")
    ap.add_argument("--web-port", type=int, default=8080)
    ap.add_argument("--speed-up", type=float, default=4.0, help="sim --web: start at this many x real time")
    add_mission_args(ap)
    add_sim_args(ap)
    ap.add_argument("--civilian", action="store_true", help="pr scenario: turn military mode off")
    args = ap.parse_args()
    from fleet.scenario import apply_scenario_defaults
    if args.cf_sim:
        from fleet.cfsim import apply_cf_sim_defaults
        apply_cf_sim_defaults(args, sys.argv[1:])
    apply_scenario_defaults(args, sys.argv[1:])
    key = P.load_key(args.key)
    if args.military and not key:
        print("note: --military without --key: packets are NOT signed. Add --key to require signatures.")
    if args.cf_sim:
        from fleet.cfsim import run_cf_sim
        r = run_cf_sim(args, key)
        print(f"\nfound {r['found']} of {r['people']} people"
              + (f" (all by {r['t_all_found']:.0f} s)" if r["t_all_found"] else ""))
    elif args.sim and args.web:
        from fleet.live import run_live_sim
        run_live_sim(args, key)
    elif args.sim:
        run_sim(args, key)
    else:
        run_hw(args, key)


if __name__ == "__main__":
    sys.exit(main())
