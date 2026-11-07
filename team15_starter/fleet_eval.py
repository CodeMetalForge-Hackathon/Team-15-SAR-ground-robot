"""fleet_eval.py — numbers for the pitch. Runs many simulated missions (real
protocol, real homebase code) and reports mean +/- 95% CI.

    python fleet_eval.py --study fleet    # 1 drone vs 3 independent vs 3 coordinated
    python fleet_eval.py --study radio    # clean vs 30% loss vs 30% loss + 60 s jam
    python fleet_eval.py --study emcon    # civilian radio vs military EMCON

Every drone carries the same sensors here (thermal + mmWave) so the comparison
is about coordination, not loadout. Results go to results/fleet_eval_<study>.csv.
"""
from __future__ import annotations

import argparse
import csv
import math
import os
import statistics
from multiprocessing import Pool

from fleet.scenario import add_mission_args, add_sim_args
from homebase import simulate

STUDIES = {
    "fleet": [("1 drone", dict(drones=1)),
              ("3 drones, no shared map", dict(drones=3, no_share=True, no_allocate=True)),
              ("3 drones, shared map", dict(drones=3, no_allocate=True)),
              ("3 drones, shared + claims", dict(drones=3))],
    "radio": [("clean radio", dict(loss=0.0)),
              ("30% loss", dict(loss=0.3)),
              ("30% loss + 60s jam", dict(loss=0.3, jam="40:100"))],
    "emcon": [("civilian radio", dict()),
              ("military EMCON + signed", dict(military=True, key="team15-secret"))],
}


def _one(job):
    base, over, seed = job
    ns = argparse.Namespace(**{**base, **over, "seed": seed})
    from link import protocol as P
    return simulate(ns, P.load_key(ns.key))


def ci(xs):
    if not xs:
        return float("nan"), float("nan")
    m = statistics.mean(xs)
    h = 1.96 * statistics.stdev(xs) / math.sqrt(len(xs)) if len(xs) > 1 else 0.0
    return m, h


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--study", choices=STUDIES, default="fleet")
    ap.add_argument("--seeds", type=int, default=20)
    ap.add_argument("--time", type=float, default=900.0)
    ap.add_argument("--workers", type=int, default=os.cpu_count() or 1)
    add_mission_args(ap)
    add_sim_args(ap)
    args = ap.parse_args()
    base = vars(args).copy()
    base.update(loadout="thermal,mmwave", keep_going=False, quiet=True)
    for k in ("study", "seeds", "workers"):
        base.pop(k)
    rows = []
    print(f"=== study '{args.study}': {args.seeds} seeds each, {args.people} hidden people, "
          f"{args.n}x{args.n} cells of {args.cell_m:g} m, time limit {args.time:g} s ===")
    print(f"{'config':<26} | {'all found (s)':>14} | {'all + vitals (s)':>16} | {'success':>7} | "
          f"{'vitals':>6} | {'delivered':>9} | {'emissions':>9} | deaths | extra contacts")
    with Pool(args.workers) as pool:
        for name, over in STUDIES[args.study]:
            res = pool.map(_one, [(base, over, s) for s in range(args.seeds)])
            # unfinished missions count at the time limit (a conservative, censored mean)
            tf = [r["t_found"] if r["t_found"] is not None else args.time for r in res]
            td = [r["t_done"] if r["t_done"] is not None else args.time for r in res]
            m1, h1 = ci(tf)
            m2, h2 = ci(td)
            succ = 100 * sum(r["done"] for r in res) / len(res)
            vit = 100 * statistics.mean(r["vitals"] for r in res)
            dl = 100 * statistics.mean(r["delivered"] for r in res)
            em = statistics.mean(r["emissions"] for r in res)
            deaths = sum(r["deaths"] for r in res)
            fc = statistics.mean(r["false_contacts"] for r in res)
            print(f"{name:<26} | {m1:6.1f} +/- {h1:4.1f} | {m2:8.1f} +/- {h2:4.1f} | {succ:6.0f}% | "
                  f"{vit:5.0f}% | {dl:8.1f}% | {em:9.0f} | {deaths} | {fc:.2f}")
            for s, r in enumerate(res):
                rows.append(dict(config=name, seed=s, **r))
    os.makedirs("results", exist_ok=True)
    path = f"results/fleet_eval_{args.study}.csv"
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"saved {path}")


if __name__ == "__main__":
    main()
