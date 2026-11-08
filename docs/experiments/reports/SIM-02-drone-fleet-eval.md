# SIM-02 to SIM-04, SIM-07, SIM-08: Drone-fleet evaluation (`team15_starter/fleet_eval.py`)

**Label: SIMULATED** · **Status:** SIM-02 (fleet study, committed CSV) COMPLETE · SIM-03 (EMCON study, committed CSV) COMPLETE · SIM-04 (radio study) **NOT RUN** (no evidence) · SIM-07 / SIM-08 (re-runs at d1b607a) COMPLETE, **results differ from the committed CSVs**
Back to: [18 Simulation](../../18_SIMULATION.md) · [Drone build guide](../../../TEAM15_DRONE_SEARCH_BUILD.md) · [Drone hardware notes](../../../team15_starter/HARDWARE.md)

## In one paragraph (plain language)

A teammate built a computer simulation of a small drone fleet searching a forest for three missing people. The "drones", "people" and "radio" are all simulated, but the planning code and the radio message format are the real ones. The evaluation script flies the same mission 20 times with different random seeds for each set-up, and compares one drone against three drones that ignore each other, three that share a map, and three that share a map *and* split up the work. In the committed results, the coordinated fleet found everyone fastest (about 93 s against about 216 s for a single drone, in simulated time). When we re-ran the script on the final code, it was repeatable run to run, but the numbers had changed, because the code changed after those results were saved. The coordinated fleet was still fastest. Nothing here involved a real drone.

## 1. Objective and hypothesis

