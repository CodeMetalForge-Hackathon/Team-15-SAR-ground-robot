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
from .scenario import build_sim, build_world, hub_config, load_allies, match_people
from .web import Dashboard, parse_origin, snapshot


def _new_mission(args, key):
    truth, grid, people, drones, gw = build_sim(args, key)
    hub = Homebase(build_world(args, hidden=True), args.drones, hub_config(args), key=key,
                   allies=load_allies(args.allies, args), log_dir="results",
                   verbose=not getattr(args, "quiet", False))
    return truth, people, drones, gw, hub


def now_status(run):
    from .terrain import terrain_status
    from .web import parse_origin
    try:
        return terrain_status(parse_origin(run.origin), run.n, run.cell_m, default=run.cover)
    except Exception:                                  # noqa: BLE001
        return "none"


def run_live_sim(args, key):
    dash = Dashboard(args.web_port).start()
    origin = parse_origin(args.origin)
    print(f"\n  dashboard:  http://localhost:{args.web_port}   (Ctrl-C to stop)\n")
    mission_id, speed, paused, setup_id = 0, float(args.speed_up), False, 0
    run = argparse.Namespace(**vars(args))
    try:
        while True:
            mission_id += 1
            truth, people, drones, gw, hub = _new_mission(run, key)
            pipe = BytePipeTransport()
            dt, t, next_tick = 0.1, 0.0, 0.0
            target = 0.0                     # sim time we should have reached (keeps fractions of a step)
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
                    elif cmd == "setup":                  # operator's own mission from the setup panel
                        lat, lon = (float(v) for v in c["origin"])
                        run.origin = f"{lat:.6f},{lon:.6f}"
                        origin = (lat, lon)
                        run.n = int(c.get("n", 24))
                        mix = c.get("drones") or {}
                        if mix:                            # operator's fleet: sweepers / thermal / finders
                            parts = (["ble"] * int(mix.get("sweepers", 0)) + ["thermal"] * int(mix.get("thermal", 0))
                                     + ["cv"] * int(mix.get("finders", 0)))
                            if parts:
                                run.loadout, run.drones = ";".join(parts), len(parts)
                        run.cell_m = float(c.get("cell", 25.0))
                        victims = [v for v in (c.get("victims") or []) if "x" in v and "y" in v]
                        run.people = len(victims) if victims else max(1, min(8, int(c.get("count", 1))))
                        civilian = bool(c.get("civilian", False))
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
                              f"terrain {'from browser' if c.get('osm') else 'to fetch'}")
                    elif cmd == "restart":
                        restart = True
                        run.seed += 1
                # real terrain finished downloading in the background: restart this mission on it
                sc = getattr(hub.world, "scenario", None)
                if sc is not None and "loading" in sc.source and t < 45 and now_status(run) == "ready":
                    print("  terrain: real map ready, restarting the mission on it")
                    run._scenario_cache = None
                    restart = True
                    continue
                now = time.monotonic()
                budget = 0.0 if paused or t >= run.time else (now - wall) * speed
                wall = now
                # Step only whole 0.1 s steps that are actually due. (Before, every 20 ms loop
                # always ran at least one 0.1 s step, so "x1" really ran at ~4-5x.)
                target += budget
                steps = 0
                while t + dt <= target + 1e-9 and steps < 300:   # catch up, but never freeze the page
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
                                tr.confirmed and (tr.observation or tr.assessed or tr.checked) for tr, _ in matched.values()):
                            done_at = t
                            print(f"  every person found, seen and checked at {t:.1f}s")
                    t += dt
                    steps += 1
                if steps >= 300:
                    target = t                                # can't keep up: drop the backlog, don't spiral
                if now >= next_pub:
                    dash.publish(snapshot(hub, t, mission_id, origin, mode="sim", paused=paused or t >= run.time,
                                          speed=speed, people=people, sim_drones=drones, gw=gw, done_at=done_at))
                    next_pub = now + 0.25
                time.sleep(0.02)
            hub.close()
    except KeyboardInterrupt:
        print("\nstopped.")
    finally:
        dash.stop()


