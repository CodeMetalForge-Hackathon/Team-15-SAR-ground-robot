"""fleet/scenario.py — command-line options and builders shared by homebase.py
(the Jetson program) and fleet_sim.py (the fake hardware)."""
from __future__ import annotations

import argparse
import os
import time

import numpy as np

from link import protocol as P
from .hub import HubConfig
from .planner import Grid, GridWorld
from .simdrones import SimDrone, SimGateway, make_people

DEFAULT_LOADOUT = "thermal,ble;thermal,mmwave;cv,mmwave"


def add_mission_args(ap: argparse.ArgumentParser):
    g = ap.add_argument_group("mission (must match between homebase and fleet_sim)")
    g.add_argument("--drones", type=int, default=3)
    g.add_argument("--n", type=int, default=24, help="grid is n x n cells")
    g.add_argument("--cell-m", type=float, default=20.0, help="cell size in metres (indoor: 0.5)")
    g.add_argument("--prior", default="multi", help="multi | ring | bimodal | uniform | path/to/heatmap.npy")
    g.add_argument("--seed", type=int, default=0)
    g.add_argument("--no-walls", action="store_true", help="open field: no known obstacles")
    g.add_argument("--military", action="store_true", help="EMCON radio, exposure cost, auth required")
    g.add_argument("--key", default=None, help="shared secret (file or text) = T15_KEY in firmware")
    g.add_argument("--allies", default=None, help="file of ally tag ids, one per line (hex ok)")
    g = ap.add_argument_group("drones")
    g.add_argument("--endurance", type=float, default=360.0, help="flight seconds per pack (Tiny Whoop ~240)")
    g.add_argument("--speed", type=float, default=8.0, help="cruise m/s (indoor whoop ~1)")
    g.add_argument("--base-alt", type=float, default=None, help="drone 1 altitude (default 30 m, or 1.0 m indoors)")
    g.add_argument("--alt-step", type=float, default=None, help="altitude gap between drones")
    g.add_argument("--sims", type=int, default=200, help="MCTS simulations per decision (lower on a slow Jetson)")
    g.add_argument("--no-allocate", action="store_true", help="ablation: don't claim teammates' next cells")
    g.add_argument("--no-share", action="store_true", help="ablation: drones don't share a map (no mesh)")
    return ap


def add_sim_args(ap: argparse.ArgumentParser):
    g = ap.add_argument_group("simulated hardware")
    g.add_argument("--people", type=int, default=3)
    g.add_argument("--loss", type=float, default=0.1, help="radio packet loss 0..1")
    g.add_argument("--jam", default=None, help="jam window in seconds, e.g. 60:120 (90%% loss)")
    g.add_argument("--drift", type=float, default=0.02, help="VIO drift (0 = perfect position)")
    g.add_argument("--loadout", default=DEFAULT_LOADOUT, help="sensors per drone, ';' between drones")
    g.add_argument("--charge", type=float, default=45.0, help="seconds the mothership needs per recharge")
    return ap


def build_world(args, hidden=False):
    w = GridWorld(n=args.n, cell_m=args.cell_m, prior=args.prior,
                  n_people=getattr(args, "people", 1), seed=args.seed, walls=not args.no_walls)
    if hidden:
        w.people = []            # the homebase never knows where anyone really is
    return w


def hub_config(args) -> HubConfig:
    indoor = args.cell_m < 3
    base = args.base_alt if args.base_alt is not None else (1.0 if indoor else 30.0)
    step = args.alt_step if args.alt_step is not None else (0.4 if indoor else 5.0)
    return HubConfig(endurance_s=args.endurance, speed_mps=args.speed, base_alt=base, alt_step=step,
                     confirm_alt=min(base, 1.0) if indoor else 1.5,
                     military=args.military, exposure=0.02 if args.military else 0.0,
                     n_sims=args.sims, allocate=not getattr(args, "no_allocate", False),
                     share_map=not getattr(args, "no_share", False))


def load_allies(path):
    if not path:
        return set()
    out = set()
    with open(path) as f:
        for line in f:
            line = line.split("#")[0].strip()
            if line:
                out.add(int(line, 16) if line.lower().startswith("0x") else int(line))
    return out


