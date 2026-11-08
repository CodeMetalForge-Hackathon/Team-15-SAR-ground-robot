# 19 · Testing and benchmarks

This document explains how Team-15's software is tested: which suites exist, how `pytest.ini` and the five GitHub Actions workflows divide the work, how many tests pass at `d1b607a` (re-run for this document), which tests skip and why, what the CI history shows, and what the tests do **not** prove. Every count here was either re-run locally on 8 Nov 2026 or read from a GitHub Actions log, and the source is named.

**Status:** Implemented. 818 automated pytest tests plus a 30-check protocol script pass locally at `d1b607a` (SIMULATED / MOCKED / SYNTHETIC inputs). No test touches real hardware.

**Related:** [01 Architecture](01_SYSTEM_ARCHITECTURE.md) · [17 Safety architecture](17_SAFETY_ARCHITECTURE.md) · [18 Simulation](18_SIMULATION.md) · [20 Runbook](20_DEPLOYMENT_AND_RUNBOOK.md) · [21 Troubleshooting](21_TROUBLESHOOTING.md) · [Benchmark results](experiments/BENCHMARK_RESULTS.md) · reports [CI-001](experiments/reports/CI-001-ci-regression-history.md) and [CI-002](experiments/reports/CI-002-local-test-suite-d1b607a.md)

---

## 1. Why the test strategy looks like this

The hackathon had real hardware, but very little of it was proven to work: no wheel turned, the ultrasonic sensor returned no echoes, the LiDAR was never scanned, and the Pi dropped off the network several times. The team therefore tested the **logic around the hardware** exhaustively and kept the hardware itself behind gates. The tests fall into four kinds:

| Kind | What it checks | Example |
|---|---|---|
| **Contract tests** | Producers and consumers agree on a versioned JSON schema, and malformed input fails closed | `rover/tests/test_ranging_contract.py` pins the rover to the ranging code's `team15.rover_range_fields/1` |
| **Fail-closed behaviour tests** | Every bad input (stale, NaN, future-dated, contradictory, missing) leads to STOP, UNKNOWN or ERROR, never to CLEAR | `rover/tests/test_issue9_fail_closed.py` (40 tests) |
| **Static architecture tests** | Code that must not reach the motors cannot import the motor path; no images are tracked in Git | `test_nothing_outside_the_allow_list_can_reach_the_motor_path`, `test_lidar_package_imports_no_actuation_or_gpio`, `test_no_photos_tracked_in_git` |
| **Simulation and scenario tests** | End-to-end behaviour on synthetic worlds | rover scenarios A–H, 20+ LiDAR scenarios, drone-fleet sim |

A passing test in any of these kinds shows that the **code behaves as designed on its inputs**. None of them measures a sensor, a motor or a model against the physical world (§7).

## 2. Test layout

### 2.1 `pytest.ini`

```ini
[pytest]
pythonpath = .
testpaths = planner/tests perception/tests dashboard/tests tests/e2e rover/tests camera_mapping/tests
```

`pytest -q` from the repository root runs only these six directories, the **default suite**. Four more suites are deliberately outside `testpaths` and run separately: `lidar/tests`, `ranging/tests`, `qwen_advisory/tests` and `team15_starter/tests`. Each was added by a PR that promised not to touch `pytest.ini` or `requirements.txt`, so it brought its own workflow, or none (§3).

### 2.2 Counts per file at `d1b607a`

Collected with `python3 -m pytest -q -p no:cacheprovider --collect-only <dir>` and run on 8 Nov 2026 (macOS 26.6.1 arm64, Python 3.13.5). All passed. Labels describe the **inputs** the tests use.

