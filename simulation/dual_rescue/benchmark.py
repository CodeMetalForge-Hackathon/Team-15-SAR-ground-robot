"""Reproducible benchmark runner for the dual-robot rescue SIMULATION.

    python3 -m simulation.dual_rescue.benchmark --runs 20 --all-environments --seed 42
    python3 -m simulation.dual_rescue.benchmark --runs 100 --all-environments --seed 42 --baselines 20 --stress 10

Every run is one complete Mission (fixed 0.05 s ticks, fixed seed). For every run the record holds the
environment, seed, software revision, configuration, all metrics (simulator ground truth is used only
here, after the run) and the outcome. Failed and unsafe runs are kept. Results: JSON + CSV + summary.md
(+ PNG charts when matplotlib is installed) under --out (default benchmark_results/<UTC time>, gitignored).

Configurations
    coordinated / mcts           the system under test
    --baselines N                same environments and seeds (first N per environment):
        aerial planner greedy, lawnmower (sar.planners, unchanged; coordinated ground)
        ground mode independent (no shared corridor map, every corridor a sensor-gated probe)
        ground mode static_route (shortest path, no replanning)
    --stress N                   failure-injection suite, N seeds per fault, each with an explicit
                                 expected behaviour that is checked per run (see FAULTS)
"""
from __future__ import annotations

import os

os.environ.setdefault("OMP_NUM_THREADS", "1")          # many small numpy arrays: threads only add overhead
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

import argparse  # noqa: E402
import csv  # noqa: E402
import json  # noqa: E402
import statistics  # noqa: E402
import subprocess  # noqa: E402
import time  # noqa: E402
from concurrent.futures import ProcessPoolExecutor  # noqa: E402
from datetime import datetime, timezone  # noqa: E402
from pathlib import Path  # noqa: E402

from simulation.dual_rescue.environments import ENVIRONMENTS, make_environment  # noqa: E402
from simulation.dual_rescue.mission import Mission  # noqa: E402
from simulation.dual_rescue.world import Debris  # noqa: E402

# name -> (environment, scenario modifier description, expected behaviour, check(evaluate) -> bool)
FAULTS = {
    "unexpected_debris": ("dynamic", "debris drops onto the rover's route after dispatch",
                          "rover stops before contact (no collision), marks the corridor blocked, replans or reports",
                          lambda e: e["ground"]["collisions"] == 0 and e["outcome"] != "UNSAFE"),
    "blocked_corridors": ("maze", "static debris in a maze with dead ends",
                          "no route through a BLOCKED corridor; correct outcome (rescue, or unreachable reported)",
                          lambda e: e["joint"]["safety_violations"] == 0 and e["correct_outcome"]),
    "missing_observations": ("collapsed_building", "30 % of aerial frames lost",
                             "lost frames give no evidence: no false CLEAR, no unsafe motion",
                             lambda e: e["aerial"]["missing_frames"] > 0 and e["aerial"]["false_clear_reports"] == 0
                             and e["joint"]["safety_violations"] == 0),
    "delayed_observations": ("collapsed_building", "aerial observations delivered 5 s late",
                             "decisions wait for evidence; no unsafe motion; correct outcome",
                             lambda e: e["joint"]["safety_violations"] == 0 and e["correct_outcome"]),
    "false_detections": ("multi_survivor", "a false heat source (decoy) in another room",
                         "a decoy is never reported as a rescue (incorrect claims = 0)",
                         lambda e: e["joint"]["incorrect_claims"] == 0 and e["joint"]["safety_violations"] == 0),
    "unreachable_target": ("collapsed_building", "debris on the survivor's only doorway",
                           "UNREACHABLE (or INSUFFICIENT_INFORMATION) reported; never AT_STANDOFF",
                           lambda e: e["ground"]["reached"] == 0 and e["outcome"] in
                           ("UNREACHABLE_REPORTED", "INSUFFICIENT_INFORMATION", "SURVIVOR_NOT_FOUND")),
    "lost_communication": ("collapsed_building", "rover mission link down from t=40 s to t=70 s",
                           "COMMS_LOST latched by the rover safety supervisor, rover stopped, no auto-resume",
                           lambda e: (e["joint"]["comm"] or {}).get("latched_comms_lost") is True
                           and e["ground"]["latched_motion_ticks"] == 0 and e["outcome"] == "SAFE_STOP_FAULT"),
    "agent_timeout": ("collapsed_building", "AIR-1 stops responding at t=15 s",
                      "AIR-1 marked UNAVAILABLE; UNKNOWN corridors stay UNKNOWN; no unsafe motion",
                      lambda e: e["joint"]["drone_lost"] and e["ground"]["unknown_entries"] == 0
                      and e["joint"]["safety_violations"] == 0),
    "invalid_coordinates": ("collapsed_building", "a corrupted aerial observation with coordinates off the site",
                            "observation rejected, never placed on the map",
                            lambda e: e["joint"]["rejected_obs"] >= 1 and e["joint"]["safety_violations"] == 0),
    "conflicting_observations": ("dynamic", "drone camera blind to debris (reports corridors CLEAR)",
                                 "rover ultrasonic still stops it; BLOCKED is kept over a later aerial CLEAR",
                                 lambda e: e["ground"]["collisions"] == 0 and e["ground"]["unknown_entries"] == 0),
}


