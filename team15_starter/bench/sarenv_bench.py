"""sarenv_bench.py — research-grade benchmark on SAREnv (Drones 2025).
Our MCTS as a SAREnv path generator, scored by SAREnv's OFFICIAL PathEvaluator
against SAREnv's OFFICIAL baselines on SAREnv's REAL lost-person heatmaps.
Metrics: likelihood (accumulated POD), time-discounted POD, victims found %.
    python bench/sarenv_bench.py --scenarios 1-6 --budget 30000
"""
from __future__ import annotations
import argparse, importlib.util, math, os, sys, time
import numpy as np

def _load(sarenv_dir, rel):
    p = os.path.join(sarenv_dir, rel)
    spec = importlib.util.spec_from_file_location(rel.replace("/", "_"), p)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m

FOV_DEG, ALT_M, OVERLAP, SPACING_M, TRANS_M, PIZZA_GAP_M = 45.0, 80.0, 0.0, 10.0, 50.0, 15.0
METERS_PER_BIN = 30
DISCOUNT = 0.999
NUM_LOST_PERSONS = 100


def mcts_path(center_x, center_y, num_drones, probability_map, bounds, max_radius,
              n_sims=16, horizon=8, c=1.4, gamma=0.995, **kw):
    from shapely.geometry import LineString
    H, W = probability_map.shape
    minx, miny, maxx, maxy = bounds
    dx = (maxx - minx) / W; dy = (maxy - miny) / H
    x0, y0 = minx + dx / 2, miny + dy / 2
    det_r = kw["altitude"] * math.tan(math.radians(kw["fov_deg"] / 2))
    rc = max(1, int(math.ceil(det_r / dx)))
    fp = [(a, b) for a in range(-rc, rc + 1) for b in range(-rc, rc + 1)
          if math.hypot(a * dy, b * dx) <= det_r]
    step = rc
    moves = [(di * step, dj * step) for di in (-1, 0, 1) for dj in (-1, 0, 1) if (di, dj) != (0, 0)]
    rng = np.random.default_rng(0)
    rem = probability_map.astype(float).copy()
    r2 = max_radius ** 2

    def inside(r, c_):
        if not (0 <= r < H and 0 <= c_ < W): return False
        wx, wy = x0 + c_ * dx, y0 + r * dy
        return (wx - center_x) ** 2 + (wy - center_y) ** 2 < r2

    def sweep(m, r, c_):
        s = 0.0
        for a, b in fp:
            rr, cc = r + a, c_ + b
            if 0 <= rr < H and 0 <= cc < W:
                s += m[rr, cc]; m[rr, cc] = 0.0
        return s

    def peek(m, r, c_):
        return sum(m[r + a, c_ + b] for a, b in fp if 0 <= r + a < H and 0 <= c_ + b < W)

    def rollout(m, r, c_):
        tot, disc = 0.0, 1.0
        for _ in range(horizon):
            best, bs = None, -1.0
            for di, dj in moves:
                nr, nc = r + di, c_ + dj
                if inside(nr, nc):
                    v = peek(m, nr, nc)
                    if v > bs: best, bs = (nr, nc), v
            if best is None: break
            r, c_ = best
            tot += disc * sweep(m, r, c_); disc *= gamma
        return tot

    r = int(np.clip((center_y - miny) / dy, 0, H - 1))
    c_ = int(np.clip((center_x - minx) / dx, 0, W - 1))
    path = [(r, c_)]; sweep(rem, r, c_)
    budget = kw.get("budget") or 1e9
    length = 0.0
    while length < budget:
        cand = [(di, dj) for di, dj in moves if inside(r + di, c_ + dj)]
        if not cand: break
        N = {m: 0 for m in cand}; Q = {m: 0.0 for m in cand}; t = 0
        for _ in range(n_sims):
            un = [m for m in cand if N[m] == 0]
            m = un[0] if un else max(cand, key=lambda k: Q[k] + c * math.sqrt(math.log(t + 1) / N[k]))
            sim = rem.copy()
            nr, nc = r + m[0], c_ + m[1]
            v = sweep(sim, nr, nc) + gamma * rollout(sim, nr, nc)
            N[m] += 1; t += 1; Q[m] += (v - Q[m]) / N[m]
        m = max(cand, key=lambda k: Q[k])
        if Q[m] <= 0:
            m = cand[rng.integers(len(cand))]
        r, c_ = r + m[0], c_ + m[1]
        sweep(rem, r, c_); path.append((r, c_))
        length += math.hypot(m[0] * dy, m[1] * dx)
    line = LineString([(x0 + cc * dx, y0 + rr * dy) for rr, cc in path])
    return _paths.split_path_for_drones(line, num_drones)


def load_scenario(sarenv_dir, idx, max_radius):
    hm = np.load(os.path.join(sarenv_dir, "sarenv_dataset", str(idx), "heatmap.npy"))
    H, W = hm.shape
    half = int(max_radius / METERS_PER_BIN)
    cr, cc = H // 2, W // 2
    crop = hm[max(0, cr - half):cr + half, max(0, cc - half):cc + half].astype(float)
    crop = crop / crop.sum() if crop.sum() > 0 else crop
    h, w = crop.shape
    return crop, (0.0, 0.0, w * METERS_PER_BIN, h * METERS_PER_BIN)