| Suite | File | Tests | Inputs |
|---|---|---|---|
| planner (19) | `planner/tests/test_route.py` | 12 | SYNTHETIC trail graph; networkx cross-check |
| | `planner/tests/test_astar.py` | 7 | SYNTHETIC |
| perception (39) | `perception/tests/test_pi_source.py` | 16 | MOCKED Pi sender |
| | `perception/tests/test_sightings.py` | 13 | SYNTHETIC frames; 1 test needs cached Faster R-CNN weights |
| | `perception/tests/test_orientation.py` | 7 | SYNTHETIC |
| | `perception/tests/test_live_camera.py` | 3 | SYNTHETIC (blank images) |
| dashboard (70) | `dashboard/tests/test_range_panel.py` | 54 | SIMULATED fixtures; 6 tests need private fixtures |
| | `dashboard/tests/test_dashboard.py` | 16 | SYNTHETIC observations; Git index scan |
| e2e (31) | `tests/e2e/test_pi_camera_integration.py` | 21 | MOCKED upside-down Pi sender → real `live_camera` → real dashboard |
| | `tests/e2e/test_live_camera_integration.py` | 10 | MOCKED camera → bridge → real HTTP server |
| rover (284) | `rover/tests/test_grove_adapter.py` | 82 | MOCKED ranging client, SIMULATED |
| | `rover/tests/test_bridge.py` | 63 | MOCKED serial + executable firmware model (`rover/tests/bridge_model.py`) |
| | `rover/tests/test_issue9_fail_closed.py` | 40 | MOCKED driver |
| | `rover/tests/test_distances.py` | 21 | SIMULATED |
| | `rover/tests/test_supervisor.py` | 21 | MOCKED driver |
| | `rover/tests/test_scanning.py` | 16 | SIMULATED |
| | `rover/tests/test_ranging_contract.py` | 11 | real `ranging` code, SIMULATED data |
| | `rover/tests/test_scenarios.py` | 10 | SIMULATED scenarios A–H |
| | `rover/tests/test_protocol_hardware.py` | 10 | `RecordingTransport` (no device) |
| | `rover/tests/test_observations.py` | 6 | SYNTHETIC |
| | `rover/tests/test_status_contract.py` | 4 | SIMULATED |
| camera_mapping (97) | `camera_mapping/tests/test_tracking_map_assess.py` | 36 | SYNTHETIC detections |
| | `camera_mapping/tests/test_geometry_distance.py` | 35 | SYNTHETIC geometry |
| | `camera_mapping/tests/test_advisory_rover_dashboard.py` | 26 | SYNTHETIC; 1 test uses a RECORDED Pi frame when present |
| **default total** | | **540** | |
| lidar (124) | `lidar/tests/test_processing_scenarios.py` | 46 | SIMULATED scans |
| | `lidar/tests/test_footprint_corridor.py` | 29 | SIMULATED |
| | `lidar/tests/test_protocol_driver.py` | 27 | MOCKED serial device |
| | `lidar/tests/test_contracts_compat.py` | 22 | SIMULATED; AST import scan |
| ranging (126) | `ranging/tests/test_ranging.py` | 126 | SIMULATED driver; fake gpiod |
| qwen_advisory (23) | `qwen_advisory/tests/test_lidar_contract.py` | 23 | 8 SIMULATED cases; fake model callables |
| team15_starter (5) | `team15_starter/tests/test_fleet.py` | 5 | SIMULATED fleet |
| **all pytest** | | **818** | |
| script | `team15_starter/tests/test_link.py` (run as `python tests/test_link.py`) | 30 `ok` checks | Python ↔ C (compiled `xcheck.c`) byte-level protocol |

`team15_starter/tests/test_link.py` is a plain script with `check()` calls and no `test_` functions, so pytest collects nothing from it. Run it directly. On this machine it printed 30 `ok` lines and `ALL LINK TESTS PASSED` (8 Nov 2026). It compiles a C cross-check, and it skips that half if no C compiler is found.

## 3. The five CI workflows

All five run on `ubuntu-latest`. None installs torch, pyserial or libgpiod. None has access to a camera, a Pi or the network beyond pip.

