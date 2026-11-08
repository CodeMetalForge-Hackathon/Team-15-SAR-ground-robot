"""fleet/live.py — runs the simulated mission in real time for the web dashboard.

Same homebase, same simulated drones and radio as `homebase.py --sim`, but
paced to the wall clock (x1, x4, x10) so you can watch it, with controls in
the browser: pause, speed, jam the radio, start a new mission.
"""
from __future__ import annotations

import argparse
import time

from link import protocol as P
from link.transport import BytePipeTransport
from .hub import Homebase
from .scenario import build_sim, build_world, hub_config, load_allies, make_hq, match_people, n_rovers
from .web import Dashboard, parse_origin, snapshot


def _new_mission(args, key):
    truth, grid, people, drones, gw = build_sim(args, key)
    hub = Homebase(build_world(args, hidden=True), args.drones, hub_config(args), key=key,
                   allies=load_allies(args.allies, args), log_dir="results",
                   verbose=not getattr(args, "quiet", False), n_rovers=n_rovers(args),
                   rover_speed=args.rover_speed, expected=getattr(args, "people", None))
    return truth, people, drones, gw, hub, make_hq(args)


def run_live_sim(args, key):
    dash = Dashboard(args.web_port).start()
    origin = parse_origin(args.origin)
    print(f"\n  dashboard:  http://localhost:{args.web_port}   (Ctrl-C to stop)\n")
    mission_id, speed, paused, setup_id = 0, float(args.speed_up), False, 0
    run = argparse.Namespace(**vars(args))
    fleet_drones = args.drones or 3
    try:
        while True:
            mission_id += 1
            truth, people, drones, gw, hub, hq = _new_mission(run, key)
            pipe = BytePipeTransport()
            dt, t, next_tick = 0.1, 0.0, 0.0
            done_at, vitals_at, restart = None, None, False
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
                    elif cmd == "sky" and hq is not None:   # block the homebase's Starlink for a bit
                        secs = float(c.get("secs", 20))
                        hq.outage(t, secs)
                        if hasattr(gw, "starlink"):
                            gw.starlink.link.forced = (t, t + secs)
                    elif cmd == "recall":
                        hub.recall(t)
                        for d in drones:
                            d.launch_at = 1e12          # the mothership keeps them on the pad
                    elif cmd == "setup":                  # operator's own mission from the setup panel
                        lat, lon = (float(v) for v in c["origin"])
                        run.origin = f"{lat:.6f},{lon:.6f}"
                        origin = (lat, lon)
                        run.n = int(c.get("n", 24))
                        run.cell_m = float(c.get("cell", 25.0))
                        victims = [v for v in (c.get("victims") or []) if "x" in v and "y" in v]
                        run.people = len(victims) if victims else max(1, min(8, int(c.get("count", 1))))
                        civilian = bool(c.get("civilian", False))
                        fl = c.get("fleet", "both")
                        run.drones = 0 if fl == "rover" else fleet_drones
                        run.rovers = 0 if fl == "drones" else 1
                        run.military = not civilian
                        run.key = None if civilian else (run.key or "team15-pr-demo-key")
                        key = P.load_key(run.key)
                        setup_id += 1
                        run.setup = dict(id=setup_id, osm=c.get("osm"), lkp=c.get("lkp"),
                                         threats=c.get("threats"), civilian=civilian, victims=victims)
                        run.seed += 1
                        restart = True
                        print(f"  setup: {run.people} victim(s) {'placed' if victims else 'random'}, "
                              f"{'civilian' if civilian else 'military'}, area {run.n * run.cell_m:.0f} m at {run.origin}, "
                              f"terrain {'from browser' if c.get('osm') else 'to fetch'}, "
                              f"{run.drones} drone(s) + {run.rovers or 0} rover(s)")
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
                    if hq is not None:
                        hq.tick(t, hub)
                    if hub.complete:
                        for d in drones:
                            if d.kind == "air":
                                d.launch_at = 1e12      # mission over: batteries stay on the pad
                    if vitals_at is None and hub.tracks:
                        matched = match_people(people, hub.tracks, 1.5 * truth.cell_m)
                        if len(matched) == len(people) and all(tr.assessed for tr, _ in matched.values()):
                            vitals_at = t
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
                                          speed=speed, people=people, sim_drones=drones, gw=gw, done_at=done_at,
                                          vitals_at=vitals_at, hq=hq))
                    next_pub = now + 0.2
                time.sleep(0.02)
            hub.close()
    except KeyboardInterrupt:
        print("\nstopped.")
    finally:
        dash.stop()


