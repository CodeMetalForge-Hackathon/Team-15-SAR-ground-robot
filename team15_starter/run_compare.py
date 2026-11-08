"""run_compare.py — multi-person search with an optional GPS-DENIED mode (DARPA FLA)."""
from __future__ import annotations
import argparse
import statistics
import numpy as np

from sar.sar_core import World
from sar.planners import Lawnmower, Greedy, MCTS
from sar.waypoint import Grid2DSink
from sar.sensors import SENSORS, apply


def _est(true_pos, offset, n):
    i = int(round(true_pos[0] + offset[0]))
    j = int(round(true_pos[1] + offset[1]))
    return (min(max(i, 0), n - 1), min(max(j, 0), n - 1))


def run_episode(seed, planner_name, budget=160, exposure=0.0, record=False,
                prior="ring", sensor="thermal", n_people=1,
                drift=0.0, use_anchors=True):
    world = World(seed=seed, prior=prior, n_people=n_people)
    apply(world, sensor)
    start = (world.n - 1, 0)
    belief = world.belief.copy()
    if planner_name == "lawnmower":
        planner = Lawnmower(world)
    elif planner_name == "greedy":
        planner = Greedy()
    else:
        planner = MCTS(world, exposure=exposure)

    rng = np.random.default_rng(seed + 9991)
    true_pos = start
    offset = np.zeros(2)
    anchors = [start]                 # origin = AprilTag-style fix
    drop_every, anchor_range, pull = 10, 1, 0.35

    remaining = set(range(len(world.people)))
    total = len(world.people)
    steps_all, collected = None, 0.0
    frames = [] if record else None

    for step in range(budget):
        est_pos = _est(true_pos, offset, world.n)
        remaining -= world.detect(true_pos, remaining)
        if not remaining:
            steps_all = step
            break
        collected += world.pod * world.footprint_mass(belief, est_pos)
        world.update_no_detection(belief, est_pos)
        if record:
            frames.append((true_pos, est_pos, belief.copy(), set(range(total)) - remaining))
        next_est = planner.next_move(world, belief, est_pos)
        d = (next_est[0] - est_pos[0], next_est[1] - est_pos[1])
        cand = (true_pos[0] + d[0], true_pos[1] + d[1])
        if world.free(cand):
            true_pos = cand
        if drift > 0:
            offset = offset + rng.normal(0, drift, 2)
            if use_anchors:
                if step % drop_every == 0:
                    anchors.append(true_pos)
                near = any(max(abs(true_pos[0] - a[0]), abs(true_pos[1] - a[1])) <= anchor_range
                           for a in anchors)
                if near:
                    offset *= (1 - pull)

    return {"found": total - len(remaining), "total": total,
            "all_found": not remaining,
            "steps_all": steps_all if steps_all is not None else budget,
            "drift_end": float(np.hypot(*offset)),
            "collected": collected, "world": world, "frames": frames}


def summarise(name, results):
    total = results[0]["total"]
    frac = statistics.mean([r["found"] / r["total"] for r in results])
    allrate = 100 * sum(r["all_found"] for r in results) / len(results)
    done = [r["steps_all"] for r in results if r["all_found"]]
    steps = statistics.median(done) if done else float("nan")
    drift = statistics.mean([r["drift_end"] for r in results])
    print(f"{name:>10} | found {frac*total:4.2f}/{total} | all-found {allrate:5.1f}% "
          f"| median steps-to-all {steps:6.1f} | end-drift {drift:4.1f} cells")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=40)
    ap.add_argument("--people", type=int, default=3)
    ap.add_argument("--gif", action="store_true")
    ap.add_argument("--military", action="store_true")
    ap.add_argument("--gps-denied", dest="gps_denied", action="store_true")
    ap.add_argument("--no-anchors", dest="no_anchors", action="store_true")
    ap.add_argument("--prior", choices=["ring", "bimodal", "multi"], default="multi")
    ap.add_argument("--sensor", choices=list(SENSORS), default="thermal")
    args = ap.parse_args()
    exposure = 0.02 if args.military else 0.0
    drift = 0.2 if args.gps_denied else 0.0
    use_anchors = not args.no_anchors
    gps = "GPS-DENIED (VIO drift" + (", +UWB anchors)" if use_anchors else ", NO anchors)") \
        if args.gps_denied else "perfect GPS"
    print(f"=== Team-15 search — {gps}, sensor={args.sensor} ===")
    print(f"    prior={args.prior}, people={args.people}, {args.trials} trials")
    for name in ("lawnmower", "greedy", "mcts"):
        results = [run_episode(s, name, exposure=exposure, prior=args.prior,
                               sensor=args.sensor, n_people=args.people,
                               drift=drift, use_anchors=use_anchors)
                   for s in range(args.trials)]
        summarise(name, results)
    if args.gif:
        save_gif(exposure, args.prior, args.sensor, args.people, drift, use_anchors)


def save_gif(exposure, prior, sensor, n_people, drift, use_anchors):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.animation import FuncAnimation, PillowWriter
    r = run_episode(3, "mcts", exposure=exposure, record=True, prior=prior,
                    sensor=sensor, n_people=n_people, drift=drift, use_anchors=use_anchors)
    world, frames = r["world"], r["frames"]
    fig, ax = plt.subplots(figsize=(5, 5))

    def draw(k):
        ax.clear()
        true_pos, est_pos, belief, found = frames[k]
        b = belief.copy(); b[world.obstacles] = np.nan
        ax.imshow(b, origin="upper")
        for idx, (pi, pj) in enumerate(world.people):
            c = "gray" if idx in found else "white"
            ax.scatter(pj, pi, marker="*", s=170, c=c, edgecolors="k")
        ax.scatter(true_pos[1], true_pos[0], marker="o", s=70, c="red")
        if drift > 0:
            ax.scatter(est_pos[1], est_pos[0], marker="x", s=70, c="cyan")
        ax.set_title(f"MCTS + {sensor} - found {len(found)}/{len(world.people)} - step {k}")
        ax.set_xticks([]); ax.set_yticks([])

    anim = FuncAnimation(fig, draw, frames=len(frames), interval=120)
    anim.save("search.gif", writer=PillowWriter(fps=8))
    print(f"saved search.gif ({len(frames)} frames)")


if __name__ == "__main__":
    main()