- **Objective:** quantify, in simulation, the benefit of (a) more drones, (b) a shared belief map, and (c) cell claims (task allocation). Separately, quantify the cost of military emission control (EMCON) with signed packets compared with civilian radio.
- **Hypothesis (from the script's docstring and commit messages):** coordinated (shared + claims) < shared < independent < single drone in time to find all people. EMCON reduces emissions at some cost in time.

## 2. Date, place, people (by role)

| ID | Run | Date | Revision | Who |
|---|---|---|---|---|
| SIM-02 | `--study fleet` → `team15_starter/results/fleet_eval_fleet.csv` | committed 2026-11-07 17:02 −0500 | `ea5016f` | drone-sim teammate (GitHub `hafsaah1`) |
| SIM-03 | `--study emcon` → `team15_starter/results/fleet_eval_emcon.csv` | committed 2026-11-07 20:45 −0500 | `e47c1bf` | same |
| SIM-04 | `--study radio` | — | — | **no CSV, log or report found** |
| SIM-07 | fleet re-run | 2026-11-08, ~12:45–13:00 UTC | d1b607a | documentation audit |
| SIM-08 | EMCON re-run | 2026-11-08, ~12:45–13:00 UTC | d1b607a | documentation audit |

The command lines for SIM-02 and SIM-03 are not recorded. The script's defaults are assumed (`--seeds 20 --time 900`). The CSV shape (20 seeds per configuration) is consistent with that.

## 3. Hardware

None in the loop. SIM-07/08 ran on an Apple M4 Pro (14 cores), macOS, Python 3.13.5, with a multiprocessing pool across all cores. The hardware for SIM-02/03 is not recorded.

## 4. Software

- `team15_starter/fleet_eval.py` (sha256 prefix `f583b85d56c9e7dd` at d1b607a) calls `homebase.simulate` with the real `link.protocol` key handling.
- Between `ea5016f` and d1b607a, `homebase.py`, `team15_starter/fleet/` and `team15_starter/sar/` changed substantially (27 files, +2878/−88 lines; including the "battery fix" in `e47c1bf` and roles plus the ~80× faster planner in `eddef53`).
- SIM-07/08 ran in a scratch copy made with `git archive d1b607a team15_starter`, so the committed CSVs were not overwritten.

## 5. Data and ground truth

- **Synthetic world:** `--scenario grid` (the default without `--web`): 24 × 24 cells of 20 m, 3 hidden people, seeds 0–19.
- **Ground truth** is the simulator's hidden people (`fleet.scenario.summarize_truth` / `match_people`, match radius 1.5 cells).
- **Every drone carries thermal + mmWave** (`loadout="thermal,mmwave"`), so only coordination differs.
- **Sensor PODs are assumptions** ("demo-calibrated starting points" in `team15_starter/sar/sensors.py`).

## 6. Metrics and why they were chosen

| Column | Definition (from `homebase.simulate`) | Why |
|---|---|---|
| `t_found` | sim time when every person had been first detected (`None` → counted as 900 s) | primary speed metric |
| `t_done` | sim time when every person is matched to a confirmed track with an observation/assessment | the full mission |
| `done` | the above reached within 900 s | success rate |
| `vitals` | fraction of people whose track was assessed | care information |
| `delivered` | detections received / made (store-and-forward) | radio robustness |
| `emissions` | packets transmitted by drones | EMCON cost |
| `deaths` | drones lost to battery | safety of the plan |
| `false_contacts` | tracks not matched to a person | precision |

Mean ± 1.96·s/√n over 20 seeds. Censoring at 900 s biases the means downward for configurations that sometimes fail, which the script notes is conservative.

## 7. Results

### SIM-02: fleet study (committed CSV, `ea5016f`; sha256 `637794afe27a6c7b12d33ed6a470f4aa5db1b1258cc8a12b6ebfdc41a4f7f483`)

| Configuration | n | t_found (s) | t_done (s) | Success | Vitals | Emissions | Deaths | False contacts |
|---|---|---|---|---|---|---|---|---|
| 1 drone | 20 | 215.7 ± 79.5 | 260.2 ± 97.7 | 95 % | 95 % | 474 | 0 | 0.00 |
| 3 drones, no shared map | 20 | 147.1 ± 51.2 | 204.2 ± 84.9 | 95 % | 95 % | 1099 | 0 | 0.05 |
| 3 drones, shared map | 20 | 100.8 ± 19.8 | 206.5 ± 105.2 | 90 % | 97 % | 1117 | 0 | 0.05 |
| 3 drones, shared + claims | 20 | 93.2 ± 15.5 | 201.5 ± 105.9 | 90 % | 95 % | 1091 | 0 | 0.00 |

### SIM-03: EMCON study (committed CSV, `e47c1bf`; sha256 `2dbb5b58bdc29ea79250aec00c87fd624c3b777f7b8fef23cf20261f4131904c`)

| Configuration | n | t_found (s) | t_done (s) | Success | Vitals | Emissions | Deaths |
|---|---|---|---|---|---|---|---|
| civilian radio | 20 | 91.6 ± 14.1 | 196.6 ± 106.2 | 90 % | 95 % | 1064 | 0 |
| military EMCON + signed | 20 | 130.1 ± 21.2 | 272.9 ± 104.4 | 90 % | 95 % | 425 | 1 |

### SIM-07 / SIM-08: re-runs at d1b607a (2026-11-08)

The fleet study took 85 s of wall time. **It was run twice, and the two CSVs were byte-identical** (sha256 `cb2a53befeefc4065f9a5ca8401a86f990612106b157c86cc8924996f7a1d419`). The EMCON re-run CSV has sha256 `e43a6f1d1c572631cc79dba6286dd861617d35b332ef5bac36c20d8634d2f8cf`. Neither re-run file is stored in the repo.

| Configuration | t_found (s) | t_done (s) | Success | Vitals | Emissions | Deaths |
|---|---|---|---|---|---|---|
| 1 drone | 218.4 ± 65.9 | 373.2 ± 124.6 | 85 % | 95 % | 663 | 0 |
| 3, no shared map | 149.4 ± 50.0 | 253.3 ± 108.9 | 90 % | 97 % | 1345 | 0 |
| 3, shared map | 128.0 ± 66.3 | 280.8 ± 136.2 | 85 % | 93 % | 1494 | 0 |
| 3, shared + claims | 91.1 ± 15.4 | 208.1 ± 108.2 | 90 % | 95 % | 1112 | 0 |
| civilian radio | 80.4 ± 11.5 | 268.3 ± 142.4 | 80 % | 92 % | 1895 | 0 |
| military EMCON + signed | 174.1 ± 89.0 | 444.2 ± 157.1 | 65 % | 83 % | 907 | 0 |

### SIM-04: radio study

**NOT RUN / no evidence.** `fleet_eval.py` defines it (clean, 30 % loss, 30 % loss + 60 s jam), but no results file, log or description exists in the repository or in PR #17.

## 8. Failures and interpretation

- **Reproducibility failure across revisions.** The committed CSVs cannot be regenerated from d1b607a. The evaluation is deterministic *within* a commit, so the difference comes from code changes, not noise. Because the generating commands were not recorded, we can't even be sure SIM-02/03 used the defaults.
- **What is robust:** "shared + claims" has the lowest t_found in both revisions (93.2 and 91.1 s), and the single drone is slowest in both (215.7 and 218.4 s). The relative benefit of the shared map *without* claims is not robust (100.8 → 128.0 s, with a wide CI at d1b607a). The EMCON time penalty grew from +42 % to +117 % in t_found, and its success rate dropped from 90 % to 65 % at d1b607a.
- **Wide intervals.** With n = 20, several CIs overlap (for example "no shared map" against "shared map" at d1b607a), so those pairwise orderings are not statistically established.

## 9. Evidence files

| File | Where | sha256 |
|---|---|---|
| `fleet_eval_fleet.csv` | `team15_starter/results/` (in repo) | `637794afe27a6c7b12d33ed6a470f4aa5db1b1258cc8a12b6ebfdc41a4f7f483` |
| `fleet_eval_emcon.csv` | `team15_starter/results/` (in repo) | `2dbb5b58bdc29ea79250aec00c87fd624c3b777f7b8fef23cf20261f4131904c` |
| Re-run CSVs (SIM-07/08) | scratch only, not published | `cb2a53be…a7d419` (fleet), `e43a6f1d…f8cf` (EMCON) |

## 10. Limitations and confounders

- Assumed sensor PODs; a simplified radio; synthetic people and terrain (grid scenario).
- Censored means at 900 s.
- The CSVs are not tied to recorded command lines.
- 20 seeds only.
- The EMCON configuration also turns on authentication (`--key`), so EMCON and signing are confounded in one condition.

## 11. Reproducibility

```bash
# in a scratch copy, so the committed CSVs are not overwritten
git archive HEAD team15_starter | tar -x -C <scratch> && cd <scratch>/team15_starter
python3 fleet_eval.py --study fleet --seeds 20      # ~85 s on 14 cores
python3 fleet_eval.py --study emcon --seeds 20
```

To regenerate SIM-02 exactly, check out `ea5016f` (and `e47c1bf` for SIM-03) and run with the defaults. That was not attempted for this report.

## 12. What this proves / does NOT prove

**Proves (within the model):** at both revisions, coordination with cell claims finds the three simulated people fastest, and a single drone is slowest. The evaluation is deterministic at a fixed commit.

**Does NOT prove:** anything about real drones, real sensors, real radio or real people; the absolute times; the robustness to radio loss (no radio results); that the committed CSVs describe the final code.

## 13. What we would change next time

- Commit the CSV together with the code change that produced it, and write the full argv and the git SHA into the CSV header.
- Separate EMCON from signing as two factors.
- Run the radio study, and use more seeds for the high-variance configurations.
