# Test results

Automated tests run on **mocked, simulated or synthetic inputs**. They check software behaviour, not
physical hardware. Counts are per suite and are **not** combined across unrelated suites.

## Summary by suite

Local results at `main` = `2e9c7ca` (PR #19 merge) on macOS arm64, Python 3.13.5, pytest 8.3.4. CI
results come from the GitHub Actions logs for the same commit.

| Suite | Tests | Local result | In CI | CI result at `2e9c7ca` |
|---|---|---|---|---|
| `planner/tests` (routing, A* vs Dijkstra) | 19 | 19 passed | `ci` | part of the `ci` total below |
| `perception/tests` (camera pipeline, synthetic frames) | 39 | 39 passed | `ci`, `perception` | `perception`: 38 passed, 1 skipped (needs torch weights) |
| `dashboard/tests` | 70 | 70 passed | `ci` | 6 skipped in CI (private simulated fixtures) |
| `tests/e2e` | 31 | 31 passed | `ci` | |
| `rover/tests` (Navigator, safety supervisor, bridge, ranging contract) | 284 | 284 passed | `ci` | |
| `camera_mapping/tests` | 97 | 97 passed | `ci` | 1 skipped in CI (needs private recorded Pi frames) |
| `simulation/dual_rescue/tests` | 25 | 25 passed | `ci` | |
| **pytest.ini default suite (the 7 suites above)** | **565** | **565 passed, 0 failed** | `ci` | **557 passed, 8 skipped** (run 42487209496) |
| `lidar/tests` | 124 | 124 passed | `lidar` | 124 passed; both hardware gates refused, as designed |
| `ranging/tests` | 126 | 126 passed | `ranging` | 126 passed at `ba7eaa1` (path-filtered) |
| `qwen_advisory/tests` | 23 | 23 passed (re-run for this package) | `qwen-advisory` | 23 passed at `ba7eaa1` (path-filtered) |
| `team15_starter/tests/test_fleet.py` (script) | 23 checks | "ALL FLEET TESTS PASSED" | **no workflow** | — |
| `team15_starter/tests/test_link.py` (script) | 30 checks | "ALL LINK TESTS PASSED" | **no workflow** | — |
| Docs check (`scripts/check_docs.py`: links, anchors, repo paths, privacy patterns) | 115 files | 0 issues | `docs` | 0 issues |

Notes:

* The 8 tests skipped in CI need data that is deliberately kept out of Git: private fixtures, torch
  weights and recorded Pi frames. They pass locally where that data exists.
* `docs/19_TESTING_AND_BENCHMARKS.md` was written at `d1b607a` (540 default tests) and predates PR #19's
  25 tests.
* Known test-isolation bug: `team15_starter`'s terrain test can start a network fetch, so run it in a
  copy of the repo.

## Dual-robot simulation tests

25 tests in [`simulation/dual_rescue/tests/test_dual_rescue.py`](../simulation/dual_rescue/tests/test_dual_rescue.py)
(SIMULATED) cover:

* aerial search finds the survivor only inside the camera footprint;
* **no ground-truth leakage** (moving the survivor leaves the flight identical until a detection);
* the MCTS vs lawnmower baseline;
* the rover routes only over corridors observed CLEAR;
* observation exchange only over the link;
* dynamic debris → STOP / VERIFY / MARK / SCAN → aerial re-check → replan;
* debris dropped from the dashboard is sensed, never announced;
* **UNKNOWN is not CLEAR**, with operator-approved sensor-gated probes;
* explicit survivor ranking;
* COMMS_LOST latched with no auto-resume;
* drone timeout and invalid-coordinate rejection;
* Qwen guard, motor-pattern discard and citation provenance;
* deterministic replay;
* **no hardware module imported**;
* 8 environment generators that produce valid layouts and safe runs;
* the `/api/rescue` endpoints.

## Safety supervisor and fault tests (MOCKED / SIMULATED)

| Area | What is tested | Tests | Source |
|---|---|---|---|
| Safety supervisor | output defaults to zero; operator approval required; speed and duration bounded; commands expire; stops immediate; forward refused unless CLEAR; heartbeat loss latches **COMMS_LOST** (> 0.25 s) with no auto-restart; stale sensor while moving latches; undervoltage and unknown power latch; e-stop latches and only an operator resets it | 21 | `rover/tests/test_supervisor.py`, `docs/17_SAFETY_ARCHITECTURE.md` |
| Fail-closed forward motion (Issue #9) | forward needs CLEAR, `forward_allowed is True`, a reading no more than 0.20 s old and hardware status OK. None, False, stale, NaN, future-dated or malformed readings are refused. A controller disconnect latches `DRIVER_FAULT`. A static allow-list guards the motor path | 40 | [ROV-01](../docs/experiments/reports/ROV-01-issue9-fail-closed-tests.md) (PR #14) |
| Bridge link faults | cable pull stops both sides; a reconnect requires re-arming; slow or stopped acks fail the health check; hung firmware gives `DRIVER_FAULT`; the modelled watchdog zeroes the motors within 300 ms | 63 | [BRG-01](../docs/experiments/reports/BRG-01-bridge-watchdog-mocked-tests.md) (PR #15) |
| Service and network faults | an unreachable service, disconnect or timeout gives STALE / UNKNOWN / DISCONNECTED (ranging, dashboard, LiDAR, perception); the Qwen client falls back on error or timeout | — | per-suite tests |
| Radio link (drone fleet) | replayed, unsigned or wrong-key packets rejected; at 20 % packet loss, 3 drones found everyone in 113 simulated seconds | script | `team15_starter/tests/test_link.py`, `test_fleet.py` |

## CI and pull requests

* **Workflows:**
  * `ci`: route smoke check + pytest default suite.
  * `perception`.
  * `lidar` (tests + 2 negative hardware-gate steps).
  * `ranging` (tests + 1 negative gate step).
  * `qwen-advisory`.
  * `docs` (links, anchors, privacy patterns).
* **History at the time of writing:**
  * **main: 37 runs, 37 successful.**
  * Whole repository: 303 runs, 284 successful. All 19 failures were on feature branches:
    * OpenCV 5 dropping `HOGDescriptor`, fixed by pinning;
    * a vendored PNG tripping the privacy test, fixed;
    * docs checks on two unmerged branches.
* **Pull requests: 16 merged, 1 open, 1 closed without merging.**

| PR | Topic | Merge commit |
|---|---|---|
| #1 | drone search build guide | `45e2659` |
| #2 | Dijkstra route planner (A→G 60 m) | `bbccb31` |
| #3 | bench camera detector | `baa1804` |
| #5 | operator dashboard | `790e3ae` |
| #7 | Grove ultrasonic range service | `691addb` |
| #8 | RoverC navigation (simulation) | `f55833a` |
| #10 | CI workflow naming | `06a69b9` |
| #11 | RPLIDAR C1 | `4ed7722` |
| #12 | Qwen advisory | `205dbc4` |
| #13 | Qwen model documentation | `0a55e3c` |
| #14 | fail-closed forward motion | `5760eaf` |
| #15 | StickC USB bridge (mocked) | `89a0e81` |
| #16 | camera obstacle mapping | `0c9acc3` |
| #17 | drone fleet simulation roles | `d1b607a` |
| #18 | engineering documentation and experiment registry | `ba7eaa1` |
| #19 | dual-robot rescue simulation | `2e9c7ca` |
| #6 | sensor identification specs | open |
| #20 | Mac/Pi rover integration | closed, not merged |

## Experiment registry

[`docs/experiments/EXPERIMENT_REGISTRY.md`](../docs/experiments/EXPERIMENT_REGISTRY.md) has **157
rows**: 141 executed, 4 duplicates, 12 not run. It was compiled at `d1b607a`, before PR #19, so the
dual-robot benchmark is reported separately in [BENCHMARKS.md](BENCHMARKS.md).

* **Rows by area:** CAM 34, QWN 34, RNG 21, LDR 15, ROV 14, MAP 12, SIM 10, CI 6, DSH 4, PLN 3,
  BRG 2, EXT 2.
* **Executed rows by evidence type (deduplicated):** real hardware 61, recorded 7,
  simulated / mocked / synthetic 71, not applicable 2.
* **Status (raw rows):** complete 107, failed 14, inconclusive 13, partial 11, not run 12.
* The registry also lists **40 claims for which no evidence was found**.

## Reproduce

```bash
pip install -r requirements.txt
python3 -m pytest -q                                     # default suite (565)
for d in lidar/tests ranging/tests qwen_advisory/tests; do python3 -m pytest -q "$d"; done
python3 -m planner.route A G                             # CI smoke check: 60 m, A..G
python3 -m rover.simrun B                                # rover scenarios A-H (simulation)
python3 scripts/check_docs.py .
python3 -m simulation.dual_rescue.benchmark --runs 20 --all-environments --seed 42
```