| Workflow file (display name) | Triggers | Python | Installs | Runs |
|---|---|---|---|---|
| `.github/workflows/ci.yml` (`ci`) | every push and PR | 3.11 | `pip install -r requirements.txt` (pinned) | (1) `python -m planner.route A G`, then asserts `length_m == 60` and path `A…G`; (2) `pytest -q` (default suite) |
| `.github/workflows/perception.yml` (`perception`) | every push and PR | 3.13 | `opencv-python-headless>=4.8,<5`, numpy, pytest (unpinned within range) | `python -B -m pytest -q -p no:cacheprovider perception/tests` |
| `.github/workflows/lidar.yml` (`lidar`) | push/PR touching `lidar/**`, `rover/**`, `core/range_view.py`, `dashboard/range_source.py`, `ranging/**`, or the workflow | 3.11 | `pytest==8.3.4 networkx==3.4.2` | `pytest -q -p no:cacheprovider lidar/tests`; then asserts that `python -m lidar check-config --config lidar/configs/c1_pi5.UNVERIFIED.json --hardware` **fails**, and that `python -m lidar scan-once --config …UNVERIFIED.json` **fails** |
| `.github/workflows/ranging.yml` (`ranging`) | push/PR touching `ranging/**` or the workflow | 3.11 | `pytest==8.3.4` | `python -m pytest -q ranging/tests`; then asserts that `python -m ranging check-config --config ranging/configs/pi5_gpio5.UNVERIFIED.json --hardware` **fails** |
| `.github/workflows/qwen.yml` (`qwen-advisory`) | push/PR touching `qwen_advisory/**`, `docs/qwen/**`, or the workflow | 3.11 | `pytest==8.3.4` | `python -B -m pytest -q -p no:cacheprovider qwen_advisory/tests` |

Things worth knowing:

- **`perception/tests` runs twice**: once in `ci` (Python 3.11, pinned OpenCV 4.13.0.92) and once in `perception` (Python 3.13, OpenCV 4.x). That is deliberate. It covers the Python version on the bench Mac and the version pinned in `requirements.txt`.
- **The gate steps are negative tests.** They pass only if the hardware command *refuses*. They show that the gate fires on the shipped unverified configs. They do not show that the gate would accept a correctly verified one.
- **`team15_starter/tests` is in no workflow.** Its 5 tests and the link script have only been run locally. The PR #17 review comment reports 5 passed, and this audit re-ran them.
- **Path filters mean not every workflow runs on every commit.** On the final merge commit `d1b607a` only `ci` and `perception` ran, because that merge changed only `team15_starter/`. The `lidar`, `ranging` and `qwen-advisory` workflows last ran on `159c678`, the PR #17 head merged into it, and all three passed there. Since `d1b607a` adds no change under their paths, those results carry over, but strictly they ran on `159c678`.
- **Display-name history.** Before PR #10, `perception.yml` was also named `ci`, so GitHub listed two workflows called "ci" on `main`. Ten `perception.yml` runs carry the old name.

### 3.1 Results on the final revisions

Read from the GitHub Actions logs on 8 Nov 2026:

| Run id | Workflow | Commit | Event | Result |
|---|---|---|---|---|
| 42479330397 | ci | `d1b607a` | push | 532 passed, **8 skipped** |
| 42479330362 | perception | `d1b607a` | push | 38 passed, 1 skipped |
| 42479254481 | ci | `159c678` | push | 532 passed, 8 skipped |
| 42479254584 | perception | `159c678` | push | 38 passed, 1 skipped |
| 42479254463 | lidar | `159c678` | push | 124 passed (+ 2 gate refusals) |
| 42479254445 | ranging | `159c678` | push | 126 passed (+ 1 gate refusal) |
| 42479254482 | qwen-advisory | `159c678` | push | 23 passed |

### 3.2 Why CI skips 8 tests that pass locally

| Tests | Skip condition | Why CI lacks it |
|---|---|---|
| 6 in `dashboard/tests/test_range_panel.py` (marked `@need`) | the robotics fixtures `sim_range_series_approach.json`, `sim_range_snapshots.json`, `sim_robot_status.json` are absent from `$TEAM15_ROBOT_FIXTURES` (default: the private robotics workspace) | the fixtures are SIMULATED but live outside the repo |
| `perception/tests/test_sightings.py::test_person_detector_blank_frames` | no cached `fasterrcnn_mobilenet_v3_large_fpn` weights in `~/.cache/torch/hub/checkpoints`, or no torch | CI installs OpenCV only |
| `camera_mapping/tests/test_advisory_rover_dashboard.py::test_recorded_pi_frame_person_detection_pipeline` | no recorded Pi frames under `~/Team15_evidence/camera_pi_validation/`, or no torch | private evidence frames are never committed |

