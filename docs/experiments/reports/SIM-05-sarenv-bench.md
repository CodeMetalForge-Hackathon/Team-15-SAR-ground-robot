# SIM-05 and SIM-06: SAREnv benchmark, MCTS against five baselines (`team15_starter/bench/sarenv_bench.py`)

**Label: SIMULATED** (on an external benchmark's probability heatmaps) · **Status:** SIM-05 (30 km budget) COMPLETE, git history only · SIM-06 (10 km budget) COMPLETE, committed · Re-run for this document: **NOT RUN** (SAREnv not available locally)
Back to: [18 Simulation](../../18_SIMULATION.md) · [SIM-02 fleet evaluation](SIM-02-drone-fleet-eval.md)

## In one paragraph (plain language)

SAREnv is a published search-and-rescue benchmark. For many real landscapes it provides a "heat map" of where a lost person is likely to be, a way to score a drone's flight path against that map, and a set of standard flight patterns to compare against (spirals, zig-zags, greedy). A teammate plugged our planner (a tree-search method called MCTS) into it as one more path generator, and scored every planner on 60 scenarios with the same flight-distance budget. Our planner scored highest on all three of SAREnv's measures, both with a 30 km budget and with a 10 km budget. These are scores against SAREnv's statistical model of lost people, not against real searches.

## 1. Objective and hypothesis

- **Objective:** compare the team's MCTS planner with SAREnv's official baselines, using SAREnv's own evaluator and heatmaps, so that "our planner is better" is measured by a third-party yardstick.
- **Hypothesis (from the commit messages):** "MCTS beats 5 baselines on all 3 metrics over 60 scenarios".

## 2. Date, place, people (by role)

| ID | Commit | Date | Budget (from `path_km`) | Who |
|---|---|---|---|---|
| SIM-05 | `7ed29a5` | 2026-11-07 15:33 −0500 | 30 km | drone-sim teammate (GitHub `hafsaah1`) |
| SIM-06 | `4018ff9` | 2026-11-07 15:39 −0500 | 10 km | same |

The `4018ff9` message says "60 scenarios x 2 budgets", but it **replaced** both CSVs. The committed raw CSV contains only the 10 km rows (all 360 `path_km` values are 10.0). The 30 km results survive only in `7ed29a5`.

## 3. Hardware

Not recorded. Desktop simulation.

## 4. Software

- `team15_starter/bench/sarenv_bench.py` (sha256 prefix `92ab11c9c79a90e2`). It loads SAREnv's analytics modules (metrics and paths) from an external checkout (`--sarenv ../SAREnv`); **SAREnv is not vendored**, and its version or commit is **not recorded**.
- Fixed parameters: FOV 45°, altitude 80 m, path spacing 10 m, transition 50 m, pizza gap 15 m, 30 m per heatmap bin, discount 0.999, **100 sampled lost persons per scenario** (seed + scenario number), radius 3000 m, 1 drone.
- MCTS settings in `mcts_path`: `n_sims=16`, `horizon=8`, `c=1.4`, `gamma=0.995`, RNG seed 0.

## 5. Data and ground truth

SAREnv lost-person probability heatmaps, for scenarios 1–60. The 100 victims per scenario are sampled from each heatmap, so the ground truth is synthetic, drawn from SAREnv's model. Licensing of SAREnv data: **UNVERIFIED** here (it is not redistributed by this repo).

## 6. Metrics and why they were chosen

SAREnv's `PathEvaluator.calculate_all_metrics`:

- **likelihood:** total accumulated probability mass covered (expected probability of detection);
- **time_discounted:** the same, discounted by 0.999 per step, which rewards finding probability early;
- **victims_found_pct:** the percentage of the 100 sampled victims inside the path's footprint.

These are the benchmark's official metrics, which is why they were chosen. Each planner's paths are cut to the same budget (`restrict_path_length`), so the comparison is at equal flight distance. The 95 % CI is 1.96·s/√60.

## 7. Results

### SIM-06: 10 km budget (committed; `team15_starter/results/sarenv_bench_summary.csv`)

| Planner | Likelihood | Time-discounted | Victims found (%) |
|---|---|---|---|
| **MCTS (ours)** | **0.0685 ± 0.0102** | **0.0207 ± 0.0033** | **6.95 ± 1.25** |
| Greedy (SAREnv) | 0.0506 ± 0.0083 | 0.0157 ± 0.0032 | 4.78 ± 0.93 |
| Spiral | 0.0246 ± 0.0048 | 0.0046 ± 0.0012 | 2.48 ± 0.64 |
| ConcentricCircles | 0.0245 ± 0.0047 | 0.0046 ± 0.0012 | 2.48 ± 0.63 |
| PizzaZigzag | 0.0243 ± 0.0047 | 0.0045 ± 0.0012 | 2.47 ± 0.63 |
| RandomWalk | 0.0080 ± 0.0017 | 0.0051 ± 0.0014 | 0.78 ± 0.28 |

### SIM-05: 30 km budget (`git show 7ed29a5:team15_starter/results/sarenv_bench_summary.csv`)

| Planner | Likelihood | Time-discounted | Victims found (%) |
|---|---|---|---|
| **MCTS (ours)** | **0.170 ± 0.023** | **0.0207 ± 0.0033** | **17.4 ± 2.5** |
| Greedy (SAREnv) | 0.126 ± 0.015 | 0.0160 ± 0.0033 | 11.3 ± 1.5 |
| PizzaZigzag | 0.089 ± 0.012 | 0.0045 ± 0.0012 | 8.95 ± 1.48 |
| Spiral | 0.090 ± 0.012 | 0.0046 ± 0.0012 | 8.92 ± 1.48 |
| ConcentricCircles | 0.089 ± 0.012 | 0.0046 ± 0.0012 | 8.78 ± 1.43 |
| RandomWalk | 0.024 ± 0.004 | 0.0047 ± 0.0012 | 2.28 ± 0.53 |

In both runs MCTS has the highest mean on every metric. Its CI does not overlap Greedy's for likelihood at 30 km (0.147–0.193 against 0.112–0.141). At 10 km the intervals are close (0.058–0.079 against 0.042–0.059) and overlap slightly.

## 8. Failures and interpretation

- **Provenance gap.** The committed files hold one of the two runs the commit message describes, so a reader of d1b607a sees only the 10 km result.
- **Interpretation.** The time-discounted scores of MCTS are almost identical across budgets (0.0207). That is expected: the discount makes later path segments count little, so extra budget adds mostly undiscounted likelihood.
- **Fairness.** MCTS and Greedy both see the true probability map (as do all planners in SAREnv). The advantage is in path shape under an equal budget, not in extra information.

## 9. Evidence files

| File | Where | sha256 |
|---|---|---|
| `sarenv_bench_summary.csv` (10 km) | `team15_starter/results/` (in repo) | `3af5f7da5b2f30802e8348ed49db42ae5162c337241af9bd597373a621b40e6c` |
| `sarenv_bench_raw.csv` (10 km, 360 rows) | `team15_starter/results/` (in repo) | `8a00b6080b532a462f8320ec348fd6bbad08daac4cf9b7f3fd409534b4feae58` |
| 30 km summary and raw | git history at `7ed29a5` | — |

## 10. Limitations and confounders

- The SAREnv version is not recorded, and SAREnv is not vendored.
- The victims are synthetic samples from the same heatmap the planners optimise against: an optimistic set-up for any planner that uses the map.
- 1 drone only; no terrain obstacles or flight dynamics beyond SAREnv's model.
- The MCTS hyperparameters were not tuned on held-out scenarios (not recorded either way).

## 11. Reproducibility

```bash
cd team15_starter
python3 bench/sarenv_bench.py --sarenv ../SAREnv --scenarios 1-60 --budget 10000   # SIM-06 (assumed command)
python3 bench/sarenv_bench.py --sarenv ../SAREnv --scenarios 1-60 --budget 30000   # SIM-05 (assumed command)
```

This needs a SAREnv checkout, pandas, numpy and shapely. **It was not re-run for this report:** SAREnv is not installed in this environment. The script **overwrites** `team15_starter/results/sarenv_bench_*.csv`, so run it in a copy.

## 12. What this proves / does NOT prove

**Proves (within SAREnv's model):** at equal flight budgets of 10 km and 30 km, our MCTS path generator outscored SAREnv's five baselines on SAREnv's three official metrics, averaged over 60 scenarios.

**Does NOT prove:** real-world search performance; performance with several drones (`--drones 1` only); robustness to a wrong prior; anything about the ground robot.

## 13. What we would change next time

- Write both budgets into one CSV with a budget column, plus the SAREnv commit.
- Add a mis-specified-prior condition: plan on one heatmap, sample victims from another.
- Pin SAREnv as a git submodule, or record its hash.