def stress_scenario(fault: str, seed: int):
    env = FAULTS[fault][0]
    sc = make_environment(env, seed)
    if fault == "missing_observations":
        sc.faults["aerial_dropout"] = 0.3
    elif fault == "delayed_observations":
        sc.faults["link_delay_s"] = 5.0
    elif fault == "unreachable_target":
        r = sc.layout.rooms[sc.survivors[0].room]
        sc.debris.append(Debris("UX", r.node, r.room_id, 2.0, note="doorway collapse"))
    elif fault == "lost_communication":
        sc.comm_loss = (40.0, 70.0)
    elif fault == "agent_timeout":
        sc.faults["drone_fail_t"] = 15.0
    elif fault == "invalid_coordinates":
        sc.faults["invalid_obs_t"] = 10.0
    elif fault == "conflicting_observations":
        sc.faults["aerial_blind_debris"] = True
    return sc


def git_rev() -> str:
    try:
        rev = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=5).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--", "simulation", "rover", "planner", "team15_starter"],
                               capture_output=True, text=True, timeout=5).stdout.strip()
        return rev + ("+dirty" if dirty else "")
    except Exception:  # noqa: BLE001
        return "unknown"


def run_one(job: dict) -> dict:
    t0 = time.perf_counter()
    if job.get("fault"):
        sc = stress_scenario(job["fault"], job["seed"])
    else:
        sc = make_environment(job["env"], job["seed"])
    m = Mission(scenario=sc, mode=job["mode"], planner=job["planner"])
    m.run_until(lambda mm: mm.done())
    ev = m.evaluate()
    rec = dict(job, outcome=ev["outcome"], success=ev["success"], correct_outcome=ev["correct_outcome"],
               metrics=ev, wall_s=round(time.perf_counter() - t0, 3), sim_t=round(m.t, 2), ticks=m.ticks)
    if job.get("fault"):
        rec["expected"] = FAULTS[job["fault"]][2]
        rec["fault_check_passed"] = bool(FAULTS[job["fault"]][3](ev))
    return rec


def flatten(rec: dict) -> dict:
    out = {k: v for k, v in rec.items() if k != "metrics"}
    for grp in ("aerial", "ground", "joint"):
        for k, v in rec["metrics"][grp].items():
            if isinstance(v, (dict, list)):
                v = json.dumps(v, sort_keys=True)
            out[f"{grp}.{k}"] = v
    return out


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return round(statistics.mean(xs), 3) if xs else None