The `perception` workflow skips only the Faster R-CNN test (38 + 1 = 39). Locally, with torch 2.12, both weight files and the private fixtures present, **all 540 default tests run and pass**. The local run is therefore stronger evidence for the three tests above. CI is stronger evidence that the suite does not depend on the bench Mac. This is the most important reproducibility caveat: **the recorded-frame person-detection regression has never run in CI.**

## 4. Local full run at `d1b607a`

Full report: [CI-002](experiments/reports/CI-002-local-test-suite-d1b607a.md). Environment: docs worktree at `d1b607a` (clean apart from untracked docs), macOS 26.6.1 arm64, Anaconda Python 3.13.5, pytest 8.3.4, numpy 2.1.3, OpenCV 4.13.0, fastapi 0.115.6, starlette 0.41.3, uvicorn 0.34.0, httpx 0.28.1, networkx 3.4.2, torch 2.12.0, torchvision 0.27.0. These match the pins in `requirements.txt`, plus torch.

| Command | Result | Wall time |
|---|---|---|
| `python3 -m pytest -q -p no:cacheprovider` | **540 passed**, 2 warnings (websockets deprecation from uvicorn) | 12.75 s |
| `python3 -B -m pytest -q -p no:cacheprovider lidar/tests` | **124 passed** | 1.76 s |
| `python3 -B -m pytest -q -p no:cacheprovider ranging/tests` | **126 passed** | 3.41 s |
| `python3 -B -m pytest -q -p no:cacheprovider qwen_advisory/tests` | **23 passed** | 0.23 s |
| `python3 -B -m pytest -q -p no:cacheprovider team15_starter/tests` | **5 passed** | 2.83 s |
| `cd team15_starter && python3 -B tests/test_link.py` | 30 `ok`, `ALL LINK TESTS PASSED` | — |
| `python3 -m planner.route A G` | `{"status": "OK", "path": ["A",…,"G"], "length_m": 60, …}` | — |
| `python3 -m lidar check-config --config lidar/configs/c1_pi5.UNVERIFIED.json --hardware` | refused, exit 2 | — |
| `python3 -m lidar scan-once --config lidar/configs/c1_pi5.UNVERIFIED.json` | refused, exit 3 (no device was attached) | — |
| `python3 -m ranging check-config --config ranging/configs/pi5_gpio5.UNVERIFIED.json --hardware` | refused, exit 2 | — |

These numbers agree with the brief's reference counts (540 / 124 / 126 / 23 / 5) and with the PR #17 review comment ("repo suite 540 passed"). The CI default count of 532 + 8 skipped = 540 is the same suite.

## 5. CI history

Full analysis: [CI-001](experiments/reports/CI-001-ci-regression-history.md). From `gh run list --limit 200` and the Actions API on 8 Nov 2026:

- **184 workflow runs** between 2026-11-07 18:59 UTC and 2026-11-08 12:14 UTC: 105 on `push`, 79 on `pull_request`.
- **181 succeeded and 3 failed**, all in `ci.yml`. By workflow: `ci.yml` 84 runs (81 ✓, 3 ✗), `perception.yml` 63 (all ✓), `ranging.yml` 19, `lidar.yml` 14, `qwen.yml` 4.

| # | Run | When (UTC) | Branch / commit | Failure | Root cause | Fix |
|---|---|---|---|---|---|---|
| 1–2 | 42403983799 (push), 42404031282 (PR) | 11-07 18:59–19:00 | `t2/dashboard-a-to-g` @ `3797530` | `perception/tests/test_live_camera.py::test_blank_image_no_person`: `AttributeError: module 'cv2' has no attribute 'HOGDescriptor'` (1 failed, 30 passed) | `requirements.txt` was unpinned. pip resolved `opencv-python-headless 5.0.0.93`, and OpenCV 5 moved `HOGDescriptor` out of the main package | `a36a658` (19:00 UTC) pinned every requirement to the bench Mac's versions, including `opencv-python-headless==4.13.0.92`. The next runs on `a36a658` passed. `perception.yml` later used the range `>=4.8,<5` with a comment explaining why |
| 3 | 42478121738 (PR) | 11-08 11:59 | `GavinPrescott-sim-roles` @ `eddef53` | `dashboard/tests/test_dashboard.py::test_no_photos_tracked_in_git`: `['team15_star…r-shadow.png'] != []` (1 failed, 332 passed, 7 skipped) | PR #17 vendored five Leaflet UI icons (PNG) for the offline fleet map, and the privacy test rejects any tracked image | `159c678` (12:13 UTC) exempts exactly those five paths in `VENDORED_ICONS`; any other image still fails. It also untracked a 10 MB generated `mujoco_search.gif` |

