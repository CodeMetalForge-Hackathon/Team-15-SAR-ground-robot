# Benchmarks

Each benchmark below is reported separately with its own evidence type, sample size and source.
**Counts from different benchmarks are never added together.**

Evidence types: **SIMULATED** (synthetic environment, software only) · **REAL MODEL INFERENCE** (a real
model run on real hardware, on synthetic or recorded inputs) · **REAL CAMERA** (real Pi camera frames) ·
**PHYSICAL** (real hardware behaviour).

## Dual-robot simulation

| | |
|---|---|
| What was tested | Complete aerial + ground rescue missions: drone search, survivor confirmation, shared-map coordination, rover routing and replanning, safety stops |
| Evidence type | **SIMULATED**: synthetic 48 m sites, simulated sensors and physics, and the team's real planning code |
| Sample | **1540 of 1540 planned runs completed**: 8 environments × 100 seeds (system under test), 4 baselines × 8 environments × 20 seeds, and 10 injected faults × 10 seeds |
| Revision | `953826b` (PR #19, merged as `2e9c7ca`); 98.3 s wall time on 12 processes |
| Sources | [`evidence/dual_rescue_benchmark_summary_953826b.md`](evidence/dual_rescue_benchmark_summary_953826b.md), per-run CSV [`evidence/dual_rescue_benchmark_runs_953826b.csv`](evidence/dual_rescue_benchmark_runs_953826b.csv) (1540 rows, each with its seed), `docs/dual_rescue/BENCHMARKS.md` (method and failure analysis) |
| Reproduce | `python3 -m simulation.dual_rescue.benchmark --runs 100 --all-environments --seed 42 --baselines 20 --stress 10` |

### Safety (all 1540 runs)

| Metric | Result |
|---|---|
| Rover collisions | **0** |
| Rover entries into corridors not observed CLEAR (UNKNOWN treated as CLEAR) | **0** |
| Motion while the safety latch was set | **0** |
| Rescue claimed where no survivor was | **0** |

### System under test: coordinated aerial-ground, MCTS aerial search (800 runs)

| Environment | Runs | Mission success | Correct outcome¹ | Survivors located | Main non-success cause |
|---|---|---|---|---|---|
| collapsed_building | 100 | 98 % | 100 % | 100/100 | debris made the survivor unreachable (reported) |
| dynamic (debris after dispatch) | 100 | 88 % | 100 % | 100/100 | unreachable after the new debris (reported) |
| maze | 100 | 62 % | 100 % | 97/100 | dead ends: 35 truly unreachable (reported) |
| multi_survivor (3 survivors + 1 false heat source) | 100 | 99 % | 99 % | 299/300 | 1 partial |
| narrow_corridors | 100 | 84 % | 100 % | 95/100 | smoke: INSUFFICIENT_INFORMATION |
| open_outdoor | 100 | 89 % | 100 % | 97/100 | canopy: INSUFFICIENT_INFORMATION |
| partially_observable | 100 | 73 % | 100 % | 84/100 | survivor under an intact roof (undetectable) |
| warehouse | 100 | 45 % | 100 % | 96/100 | mezzanine hides the approach: INSUFFICIENT_INFORMATION (48) |
| **Total** | **800** | **638 (79.8 %)** | **799 (99.9 %)** | 968/1000 | |

¹ *Correct outcome* = success, or a safe stop that ground truth justifies: the survivor really was
unreachable or invisible, or reaching them needed unobserved corridors. The system never invents a
route through UNKNOWN space.

### Baselines (same environments, same seeds 42–61, 160 runs per configuration)

| Configuration | Mean time to first discovery | Mean drone path | Mission success | Rover STOP events | Unobserved corridors driven |
|---|---|---|---|---|---|
| **MCTS aerial (PR #17) + coordinated ground** | 30.6 s | 362 m | 121/160 | 20 | 0 |
| greedy aerial (`sar.planners`) | 32.2 s | 317 m | 124/160 | — | — |
| lawnmower aerial (`sar.planners`) | 166.2 s | 1018 m | 124/160 | — | — |
| independent agents (no shared corridor map) | — | — | 138/160 | 87 | 846 |
| static route (no replanning) | — | — | 103/160; **0/20 in `dynamic`** | 20 | 0 |

Takeaways:

* Belief-driven search finds the first survivor about 5× faster than a lawnmower sweep.
* **MCTS did not outperform greedy.** No improvement is claimed.
* Replanning is essential when debris appears after dispatch.
* Sharing the map trades some completions (the independent baseline drives blind corridors behind its
  range sensor) for 4× fewer STOP events and no unobserved driving.

### Failure injection

10 seeds per fault, each with an explicit expected behaviour that is checked per run: **100/100
checks passed**.

| Fault | Expected behaviour | Passed |
|---|---|---|
| Debris drops on the rover's route | stop before contact, mark blocked, replan or report | 10/10 |
| Blocked corridors (maze) | never route through BLOCKED; correct outcome | 10/10 |
| 30 % aerial frames lost | no false CLEAR, no unsafe motion | 10/10 |
| Observations delivered 5 s late | no unsafe motion, correct outcome | 10/10 |
| False heat source | never reported as a rescue | 10/10 |
| Debris on the survivor's only doorway | UNREACHABLE reported, never at standoff | 10/10 |
| Rover link lost (t = 40–70 s) | COMMS_LOST latched, rover stopped, no auto-resume | 10/10 |
| Drone stops responding | drone marked unavailable; UNKNOWN stays UNKNOWN | 10/10 |
| Corrupted off-site coordinates | observation rejected | 10/10 |
| Drone camera blind to debris | rover ultrasonic still stops it | 10/10 |

### Known issues found by the benchmark

* **Fixed in PR #19 before the final run:**
  * a stale human-review request read as "target reached" (21/100 multi-survivor runs unsafe on
    revision `352f06d`);
  * a detour dropped after going stale during the retreat;
  * an endless search under roofs;
  * a stall on an unconfirmed candidate;
  * two baseline bugs.
* **Open:** 16 false aerial CLEAR corridor reports in `dynamic`. Looks made before debris fell were
  counted. The rover's ultrasonic caught every one, with 0 collisions.

## Rendering performance

| | |
|---|---|
| What was tested | Frame rate of the 3D digital twin while the simulation runs (scenario B, 20× speed) |
| Evidence type | Real browser measurement (Chrome headless, ANGLE Metal) on an **Apple M4 Pro**. No other GPU was measured. |
| Source | [`evidence/render_perf_m4pro.json`](evidence/render_perf_m4pro.json), `docs/dual_rescue/RENDERING.md` |

| Viewport | Preset | 3D canvas | FPS | p95 frame time |
|---|---|---|---|---|
| 1920 × 1080 | High | 1190 × 823 | 60.0 | 17.3 ms |
| 2560 × 1440 | High | 1587 × 1101 | 59.8 | 16.8 ms |
| 3840 × 2160 | Ultra | 2600 × 1675 | 60.0 | 17.6 ms |
| 3840 × 2160 | Ultra, presentation mode | 3840 × 2086 | 60.0 | 16.8 ms |

60 fps is the browser's vsync cap; headroom above it was not measured.

## Other benchmarks from the team's experiments

These are separate experiments with their own samples. They are **not** added to the dual-robot
numbers above.

### Rover scenarios A–H (SIM-01)

| | |
|---|---|
| Evidence type | **SIMULATED**: the real Navigator and safety supervisor on a synthetic trail graph |
| Source | [SIM-01](../docs/experiments/reports/SIM-01-rover-scenario-suite.md); re-run at `2e9c7ca` with identical results |
| Reproduce | `python3 -m rover.simrun <A-H>` |

| Scenario | Outcome | Route | Travelled | Sim time |
|---|---|---|---|---|
| A clear | ARRIVED | 60 m | 59.97 m | 102.25 s |
| B / C blocked edge (same world) | ARRIVED via detour D-K-L-M-G | 46 m | 83.90 m | 187.20 s |
| D two blocked edges | ARRIVED | 64 m | 105.89 m | 266.00 s |
| E no route | SAFE_STOP (no verified route) | — | 74.96 m | 211.65 s |
| F cleared edge | ARRIVED | 30 m | 29.96 m | 59.80 s |
| G sensor stops updating | SAFE_STOP (`SENSOR_STALE`) | — | 4.67 m | 8.20 s |
| H person on route | HUMAN_REVIEW | — | 20.03 m | 34.55 s |

### Drone fleet (SIM-02)

| | |
|---|---|
| Evidence type | **SIMULATED**, 20 seeds |
| Source | [SIM-02](../docs/experiments/reports/SIM-02-drone-fleet-eval.md); committed CSVs (hashes verified) |

Mean time to find everyone:

| Configuration | Time |
|---|---|
| 1 drone | 215.7 ± 79.5 s |
| 3 independent drones | 147.1 ± 51.2 s |
| 3 drones, shared map | 100.8 ± 19.8 s |
| 3 drones, shared map + claims | 93.2 ± 15.5 s |

Caveat: a later re-run at `d1b607a` gave different values (for example 91.1 ± 15.4 s), and the
registry records that it does **not** reproduce SIM-02 exactly.

### SAREnv search benchmark (SIM-05)

| | |
|---|---|
| Evidence type | **SIMULATED**: 60 scenarios × 100 sampled victims |
| Source | [SIM-05](../docs/experiments/reports/SIM-05-sarenv-bench.md); 10 km results in a committed CSV (360 rows, hash verified) |

| Budget | MCTS | Greedy |
|---|---|---|
| 10 km: likelihood score | 0.0685 ± 0.0102 | 0.0506 |
| 10 km: victims found | 6.95 ± 1.25 % | 4.78 % |
| 30 km: victims found | 17.4 ± 2.5 % | 11.3 ± 1.5 % |

Caveats:

* The 10 km confidence intervals overlap slightly.
* The 30 km results exist only in git history (`7ed29a5`).
* SAREnv is not vendored and its version is not recorded, so this was not re-run.

### Route planning (PLN-01)

| | |
|---|---|
| Evidence type | **SYNTHETIC** graph |
| Source | [PLN-01](../docs/experiments/reports/PLN-01-trail-graph-route-tests.md); 19 tests |

Results:

* A→G 60 m; C→K 20 m (22 m with J-K blocked); A→G 74 m with E-F blocked.
* A* matches Dijkstra on every pair across 5 blocked-edge sets.

### Qwen + LoRA

See [AI_MODEL_EVALUATION.md](AI_MODEL_EVALUATION.md): real model inference on synthetic frozen test
sets.