def summarise(records: list[dict]) -> str:
    lines = []
    groups: dict[tuple, list] = {}
    for r in records:
        if r.get("fault"):
            continue
        groups.setdefault((r["env"], r["mode"], r["planner"]), []).append(r)
    lines.append("| environment | mode | aerial planner | runs | mission success | correct outcome | located/survivors | "
                 "coverage | 1st discovery s | drone path m | rover path m | replans | STOP events | collisions | "
                 "unknown entries | incorrect assign. | safety viol. | mean sim s |")
    lines.append("|" + "---|" * 18)
    for (env, mode, pl), rs in sorted(groups.items()):
        M = [r["metrics"] for r in rs]
        n = len(rs)
        loc = sum(m["aerial"]["located"] for m in M)
        sv = sum(m["aerial"]["survivors"] for m in M)
        lines.append(
            f"| {env} | {mode} | {pl} | {n} | {sum(r['success'] for r in rs) / n:.0%} | "
            f"{sum(r['correct_outcome'] for r in rs) / n:.0%} | {loc}/{sv} | "
            f"{_mean([m['aerial']['coverage'] for m in M]):.2f} | {_mean([m['aerial']['first_discovery_t'] for m in M])} | "
            f"{_mean([m['aerial']['path_m'] for m in M])} | {_mean([m['ground']['path_m'] for m in M])} | "
            f"{_mean([m['ground']['replans'] for m in M])} | {_mean([m['ground']['stop_events'] for m in M])} | "
            f"{sum(m['ground']['collisions'] for m in M)} | {sum(m['ground']['unknown_entries'] for m in M)} | "
            f"{sum(m['joint']['incorrect_assignments'] for m in M)} | {sum(m['joint']['safety_violations'] for m in M)} | "
            f"{_mean([r['sim_t'] for r in rs])} |")
    out = ["## Configurations", "", *lines, ""]
    oc: dict[tuple, dict] = {}
    for r in records:
        if not r.get("fault"):
            oc.setdefault((r["env"], r["mode"], r["planner"]), {}).setdefault(r["outcome"], 0)
            oc[(r["env"], r["mode"], r["planner"])][r["outcome"]] += 1
    out += ["## Outcome distribution", "", "| environment | mode | planner | outcomes |", "|---|---|---|---|"]
    for k, v in sorted(oc.items()):
        out.append(f"| {k[0]} | {k[1]} | {k[2]} | " + ", ".join(f"{o} {c}" for o, c in sorted(v.items())) + " |")
    st = [r for r in records if r.get("fault")]
    if st:
        out += ["", "## Failure injection", "", "| fault | environment | injected | expected behaviour | runs | check passed | outcomes |",
                "|---|---|---|---|---|---|---|"]
        for f, (env, what, exp, _chk) in FAULTS.items():
            rs = [r for r in st if r["fault"] == f]
            if not rs:
                continue
            cnt: dict[str, int] = {}
            for r in rs:
                cnt[r["outcome"]] = cnt.get(r["outcome"], 0) + 1
            out.append(f"| {f} | {env} | {what} | {exp} | {len(rs)} | {sum(r['fault_check_passed'] for r in rs)}/{len(rs)} | "
                       + ", ".join(f"{o} {c}" for o, c in sorted(cnt.items())) + " |")
    return "\n".join(out) + "\n"


