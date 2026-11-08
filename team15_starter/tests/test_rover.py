"""tests/test_rover.py — ground rover + Starlink. Run from team15_starter/:

    python tests/test_rover.py        (about 30 s)
"""
from __future__ import annotations

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import numpy as np  # noqa: E402

from fleet.scenario import add_mission_args, add_sim_args  # noqa: E402
from homebase import simulate  # noqa: E402


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)
    print("  ok  ", msg)


def test_ground():
    print("ground view")
    from fleet.ground import GroundView
    from fleet.planner import GridWorld
    from fleet.terrain import C

    class Sc:                               # a tiny real-terrain map: road, pond, forest
        terrain = np.full((6, 6), C["forest"], dtype=np.int8)
        terrain[5, :] = C["road"]
        terrain[2:4, 2:4] = C["water"]
        vis = np.ones((6, 6))
        threat = np.zeros((6, 6))
        nofly = np.zeros((6, 6), dtype=bool)
        prior = np.ones((6, 6)) / 36
    w = GridWorld(n=6, cell_m=10.0, prior="uniform", walls=False)
    w.scenario = Sc()
    g = GroundView(w, speed_mps=2.0)
    check(not g.free((2, 2)) and g.free((0, 0)), "rover can't drive into the pond")
    check(g.cost[5, 0] < g.cost[0, 0], "road is faster than forest")
    p = g.path((5, 0), (0, 5))
    check(p is not None and all(g.free(c) for c in p), "route goes around the pond")
    check(g.path_time((5, 0), (5, 5)) < g.path_time((0, 0), (0, 5)), "the road route takes less time")


def _args(**kw):
    ap = argparse.ArgumentParser()
    add_mission_args(ap)
    add_sim_args(ap)
    a = ap.parse_args([])
    a.time, a.quiet, a.keep_going, a.loss = 600.0, True, False, 0.1
    for k, v in kw.items():
        setattr(a, k, v)
    return a


def test_mission_with_rover():
    print("mission: 3 drones + 1 rover over Starlink")
    r = simulate(_args(rovers=1), None)
    check(r["done"], f"everyone found, confirmed and checked with a rover along ({r['t_done']:.0f} s)")
    check(r["deaths"] == 0, "no vehicle ran out of battery")


def test_rover_reads_vitals_when_drones_cant():
    print("BLE-only drones + rover: the rover reads the vitals")
    from fleet.hub import Homebase
    from fleet.scenario import build_sim, build_world, hub_config, make_hq
    from link.transport import BytePipeTransport
    a = _args(rovers=1, loadout="thermal,ble", people=2, seed=2, no_walls=True)
    truth, grid, people, vehicles, gw = build_sim(a, None)
    hub = Homebase(build_world(a, hidden=True), a.drones, hub_config(a), log_dir=None, verbose=False,
                   n_rovers=1, rover_speed=a.rover_speed)
    hq = make_hq(a)
    pipe, t, nt = BytePipeTransport(), 0.0, 0.0
    while t < 900 and not any("mmwave" in tr.sensors for tr in hub.tracks):   # only R1 has radar
        up = {d.id: d.step(t, 0.1) for d in vehicles}
        pipe.rx += gw.uplink(t, up)
        for rssi, raw in pipe.recv():
            hub.on_raw(raw, rssi, t)
        if t >= nt:
            for pkt in hub.tick(t):
                pipe.send(pkt)
            nt += 0.2
        gw.downlink(t, bytes(pipe.tx))
        pipe.tx.clear()
        hq.tick(t, hub)
        t += 0.1
    got = [tr for tr in hub.tracks if "mmwave" in tr.sensors and tr.assessed]
    check(got and 11 in got[0].drones, f"rover R1 drove to a contact and read its vitals ({t:.0f} s)")
    check(hq.stats["delivered"] >= 1, "HQ got the casualty report over Starlink")


def test_starlink_queue():
    print("Starlink uplink to HQ")
    from fleet.starlink import HQUplink

    class Tr:
        id, status, confirmed, assessed, hr, br, x, y, tag_id, ally = 1, "critical", True, True, 40, 5, 10.0, 20.0, 0, None

    class Hub:
        tracks, events = [Tr()], []

        def _event(self, t, ev, **kw):
            self.events.append((t, ev, kw))
    hub = Hub()
    up = HQUplink(np.random.default_rng(0))
    up.link.outages, up.link._next = [(0.0, 10.0)], 1e9         # sky blocked for the first 10 s
    for k in range(50):                                         # 0 .. 9.8 s
        up.tick(k * 0.2, hub)
    check(not up.hq, "nothing reaches HQ during the outage (report waits in the queue)")
    for k in range(50, 80):
        up.tick(k * 0.2, hub)
    check(1 in up.hq and up.hq[1]["status"] == "critical", "report delivered once the sky is back")
    check(any(ev == "starlink_up" for _, ev, _ in hub.events), "the outage and recovery are logged")


if __name__ == "__main__":
    test_ground()
    test_starlink_queue()
    test_rover_reads_vitals_when_drones_cant()
    test_mission_with_rover()
    print("ALL ROVER TESTS PASSED")
