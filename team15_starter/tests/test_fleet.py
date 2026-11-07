"""tests/test_fleet.py — homebase logic checks. Run from team15_starter/:

    python tests/test_fleet.py        (about 15 s)
"""
from __future__ import annotations

import argparse
import filecmp
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import numpy as np  # noqa: E402

from fleet.hub import Homebase, HubConfig  # noqa: E402
from fleet.planner import GridWorld, apply_look, astar, dist_field  # noqa: E402
from fleet.scenario import add_mission_args, add_sim_args  # noqa: E402
from homebase import simulate  # noqa: E402
from link import protocol as P  # noqa: E402


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)
    print("  ok  ", msg)


def test_planner():
    print("planner")
    w = GridWorld(seed=0, prior="uniform", walls=True)
    a, b = w.belief.copy(), w.belief.copy()
    apply_look(w, a, (12, 12), ["thermal"], sigma_cells=0.0)
    apply_look(w, b, (12, 12), ["thermal"], sigma_cells=2.0)
    check((a < w.belief).sum() < (b < w.belief).sum(),
          "drifting drone spreads its look over more cells (doesn't over-trust its position)")
    check(a[12, 12] < b[12, 12], "...and trusts each cell less")
    path = astar(w, (23, 0), (0, 23))
    check(path is not None and all(w.free(c) for c in path), "A* finds a path around the walls")
    f = dist_field(w, (23, 0))
    check(f[(0, 23)] == len(path), "return-home cost map agrees with A*")


def test_hub_inputs():
    print("homebase inputs")
    w = GridWorld(seed=0, prior="multi", n_people=1)
    w.people = []
    key = b"k"
    hub = Homebase(w, 2, HubConfig(military=True), key=key, log_dir=None, verbose=False)
    tel = P.Telemetry(0, 0, 10, 0, 0, 90, 1, P.sensor_bit("thermal"), 0)
    hub.on_raw(P.encode(tel, 1, 0, 100, key=key), -50, 0.0)
    check(hub.drones[1].task == "search", "signed telemetry accepted, drone 1 starts searching")
    hub.on_raw(P.encode(tel, 1, 0, 100, key=key), -50, 0.1)
    check(hub.stats["rx_replay"] == 1, "same packet again = replay, rejected")
    hub.on_raw(P.encode(tel, 2, 0, 5), -50, 0.2)
    check(hub.drones[2].task == "idle" and hub.stats["rx_bad"] == 1, "unsigned packet rejected in military mode")
    hub.on_raw(P.encode(tel, 1, 0, 101, key=b"enemy"), -50, 0.3)
    check(hub.stats["rx_bad"] == 2, "packet signed with the wrong key rejected")
    out = hub.tick(0.5)
    check(len(out) == 1 and P.decode(out[0], key=key).dst == 1, "tick sends drone 1 a signed waypoint")

    hub.on_local({"type": "det", "drone": 1, "sensor": "cv", "conf": 0.8, "status": "injured",
                  "x": 40.0, "y": 60.0}, 1.0)
    check(len(hub.tracks) == 1 and hub.tracks[0].status == "injured", "CV JSON on UDP becomes a contact")
    det = P.Detection(41.0, 61.0, P.SENSOR_IDS["mmwave"], 245, 0, 150, 33, 10, 1, 0)
    hub.on_raw(P.encode(det, 1, 0, 102, key=key), -50, 2.0)
    hub.on_raw(P.encode(det, 1, 0, 103, key=key), -50, 2.5)     # retransmit of det_id 1
    tr = hub.tracks[0]
    check(len(hub.tracks) == 1 and tr.hits == 2, "radar hit merges into the same contact; retransmit ignored")
    check(tr.status == "critical" and tr.assessed, "vitals 150/33 -> critical (placeholder triage)")
    check(hub.drones[1].det_ack == 1, "detection acked back to the drone (store-and-forward)")
    hub.on_local({"type": "pose", "drone": 2, "x": 20.0, "y": 0.0, "sigma": 0.3}, 3.0)
    check(hub.drones[2].cell == hub.grid.to_cell(20.0, 0.0), "overhead-camera pose JSON moves drone 2")


def test_mission():
    print("full simulated mission (real bytes, 3 drones, 20% loss)")
    ap = argparse.ArgumentParser()
    add_mission_args(ap)
    add_sim_args(ap)
    args = ap.parse_args([])
    args.loss, args.time, args.quiet, args.keep_going = 0.2, 600.0, True, False
    r = simulate(args, None)
    check(r["done"], f"all people found, confirmed and checked in {r['t_done']:.0f} s")
    check(r["delivered"] == 1.0, "every detection reached the homebase despite packet loss")
    check(r["deaths"] == 0, "no drone ran out of battery")


def test_firmware_headers():
    print("firmware")
    src = os.path.join(ROOT, "firmware", "t15_protocol.h")
    for sketch in ("drone_node", "gateway"):
        copy = os.path.join(ROOT, "firmware", sketch, "t15_protocol.h")
        check(filecmp.cmp(src, copy, shallow=False), f"{sketch}/t15_protocol.h is identical to firmware/t15_protocol.h")


if __name__ == "__main__":
    test_planner()
    test_hub_inputs()
    test_firmware_headers()
    test_mission()
    print("ALL FLEET TESTS PASSED")