def charts(records: list[dict], out: Path) -> list[str]:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:  # noqa: BLE001
        return []
    made = []
    base = [r for r in records if not r.get("fault") and r["mode"] == "coordinated" and r["planner"] == "mcts"]
    envs = sorted({r["env"] for r in base})
    if envs:
        fig, ax = plt.subplots(figsize=(10, 4.2))
        succ = [sum(r["success"] for r in base if r["env"] == e) / max(1, sum(1 for r in base if r["env"] == e)) for e in envs]
        corr = [sum(r["correct_outcome"] for r in base if r["env"] == e) / max(1, sum(1 for r in base if r["env"] == e)) for e in envs]
        x = range(len(envs))
        ax.bar([i - 0.2 for i in x], succ, 0.4, label="mission success", color="#4c8dff")
        ax.bar([i + 0.2 for i in x], corr, 0.4, label="correct outcome (incl. safe aborts)", color="#4cc38a")
        ax.set_xticks(list(x), [e.replace("_", "\n") for e in envs], fontsize=8)
        ax.set_ylim(0, 1.05)
        ax.set_title("Coordinated aerial-ground rescue (SIMULATION)")
        ax.legend(fontsize=8)
        fig.tight_layout()
        fig.savefig(out / "success_by_environment.png", dpi=130)
        made.append("success_by_environment.png")
        plt.close(fig)
    cfgs = sorted({(r["mode"], r["planner"]) for r in records if not r.get("fault")})
    if len(cfgs) > 1:
        fig, axs = plt.subplots(1, 3, figsize=(13, 4))
        for ax, (key, title) in zip(axs, [(("aerial", "coverage"), "aerial coverage"),
                                          (("aerial", "first_discovery_t"), "time to first discovery (s)"),
                                          (("ground", "stop_events"), "rover STOP events")]):
            vals = [_mean([r["metrics"][key[0]][key[1]] for r in records if not r.get("fault") and (r["mode"], r["planner"]) == c]) or 0 for c in cfgs]
            ax.bar(range(len(cfgs)), vals, color=["#35d0e0", "#4c8dff", "#f2b33d", "#a48bd8", "#4cc38a"][:len(cfgs)])
            ax.set_xticks(range(len(cfgs)), [f"{m}\n{p}" for m, p in cfgs], fontsize=7)
            ax.set_title(title, fontsize=10)
        fig.tight_layout()
        fig.savefig(out / "baselines.png", dpi=130)
        made.append("baselines.png")
        plt.close(fig)
    return made


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--runs", type=int, default=20, help="seeds per environment for the system under test")
    p.add_argument("--seed", type=int, default=42, help="first seed (runs use seed, seed+1, ...)")
    p.add_argument("--all-environments", action="store_true")
    p.add_argument("--env", action="append", choices=ENVIRONMENTS, help="environment(s) when not --all-environments")
    p.add_argument("--baselines", type=int, default=0, help="seeds per environment for each baseline configuration")
    p.add_argument("--stress", type=int, default=0, help="seeds per fault in the failure-injection suite")
    p.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    p.add_argument("--out", default=None)
    a = p.parse_args(argv)
    envs = list(ENVIRONMENTS) if a.all_environments or not a.env else a.env
    seeds = [a.seed + i for i in range(a.runs)]
    jobs = [{"env": e, "seed": s, "mode": "coordinated", "planner": "mcts"} for e in envs for s in seeds]
    for e in envs:
        for s in seeds[:a.baselines] if a.baselines else []:
            jobs += [{"env": e, "seed": s, "mode": "coordinated", "planner": "greedy"},
                     {"env": e, "seed": s, "mode": "coordinated", "planner": "lawnmower"},
                     {"env": e, "seed": s, "mode": "independent", "planner": "mcts"},
                     {"env": e, "seed": s, "mode": "static_route", "planner": "mcts"}]
    for f in FAULTS if a.stress else []:
        jobs += [{"env": FAULTS[f][0], "seed": a.seed + i, "mode": "coordinated", "planner": "mcts", "fault": f}
                 for i in range(a.stress)]
    rev = git_rev()
    out = Path(a.out or f"benchmark_results/{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}")
    out.mkdir(parents=True, exist_ok=True)
    print(f"{len(jobs)} runs planned ({len(envs)} environments, seeds {seeds[0]}..{seeds[-1]}, {a.workers} workers); rev {rev}")
    t0 = time.time()
    records = []
    with ProcessPoolExecutor(max_workers=a.workers) as ex:
        for i, rec in enumerate(ex.map(run_one, jobs, chunksize=2)):
            rec["software_revision"] = rev
            records.append(rec)
            if (i + 1) % 50 == 0:
                print(f"  {i + 1}/{len(jobs)} runs complete ({time.time() - t0:.0f} s)")
    meta = {"created_utc": datetime.now(timezone.utc).isoformat(), "software_revision": rev, "runs_completed": len(records),
            "runs_planned": len(jobs), "seeds": seeds, "environments": envs, "baseline_seeds_per_env": a.baselines,
            "stress_seeds_per_fault": a.stress, "wall_s": round(time.time() - t0, 1),
            "tick_s": 0.05, "note": "SIMULATION only; synthetic sites; metrics use simulator ground truth after each run"}
    (out / "results.json").write_text(json.dumps({"meta": meta, "runs": records}, indent=1, default=str))
    flat = [flatten(r) for r in records]
    keys = sorted({k for f in flat for k in f})
    with open(out / "results.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=keys)
        w.writeheader()
        w.writerows(flat)
    summ = summarise(records)
    made = charts(records, out)
    (out / "summary.md").write_text(f"# Benchmark summary\n\nRevision `{rev}`, {len(records)} completed runs of {len(jobs)} "
                                    f"planned, wall {meta['wall_s']} s.\n\n" + summ +
                                    ("\nCharts: " + ", ".join(made) + "\n" if made else ""))
    print(summ)
    print(f"completed {len(records)}/{len(jobs)} runs in {meta['wall_s']} s -> {out}/results.json, results.csv, summary.md"
          + (f", {', '.join(made)}" if made else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