def build_sim(args, key):
    truth = build_world(args)
    grid = Grid(truth)
    rng = np.random.default_rng(args.seed + 1)
    people = make_people(truth, grid, rng)
    loadout = [s.split(",") for s in args.loadout.split(";")]
    drones = [SimDrone(i + 1, loadout[i % len(loadout)], truth, grid, people,
                       np.random.default_rng(args.seed + 10 + i), key=key,
                       speed=args.speed, endurance=args.endurance, drift=args.drift,
                       launch_at=2.0 * i, charge_s=args.charge, military=args.military,
                       mmwave_alt=2.0 if args.cell_m >= 3 else 1.2)
              for i in range(args.drones)]
    jam = tuple(float(v) for v in args.jam.split(":")) if args.jam else None
    gw = SimGateway(drones, np.random.default_rng(args.seed + 99), loss=args.loss, jam=jam)
    return truth, grid, people, drones, gw


class SeqLease:
    """Homebase packet counter that never goes backwards, even across restarts
    (drones reject old sequence numbers in --military/--key mode)."""

    def __init__(self, path, step=1000):
        self.path, self.step = path, step
        start = 1
        try:
            with open(path) as f:
                start = int(f.read().strip())
        except (OSError, ValueError):
            start = int(time.time()) % 1_000_000_000
        self.ceiling = start + step
        self._save()
        self.value = start

    def _save(self):
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        with open(self.path, "w") as f:
            f.write(str(self.ceiling))

    def check(self, value):
        if value >= self.ceiling:
            self.ceiling = value + self.step
            self._save()


def match_people(people, tracks, max_m):
    """One-to-one: each hidden person gets at most one contact and vice versa,
    closest pairs first. Two people merged into one contact = one of them missed."""
    pairs = sorted(((float(np.hypot(t.x - p.x, t.y - p.y)), k, j)
                    for k, p in enumerate(people) for j, t in enumerate(tracks)))
    used_p, used_t, out = set(), set(), {}
    for dist, k, j in pairs:
        if dist > max_m:
            break
        if k in used_p or j in used_t:
            continue
        used_p.add(k)
        used_t.add(j)
        out[k] = (tracks[j], dist)
    return out


def summarize_truth(people, hub, drones, gw, t_end):
    """Score the mission against ground truth (only the simulator can do this)."""
    lines = []
    cell_m = hub.world.cell_m
    found = 0
    matched = match_people(people, hub.tracks, 1.5 * cell_m)
    for k, p in enumerate(people):
        best, err = matched.get(k, (None, float("inf")))
        ok = best is not None
        found += ok
        det = f"{p.first_detected:6.1f}s" if p.first_detected is not None else "   never"
        if ok:
            vit = f"hr {best.hr:3d} br {best.br:2d}" if best.hr or best.br else "no vitals  "
            lines.append(f"  person {k + 1}: truth {p.status:<8} (hr {p.hr:3d} br {p.br:2d}) | first seen {det} | "
                         f"homebase says {best.status:<8} {vit} {'confirmed' if best.confirmed else 'UNCONFIRMED'} | "
                         f"error {err:4.1f} m")
        else:
            lines.append(f"  person {k + 1}: truth {p.status:<8} | first seen {det} | NOT FOUND")
    made = sum(d.stats["det_made"] for d in drones)
    got = sum(len(hd.det_seen) for hd in hub.drones.values())
    dead = sum(d.dead for d in drones)
    up_loss = gw.stats["up_lost"] / max(1, gw.stats["up_sent"])
    tx_drones = sum(d.stats["tx"] for d in drones)
    print("\n=== mission result (vs ground truth) ===")
    print("\n".join(lines))
    print(f"  found {found}/{len(people)} people in {t_end:.0f} s | false contacts "
          f"{max(0, len(hub.tracks) - found)}")
    print(f"  radio: {100 * up_loss:.0f}% of uplink packets lost | detections delivered "
          f"{got}/{made} (store-and-forward) | rejected bad/replay {hub.stats['rx_bad']}/{hub.stats['rx_replay']}")
    print(f"  emissions: drones {tx_drones} packets, homebase {hub.stats['tx']} packets")
    print(f"  returns-to-base {hub.stats['rtb']} | battery deaths {dead}")
    return found
