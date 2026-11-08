# LDR-SIM-01 … LDR-SIM-05: LiDAR simulation scenario suite, test suite and processing benchmark

**Label: SIMULATED + MOCKED** (`MockLidarDevice` byte stream) · **Status: COMPLETE**
Back to: [15 RPLIDAR C1](../../15_RPLIDAR_C1.md) · [LiDAR test report](../../lidar/LIDAR_C1_TEST_REPORT.md) · [18 Simulation](../../18_SIMULATION.md)

## In one paragraph (plain language)

No real LiDAR scan exists, so the LiDAR software was tested against a **virtual room**. A small 2D ray-caster shoots 500 virtual laser beams per revolution at walls, boxes, poles, a doorway, glass and a mirror, and records what a C1 might report. Twenty-three scenarios cover normal cases (an obstacle ahead, an obstacle to the left), tricky ones (a pole just at the robot's wheel edge, a door narrower than the robot) and failures (stale timestamps, a partial scan, a sensor mounted the wrong way). A fake serial device also replays the scans byte by byte, to test disconnects, timeouts and corrupted packets. All 124 tests pass. This shows the code makes the intended decision in every one of these situations. It does **not** show that a real C1 produces data that looks like this.

## 1. Objective

Verify the codec, the driver state machine, the sector and corridor logic, the staleness rules and every adapter contract, with deterministic inputs.

## 2. Generator and data

- `lidar/simulation.py`: deterministic with `seed = 15`. `POINTS_PER_REV = 500` (≈ 5 kHz / 10 Hz, datasheet typical, not measured). `SCAN_PERIOD_NS = 100 ms`.
- **Mount:** `SIM_MOUNT` has the sensor's 0 mark facing the robot **rear** (offset 180°, CW). A 2 cm mast at robot (−0.10, +0.10) m, bearing 135°, range 0.141 m, serves as the orientation fiducial inside a signed-off occlusion window (sensor 38–52°). All "verified_by" fields read "SIMULATION (not a person)".
- **Footprint:** `SIM_FOOTPRINT`: width 0.20 m (SYNTHETIC placeholder, from `rover/simrun.py`), margin 0.05, lookahead 1.0, sensor 0.10 m behind the bumper.
- **Surface kinds:** `solid`, `glass` (no return), `mirror` (spurious long return, weak), `dark` (low quality).
- **Fixtures:** `lidar/fixtures/*.json`. 23 scenario files plus `index.json` and `dashboard_range_series_approach.json`, written by `python -m lidar export-fixtures`. **76 frames, 37,038 points in total**; 832 KB; every file labelled `SIMULATED`. `index.json` SHA-256 `7bd67e3683d50402a21d5a4ac613072e598d25d4f5dd7f34a02fb77305e97d24`.
- **Byte-level scenarios** (driver tests only, no fixture): `13_serial_disconnect`, `14_device_timeout`, `19_corrupted_packets`.

## 3. Runs (separate rows)

| ID | Date | Commit | Environment | Result |
|---|---|---|---|---|
| LDR-SIM-02 | 2026-11-08 ~04:00 UTC | `9041c05` (first round) | Mac, Python 3.13.5 | 92 LiDAR tests; with default 340 + ranging 126 = 558 passed; coverage 88 %; CI 6/6 (`$ROBOT_WORKSPACE/IMPLEMENTATION_JOURNAL.md`) |
| LDR-SIM-01 | 2026-11-08 | branch after the footprint round (`9027320`/`7e61595`) | Mac, Python 3.13.5, pytest 8.3.4 | **124** LiDAR + 340 + 126 = **590 passed**, 0 failed, 0 skipped; coverage **89 %** of 1828 statements (`docs/lidar/LIDAR_C1_TEST_REPORT.md`) |
| LDR-SIM-03 | 2026-11-08 (this audit) | `d1b607a` (`lidar/` identical to `7e61595`) | macOS, Python 3.13.5, pytest 8.3.4 | `python3 -m pytest -q -p no:cacheprovider lidar/tests` → **124 passed in 2.03 s** |
| LDR-SIM-04 | fixtures as committed | `7e61595` | — | 23 scenario fixtures re-evaluated by `test_processing_scenarios` against their recorded expectations: all match (inside the 124) |
| LDR-SIM-05a | 2026-11-08 (test report) | branch | Mac | `bench`: p50 **1.13 ms**, p95 **1.18 ms** per 500-point scan, corridor included (was 0.58 ms before the corridor) |
| LDR-SIM-05b | 2026-11-08 (this audit) | `d1b607a` | Mac | `python3 -B -m lidar bench -n 50`: p50 **1.159 ms**, p95 1.265 ms, max 1.288 ms |

CI: the `lidar` workflow (`.github/workflows/lidar.yml`, Python 3.11, pytest 8.3.4 + networkx 3.4.2) runs `lidar/tests` and checks that the gate and `scan-once` refuse. Latest runs succeeded (for example 42479102768 on `main`, 2026-11-08 12:11 UTC).

## 4. Scenario expectations (last frame of each committed fixture; from `frames[-1].expected`)

| Scenario | Frames | FRONT | FRONT_LEFT | FRONT_RIGHT | `forward_motion_allowed` | Completion |
|---|---|---|---|---|---|---|
| `00_clear_room_control` | 3 | CLEAR | CLEAR | CLEAR | **true** | COMPLETE |
| `01_empty_incomplete_returns` | 3 | UNKNOWN | UNKNOWN | UNKNOWN | false | COMPLETE |
| `02_obstacle_ahead` | 3 | BLOCKED | BLOCKED | BLOCKED | false | COMPLETE |
| `03_obstacle_behind` | 3 | CLEAR | CLEAR | CLEAR | **true** | COMPLETE |
| `04_obstacle_left` | 3 | CLEAR | BLOCKED | CLEAR | false | COMPLETE |
| `05_multiple_obstacles` | 3 | BLOCKED | BLOCKED | BLOCKED | false | COMPLETE |
| `06_narrow_doorway` | 3 | CLEAR | CLEAR | CLEAR | **true** | COMPLETE |
| `07_wall_one_side` | 3 | CAUTION | CLEAR | BLOCKED | false | COMPLETE |
| `08_obstacle_approaching` | 6 | BLOCKED | BLOCKED | BLOCKED | false | COMPLETE |
| `09_invalid_range_values` | 1 | UNKNOWN | UNKNOWN | UNKNOWN | false | COMPLETE |
| `10_missing_angular_sectors` | 3 | UNKNOWN | UNKNOWN | UNKNOWN | false | PARTIAL |
| `11_partial_scan` | 1 | UNKNOWN | UNKNOWN | UNKNOWN | false | PARTIAL |
| `12_stale_timestamps` | 3 | UNKNOWN | UNKNOWN | UNKNOWN | false | COMPLETE |
| `15_incorrect_orientation` | 3 | UNKNOWN | UNKNOWN | UNKNOWN | false | COMPLETE |
| `16_unexpected_scan_frequency` | 4 | CLEAR | CLEAR | CLEAR | false (4.0 Hz, outside 7–13 Hz; scan 0.27 s old > 0.20 s) | COMPLETE |
| `17_reflective_transparent` | 3 | UNKNOWN | CLEAR | UNKNOWN | false | COMPLETE |
| `18_moving_robot_stationary_obstacle` | 8 | CLEAR | CLEAR | CLEAR | **true** | COMPLETE |
| `20_unsafe_forward_clearance` | 3 | UNKNOWN | BLOCKED | UNKNOWN | false | COMPLETE |
| `21_edge_obstacle_left` | 3 | CAUTION | CLEAR | CLEAR | false (corridor BLOCKED: 0.29 m ahead, +0.14 m) | COMPLETE |
| `22_edge_obstacle_right` | 3 | CAUTION | CLEAR | CLEAR | false (corridor BLOCKED: 0.29 m ahead, −0.15 m) | COMPLETE |
| `23_pole_just_outside_corridor` | 3 | CLEAR | CAUTION | CLEAR | **true** | COMPLETE |
| `24_door_narrower_than_robot` | 5 | CAUTION | CAUTION | CAUTION | false | COMPLETE |
| `25_mirror_across_corridor` | 3 | UNKNOWN | CLEAR | CLEAR | false | COMPLETE |

Five scenarios allow motion (00, 03, 06, 18, 23), and only in simulation (`source_mode SIMULATED`). With real-device data (`HARDWARE_UNVERIFIED`) every row would read `false`.

Corridor checks (`test_footprint_corridor.py`, 29 tests, from the test report):
- edge poles at ±0.14 m and 0.30 m ahead → corridor BLOCKED, though the FRONT wedge says CAUTION;
- pole at 0.22 m off centre → no over-block;
- corridor edges ±0.149 m BLOCKED / ±0.161 m CLEAR;
- lateral-offset transform;
- bumper inside the blind zone → UNKNOWN;
- one missing near-zone ray → UNKNOWN;
- far-zone gap > 2° → UNKNOWN;
- mirror across the corridor → UNKNOWN;
- unsigned occlusion → UNKNOWN;
- fiducial catches a wrong offset, CW/CCW error, a 12° rotation and a missing mast.

## 5. Metrics and why

Exact sector, corridor and motion verdicts per scenario. The logic is deterministic, so the right metric is agreement with the specified rule, not an error rate. The latency percentiles show whether processing fits inside the 0.20 s motion age budget, roughly 100 ms per revolution plus processing.

## 6. What this proves / does NOT prove

**Proves (simulation):**
- the frame conversions are correct, including a deliberately reversed mount;
- missing, weak, occluded or stale data never becomes CLEAR;
- edge obstacles are caught by the corridor;
- real-device data never authorizes motion in this PR;
- the contracts hold (rover rejects `rplidar-c1`; the dashboard never shows CLEAR from the compatibility snapshot; Qwen gets no authority);
- processing takes about 1.2 ms on the Mac.

**Does NOT prove:**
- that the C1 answers legacy SCAN;
- real quality and coverage distributions;
- that real mirrors and glass are weak, since the simulator assumes they are (quality 12 < 20);
- the real scan rate, points per revolution and Pi latency;
- any physical distance or bearing accuracy.

## 7. Limitations / next time

The simulator is a perfect 2D world: no beam divergence, no multipath, no motion blur within a revolution. All thresholds are placeholders. Next: replay **recorded** C1 scans (RECORDED HARDWARE) through the same tests once Stage C produces any.
