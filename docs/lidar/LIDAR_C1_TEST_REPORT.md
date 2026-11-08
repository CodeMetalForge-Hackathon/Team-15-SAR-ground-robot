# LiDAR test report

**Everything below is SIMULATION or mock-serial testing. No physical LiDAR test has been done (hardware-tested: none).** Run on the bench Mac with Python 3.13.5 and pytest 8.3.4, on branch `feature/rplidar-c1-ground-robot` based on main 06a69b9.

| Suite | Command | Passed | Failed | Skipped |
|---|---|---|---|---|
| LiDAR (new) | `python -m pytest lidar/tests` | **92** | 0 | 0 |
| Default (planner, perception, dashboard, e2e, rover) | `python -m pytest` | 340 | 0 | 0 |
| Ranging (Grove) | `python -m pytest ranging/tests` | 126 | 0 | 0 |
| **Total** | | **558** | **0** | **0** |

The pre-existing **466** (340 + 126) is unchanged: no Grove test was modified, moved or deleted. CI: the new workflow `lidar` (job `lidar-tests`, Python 3.11, pytest + networkx only) runs the LiDAR suite and checks that the gate refuses the unverified config and that `scan-once` refuses without approval.

## New coverage (`coverage 7.6.10`, `lidar/` excluding tests): **88 %** of 1579 statements

| Module | Cover | Not covered |
|---|---|---|
| processing 98 %, simulation 99 %, panel 97 %, server 97 %, tracking 97 % | | minor branches |
| driver 90 %, protocol 92 %, transport 92 %, scan 93 %, adapters 94 %, config 90 % | | `SerialTransport` methods (hardware only, `pragma: no cover`), a few error branches |
| cli 38 %, discovery 57 % | | `bench`/`export`/`replay` printing paths (run manually), sysfs VID:PID lookup (Linux only) |

## What the tests establish

| Area | Tests (file) |
|---|---|
| Protocol: node roundtrip, q2 mm → m and q6 → deg conversion, check bits S/!S and C, descriptor/info/health parsing, legacy-only requests | test_protocol_driver |
| Driver: connect (STOP first), GET_INFO/HEALTH, scan assembly at start flags, mid-revolution join, junk before the descriptor, cleanup (STOP + close) on normal exit and on exception, idempotent disconnect, reconnect | test_protocol_driver |
| 13 serial disconnect: `LidarDisconnected`, port closed, partial revolution dropped | test_protocol_driver |
| 14 device timeout: `LidarTimeout`, nothing half-built kept | test_protocol_driver |
| 19 corrupted packets: resync; > 5 % corrupt → PARTIAL; light corruption tolerated | test_protocol_driver |
| Health error and model mismatch refuse scanning; the hardware gate refuses before any I/O; no implicit real serial; HARDWARE_VERIFIED cannot be set | test_protocol_driver |
| Angular conventions: sensor CW → robot CCW with offset; sector boundaries at ±22.5°; no default offset; unverified alignment → all UNKNOWN | test_processing_scenarios |
| Quality threshold, min/max range, self-occlusion | test_processing_scenarios |
| Timestamps: 0.20 s motion and 0.5 s display limits, age from capture **start**, future timestamp = clock fault, re-assessment after disconnect, health not GOOD, two-scan confirmation | test_processing_scenarios |
| Scenarios 00–12, 15–18, 20 (expected sector states and motion verdict); determinism; SIMULATED labels; no person distance anywhere | test_processing_scenarios |
| Committed fixtures re-evaluate to their recorded expectations; forged fixture labels are refused | test_processing_scenarios |
| Rover: LiDAR fields rejected by `from_rover_fields` → UNKNOWN; `PiRobotIO` with a LiDAR reader → UNKNOWN; stale/disconnected → ERROR; NO_ECHO never OK; freshness constants equal to rover's 0.20 s | test_contracts_compat |
| Dashboard: the existing card renders the compat snapshot as SIMULATED, BLOCKED or UNKNOWN, never CLEAR; a forged LIVE-HW claim is not HARDWARE; `RangeSource` reads the committed fixture | test_contracts_compat |
| Grove spoofing path: `GroveRangeIO`/`RangeClient` pointed at a LiDAR snapshot never allows motion; the Grove snapshot path is refused | test_contracts_compat |
| Panel: badges, fixture spoofing, greyed stale/disconnected, no "path clear"/"motion allowed"/person text, sensor-frame warning | test_contracts_compat |
| Qwen field: NOT_ESTABLISHED, null person distance, no authorization flags; stale → UNKNOWN | test_contracts_compat |
| Safety: `lidar/` imports no GPIO/motor/servo/rover-actuation module (AST check); `scan-once` and `check-config --hardware` refuse; discovery never opens a port | test_contracts_compat |
| Replay server endpoints (port 0) | test_contracts_compat |

## Safety behaviour on missing data (all simulation-tested)

| Condition | Sector result | forward_motion_allowed | Rover adapter |
|---|---|---|---|
| No returns / glass / dark surface / < 60 % coverage | UNKNOWN | false | NO_ECHO or ERROR |
| Partial or interrupted scan | UNKNOWN (BLOCKED kept) | false | ERROR or OK + not allowed |
| Stale > 0.20 s | displayable | false | ERROR |
| Stale > 0.5 s or a future timestamp | all UNKNOWN | false | ERROR |
| Disconnected / timeout / health error | UNKNOWN | false | ERROR |
| Alignment not verified | all UNKNOWN | false | NO_ECHO or ERROR |
| Scan rate outside 7–13 Hz, or unknown | unchanged | false | — |
| Real device (HARDWARE_UNVERIFIED) | computed | **always false** | rejected by rover (source) |

## Timing assumptions (not measured on hardware)

The revolution takes ≈ 100 ms at the 10 Hz datasheet typical. Processing on the Mac measured p50 0.58 ms / p95 0.61 ms for 500 points (SIMULATED). The age at assessment is therefore ≈ 0.10–0.13 s, which fits the 0.20 s motion limit with ≈ 70–100 ms to spare. The real Pi 5 latency is **unmeasured**; Stage C `scan-once` reports it.

## Known limitations (documented, not hidden)

* A mirror produces phantom far returns, which read as CLEAR for that sector (scenario 17). A single scan cannot distinguish them. Calibration and operator awareness are required.
* Sector minimum range does not model the robot's width. A doorway narrower than the robot inside FRONT at > 0.75 m reads CLEAR. Corridor-width checking is future work, before any Stage E motion.
* Thresholds (0.35/0.75 m, quality 10, coverage 60 %, 7–13 Hz) are placeholders.
