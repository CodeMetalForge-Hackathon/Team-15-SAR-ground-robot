"""Planner + simulated Crazyflies through the real bridge (fleet/cfsim.py). About 50 s, real time.

Run from team15_starter/:  python tests/test_cfsim.py
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from fleet.cfsim import apply_cf_sim_defaults, run_cf_sim  # noqa: E402
from fleet.scenario import add_mission_args, add_sim_args, apply_scenario_defaults  # noqa: E402


def args_for(*extra):
    ap = argparse.ArgumentParser()
    add_mission_args(ap)
    add_sim_args(ap)
    ap.add_argument("--web-port", type=int, default=8080)
    ap.add_argument("--time", type=float, default=600.0)
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(list(extra))
    apply_cf_sim_defaults(a, list(extra))
    apply_scenario_defaults(a, list(extra))
    a.quiet = True
    return a


def test_planner_flies_crazyflies_and_finds_people():
    lines = []
    r = run_cf_sim(args_for("--seed", "3"), None, web=False, stop_after=45, out=lines.append)
    assert r["refused"] == [], r["refused"]                       # the bridge accepted every command
    assert r["found"] >= 1, (r, lines[-5:])                        # BLE found someone with a phone
    assert any("search" in l for l in lines), lines[:5]
    assert all("no pose" not in m and "quiet" not in m for m in r["bridge_log"]), r["bridge_log"]
    print(f"  found {r['found']}/{r['people']} people, all by {r['t_all_found']}")


if __name__ == "__main__":
    test_planner_flies_crazyflies_and_finds_people()
    print("CF SIM TEST PASSED")