Neither failure was a logic regression in robot code. Both were **environment or repository-hygiene failures caught by CI**, and that is CI doing its job. The HOG failure is a textbook case of why dependencies need pins: a major-version bump of a transitive dependency silently removed an API.

### 5.1 How the test count grew

These counts are **as reported in each PR description** (local runs, usually macOS and Python 3.13). They were not re-run for this document, except where marked.

| When (UTC) | PR / commit | Reported count |
|---|---|---|
| 11-07 18:50 | #2 `77a3979` | planner 12 passed |
| 11-07 18:50 | #3 (first version) | perception 16 passed |
| 11-07 ~22:30 | #5 `901c7e2` | 89 passed locally; CI 88 passed + 1 skipped |
| 11-08 ~01:30 | #5 `7624788` | 143 passed |
| 11-08 ~01:30 | #3 `8f351fe` | perception 39 passed; CI 38 + 1 skipped |
| 11-07 23:46+ | #7 | ranging 126 passed |
| 11-08 ~01:20 | #8 `dac82f4` | default 277 (rover 181); 403 across packages |
| 11-08 03:53+ | #11 | lidar 92 (later 124), default 340, total 558 |
| 11-08 05:55 | #12 | qwen 23 |
| 11-08 10:28 | #14 | rover 221, default 380 |
| 11-08 10:32 | #15 | rover 284, default 443 |
| 11-08 11:31 | #16 (branch without #14/#15) | default 437 (camera_mapping 97) |
| 11-08 12:13 | #17 review / `d1b607a` | **default 540** (re-run here: 540) |

## 6. Hardware-gated and hardware-adjacent tests

No automated test opens a GPIO line, a serial port, an I²C bus or a camera:

- **Ranging:** `test_gpiod_driver_refuses_unverified_wiring_before_importing_gpiod` and `test_cli_requires_hardware_flag_and_verified_config` check the electrical gate. The `test_gpiod_*` tests drive `GpiodDriver` against a fake `gpiod` module (MOCKED).
- **LiDAR:** the driver tests use `MockLidarDevice` (`lidar/transport.py`). `test_lidar_package_imports_no_actuation_or_gpio` parses the package's AST.
- **Rover:** `RoverCAdapter` refuses to construct without a filled `HardwareVerification`. Protocol tests use `RecordingTransport`. The bridge tests run an executable model of the firmware (`rover/tests/bridge_model.py`), not the firmware.
- **Camera:** the Pi source tests use a fake sender process. The e2e tests feed a deliberately **upside-down** fake Pi stream, to prove the frame is rotated exactly once.

Real-hardware *procedures* exist as runbooks, not tests: [docs/rover/BENCH_RUNBOOK](rover/BENCH_RUNBOOK.md), [LIDAR_C1_STATIONARY_SCAN_PROCEDURE](lidar/LIDAR_C1_STATIONARY_SCAN_PROCEDURE.md), [ranging/HARDWARE_VALIDATION](../ranging/HARDWARE_VALIDATION.md), [camera_mapping CALIBRATION](camera_mapping/CALIBRATION.md). None of their measurement steps had been completed at `d1b607a`. The only real-sensor runs of a ranging command, the Grove `diagnose` runs on 8 Nov, returned 0/50 valid. See [14](14_GROVE_ULTRASONIC.md).

Outside this repository, the robotics workspace (`$ROBOT_WORKSPACE/TEST_REPORT.md`) records a separate stdlib simulation suite run **on the Pi 5**: 30 repetitions × 90 tests = 2,700 passed on 7 Nov at 19:50 ET, with a hardware-access guard and `throttled=0x0` throughout. That is SIMULATED software executed on REAL HARDWARE. It is evidence that the Pi stays stable under light CPU load, not evidence about sensors or motors, and that code is not on `main`.

