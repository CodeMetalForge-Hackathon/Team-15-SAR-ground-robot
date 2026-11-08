"""fleet/live.py — runs the simulated mission in real time for the web dashboard.

Same homebase, same simulated drones and radio as `homebase.py --sim`, but
paced to the wall clock (x1, x4, x10) so you can watch it, with controls in
the browser: pause, speed, jam the radio, start a new mission.
"""
from __future__ import annotations

import argparse
import time

from link.transport import BytePipeTransport
from .hub import Homebase
from .scenario import build_sim, build_world, hub_config, load_allies, match_people
from .web import Dashboard, parse_origin, snapshot


def _new_mission(args, key):
    truth, grid, people, drones, gw = build_sim(args, key)
    hub = Homebase(build_world(args, hidden=True), args.drones, hub_config(args), key=key,
                   allies=load_allies(args.allies, args), log_dir="results",
                   verbose=not getattr(args, "quiet", False))
    return truth, people, drones, gw, hub


def run_live_sim(args, key):
    dash = Dashboard(args.web_port).start()
    origin = parse_origin(args.origin)
    print(f"\n  dashboard:  http://localhost:{args.web_port}   (Ctrl-C to stop)\n")
    mission_id, speed, paused = 0, float(args.speed_up), False
    run = argparse.Namespace(**vars(args))
    try:
        while True:
            mission_id += 1
            truth, people, drones, gw, hub = _new_mission(run, key)
            pipe = BytePipeTransport()
            dt, t, next_tick = 0.1, 0.0, 0.0
            done_at, restart = None, False
            wall = time.monotonic()
            next_pub = 0.0
            print(f"=== mission {mission_id} (seed {run.seed}): {len(people)} hidden people ===")
            while not restart:
                for c in dash.take_commands():
                    cmd = c.get("cmd")
                    if cmd == "pause":
                        paused = True
                    elif cmd == "play":
                        paused = False
                    elif cmd == "speed":
                        speed = float(min(20, max(0.25, c.get("value", 1))))
                    elif cmd == "jam":
                        secs = float(c.get("secs", 30))
                        gw.jam = (t, t + secs)
                        hub._event(t, "jam", secs=int(secs))
                    elif cmd == "recall":
                        hub.recall(t)
                        for d in drones:
                            d.launch_at = 1e12          # the mothership keeps them on the pad
                    elif cmd == "restart":
                        restart = True
                        run.seed += 1
                now = time.monotonic()
                budget = 0.0 if paused or t >= run.time else (now - wall) * speed
                wall = now
                goal, steps = t + budget, 0
                while t < goal and steps < 300:               # catch up, but never freeze the page
                    up = {d.id: d.step(t, dt) for d in drones}
                    pipe.rx += gw.uplink(t, up)
                    for rssi, raw in pipe.recv():
                        hub.on_raw(raw, rssi, t)
                    if t >= next_tick:
                        for pkt in hub.tick(t):
                            pipe.send(pkt)
                        next_tick += 0.2
                    gw.downlink(t, bytes(pipe.tx))
                    pipe.tx.clear()
                    if done_at is None and hub.tracks:
                        matched = match_people(people, hub.tracks, 1.5 * truth.cell_m)
                        if len(matched) == len(people) and all(
                                tr.confirmed and (tr.assessed or tr.checked) for tr, _ in matched.values()):
                            done_at = t
                            print(f"  every person found and checked at {t:.1f}s")
                    t += dt
                    steps += 1
                if now >= next_pub:
                    dash.publish(snapshot(hub, t, mission_id, origin, mode="sim", paused=paused or t >= run.time,
                                          speed=speed, people=people, sim_drones=drones, gw=gw, done_at=done_at))
                    next_pub = now + 0.2
                time.sleep(0.02)
            hub.close()
    except KeyboardInterrupt:
        print("\nstopped.")
    finally:
        dash.stop()