def sample_victims(heatmap, bounds, n, seed):
    import geopandas as gpd
    from shapely.geometry import Point
    rng = np.random.default_rng(seed)
    flat = heatmap.flatten(); flat = flat / flat.sum()
    idx = rng.choice(flat.size, size=n, p=flat)
    H, W = heatmap.shape
    minx, miny, maxx, maxy = bounds
    dx, dy = (maxx - minx) / W, (maxy - miny) / H
    pts = [Point(minx + (i % W + rng.random()) * dx, miny + (i // W + rng.random()) * dy) for i in idx]
    return gpd.GeoDataFrame(geometry=pts)


def generators():
    return {
        "Spiral":            _paths.generate_spiral_path,
        "ConcentricCircles": _paths.generate_concentric_circles_path,
        "PizzaZigzag":       _paths.generate_pizza_zigzag_path,
        "Greedy (SAREnv)":   _paths.generate_greedy_path,
        "RandomWalk":        _paths.generate_random_walk_path,
        "MCTS (ours)":       mcts_path,
    }


def run(sarenv_dir, scenarios, budget, num_drones, max_radius, seed):
    import pandas as pd
    rows = []
    for sc in scenarios:
        hm, bounds = load_scenario(sarenv_dir, sc, max_radius)
        cx, cy = (bounds[0] + bounds[2]) / 2, (bounds[1] + bounds[3]) / 2
        victims = sample_victims(hm, bounds, NUM_LOST_PERSONS, seed + sc)
        ev = _metrics.PathEvaluator(hm, bounds, victims, FOV_DEG, ALT_M, METERS_PER_BIN)
        params = dict(center_x=cx, center_y=cy, max_radius=max_radius, probability_map=hm,
                      bounds=bounds, num_drones=num_drones, fov_deg=FOV_DEG, altitude=ALT_M,
                      overlap=OVERLAP, path_point_spacing_m=SPACING_M,
                      transition_distance_m=TRANS_M, border_gap_m=PIZZA_GAP_M, budget=budget)
        for name, fn in generators().items():
            t0 = time.time()
            try:
                paths = fn(**params)
                paths = _paths.restrict_path_length(paths, budget / num_drones)
                m = ev.calculate_all_metrics(paths, DISCOUNT)
                rows.append(dict(scenario=sc, planner=name,
                                 likelihood=m["total_likelihood_score"],
                                 time_discounted=m["total_time_discounted_score"],
                                 victims_found_pct=m["victim_detection_metrics"]["percentage_found"],
                                 path_km=m["total_path_length"], secs=time.time() - t0))
                print(f"  sc{sc:>2} {name:<18} POD {m['total_likelihood_score']:.3f}  "
                      f"disc {m['total_time_discounted_score']:.3f}  "
                      f"victims {m['victim_detection_metrics']['percentage_found']:5.1f}%  "
                      f"({time.time()-t0:4.1f}s)")
            except Exception as e:
                print(f"  sc{sc:>2} {name:<18} FAILED: {type(e).__name__}: {e}")
    df = pd.DataFrame(rows)
    os.makedirs("results", exist_ok=True)
    df.to_csv("results/sarenv_bench_raw.csv", index=False)
    print("\n=== SAREnv benchmark — mean ± 95% CI over "
          f"{df.scenario.nunique()} scenarios, budget {budget/1000:.0f} km, {num_drones} drone(s) ===")
    print(f"{'planner':<18} {'POD (likelihood)':>18} {'time-discounted':>18} {'victims found %':>18}")
    summary = []
    for name, g in df.groupby("planner", sort=False):
        line = f"{name:<18}"; rec = {"planner": name}
        for col in ("likelihood", "time_discounted", "victims_found_pct"):
            mu = g[col].mean(); ci = 1.96 * g[col].std(ddof=1) / math.sqrt(len(g)) if len(g) > 1 else 0.0
            line += f" {mu:9.3f} ± {ci:6.3f}"
            rec[col + "_mean"] = mu; rec[col + "_ci95"] = ci
        print(line); summary.append(rec)
    pd.DataFrame(summary).to_csv("results/sarenv_bench_summary.csv", index=False)
    print("\nsaved results/sarenv_bench_raw.csv and results/sarenv_bench_summary.csv")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sarenv", default="../SAREnv")
    ap.add_argument("--scenarios", default="1-6")
    ap.add_argument("--budget", type=float, default=30_000)
    ap.add_argument("--drones", type=int, default=1)
    ap.add_argument("--radius", type=float, default=3000)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    global _metrics, _paths
    _metrics = _load(a.sarenv, "sarenv/analytics/metrics.py")
    _paths = _load(a.sarenv, "sarenv/analytics/paths.py")
    if "-" in a.scenarios:
        lo, hi = a.scenarios.split("-"); scen = list(range(int(lo), int(hi) + 1))
    else:
        scen = [int(s) for s in a.scenarios.split(",")]
    run(a.sarenv, scen, a.budget, a.drones, a.radius, a.seed)


if __name__ == "__main__":
    main()