## 7. What the tests do not prove

1. **Physical perception accuracy.** No test compares a camera distance with a tape measure. `camera_mapping.calibrate report` is unit-tested on SYNTHETIC samples only ([EVALUATION §1](camera_mapping/EVALUATION.md)). The detector's real false-alarm rate is known only from a handful of bench runs (PR #3), and the 60 s empty-scene test never passed.
2. **Motor safety.** The supervisor, watchdog and bridge tests show that the *software* stops on a fault. They cannot show how far the real RoverC-Pro travels after a stop command, whether the StickC firmware compiles, or whether the 250 ms watchdog holds on the real MCU. These are bench-runbook items, all **NOT TESTED**.
3. **Sensor drivers on real devices.** The Grove driver is tested against a fake `gpiod`. The real sensor produced no echoes. The LiDAR codec is tested against a mock that implements the *documented* protocol. Whether the C1 answers the legacy SCAN at 460800 baud is **unverified** (PR #11).
4. **Model quality in the field.** The Qwen tests check schema, guard and fallback, not answer quality. The 218/230 benchmark is SYNTHETIC and in-distribution ([08](08_QWEN_MODEL.md)).
5. **Timing under load.** Latency numbers come from short live runs ([EVALUATION §3](camera_mapping/EVALUATION.md)), not from tests. Tests use injected clocks.
6. **Network and power failure modes on the Pi.** The Pi dropped off Tailscale several times, cause unknown, and no test models it.
7. **That CI and local runs cover the same code.** CI skips the 8 tests that need private data or torch (§3.2).

## 8. Benchmarks

Consolidated numbers, with conditions and labels, are in [experiments/BENCHMARK_RESULTS.md](experiments/BENCHMARK_RESULTS.md). The test-adjacent ones are:

| Benchmark | Command | Label | Where reported |
|---|---|---|---|
| Camera pipeline latency (detector, mapping, capture→state) | live run of `camera_mapping.live --jsonl …` | REAL HARDWARE | [EVALUATION §3](camera_mapping/EVALUATION.md) |
| LiDAR scan-processing latency | `python3 -m lidar bench -n N` | SIMULATED scans (processing time only) | [LIDAR_C1_TEST_REPORT](lidar/LIDAR_C1_TEST_REPORT.md) |
| Rover scenarios A–H | `python3 -m rover.simrun <A-H>` | SIMULATED | [18](18_SIMULATION.md) |
| Drone-fleet search comparison | `team15_starter/fleet_eval.py`, `team15_starter/bench/sarenv_bench.py` | SIMULATED | `team15_starter/results/*.csv`, [18](18_SIMULATION.md) |
| Test-suite wall time | `pytest -q` | — | §4 (12.75 s locally; 11.7–17.5 s in CI) |

## 9. How to reproduce

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt                      # CI's pinned set
python3 -m pytest -q -p no:cacheprovider             # default suite (540; 8 skip without private data/torch)
for d in lidar/tests ranging/tests qwen_advisory/tests team15_starter/tests; do
  python3 -B -m pytest -q -p no:cacheprovider "$d"
done
(cd team15_starter && python3 -B tests/test_link.py)
python3 -m planner.route A G
```

To run the 8 data-dependent tests as well, install torch and torchvision, let the Faster R-CNN weights download once into `~/.cache/torch`, and point `TEAM15_ROBOT_FIXTURES` at the robotics fixtures. Those fixtures and the recorded Pi frames are private; see the [docs index](README.md#private-evidence-stores).

## 10. How to extend

- Put new tests for the default suite under one of the six `testpaths`. A new top-level package should either join `testpaths` (and so `ci.yml`) or get its own path-filtered workflow modelled on `ranging.yml`.
- **Add `team15_starter/tests` to a workflow.** It is the only suite that CI never runs.
- For any new hardware path, add (a) a gate test showing that an unverified config is refused, (b) a CI step that runs the real CLI against the shipped `*.UNVERIFIED.json` and expects failure, and (c) the device module to the static import scans.
- Keep data-dependent tests skippable, but give each a reason string naming the missing artefact, as the three in §3.2 do.
