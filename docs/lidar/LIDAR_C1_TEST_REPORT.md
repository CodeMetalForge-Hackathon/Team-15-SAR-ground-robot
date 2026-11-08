# LiDAR test report

**Everything below is SIMULATION or mock-serial testing. No physical LiDAR test has been done (hardware-tested: none).** Run on the bench Mac with Python 3.13.5 and pytest 8.3.4, on branch `feature/rplidar-c1-ground-robot` based on main 06a69b9.

| Suite | Command | Passed | Failed | Skipped |
|---|---|---|---|---|
| LiDAR (new) | `python -m pytest lidar/tests` | **124** | 0 | 0 |
| Default (planner, perception, dashboard, e2e, rover) | `python -m pytest` | 340 | 0 | 0 |
| Ranging (Grove) | `python -m pytest ranging/tests` | 126 | 0 | 0 |
| **Total** | | **590** | **0** | **0** |

Updated 2026-11-08 after the footprint-clearance round. Before that it was 92 LiDAR / 558 total.

The pre-existing **466** (340 + 126) is unchanged: no Grove test was modified, moved or deleted. CI: the new workflow `lidar` (job `lidar-tests`, Python 3.11, pytest + networkx only) runs the LiDAR suite and checks that the gate refuses the unverified config and that `scan-once` refuses without approval.

## New coverage (`coverage 7.6.10`, `lidar/` excluding tests): **89 %** of 1828 statements (footprint 96 %, processing 98 %, adapters 94 %)

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

## Footprint corridor tests (`test_footprint_corridor.py`, 29 tests)

* **The user's case.** In scenarios 21 and 22 the centreline is clear: the FRONT wedge alone says CAUTION, which the old rule would allow. A pole 0.30 m ahead of the bumper and 0.14 m left or right of centre gives corridor **BLOCKED**, and motion is denied.
* A pole 0.22 m off centre (just outside the corridor) does not over-block (scenario 23).
* Corridor edges: ±0.149 m → BLOCKED, ±0.161 m → CLEAR, centreline → BLOCKED.
* **Off-centre mount transform.** A pole outside ±0.15 m in sensor axes is inside the corridor once the 0.10 m lateral offset is applied, and the reverse holds on the other side.
* `sensor_to_front_m` shifts the bumper reference. A return inside the robot's own footprint gives BLOCKED. A bumper inside the min-range blind zone gives UNKNOWN.
* **Unknown robot dimensions.** A missing width, front distance or sign-off gives UNKNOWN and no motion. A lookahead below the rover's required clearance is rejected at config time.
* **Incomplete scans.** A single missing ray in the near zone gives UNKNOWN (100 % required). A far-zone contiguous gap over 2° gives UNKNOWN.
* **Reflective surfaces.** Weak returns never count as clear evidence but do count as obstacles. A mirror across the corridor gives UNKNOWN (scenario 25). The LEFT mirror in scenario 17 is now UNKNOWN, where it used to read CLEAR.
* **Occlusion.** Unsigned windows give UNKNOWN. A signed window crossing the near zone prevents CLEAR. Windows are re-applied at assessment time.
* **Incorrect orientation.** The body fiducial catches a wrong offset (scenario 15), a CW/CCW sign error, a 12° rotation and a missing mast. Without a fiducial, motion is refused.
* **Narrow door (scenario 24).** The jambs are in the corridor: CAUTION, then BLOCKED before contact.
* **Contracts.** Rover fields are bumper-referenced, with the horizon equal to `lookahead_m` and never `max_range_m`. Edge obstacles give OK/BLOCKED with a clearance. An unknown corridor gives ERROR. The rover still rejects the source, and the Stage D preview gives BLOCKED. The dashboard snapshot takes the more restrictive corridor status. The Qwen field carries the corridor with no authority.

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

The revolution takes ≈ 100 ms at the 10 Hz datasheet typical. Processing on the Mac measured p50 1.13 ms / p95 1.18 ms for 500 points, corridor included (SIMULATED; it was 0.58 ms before the corridor). The age at assessment is therefore ≈ 0.10–0.13 s, which fits the 0.20 s motion limit with ≈ 70–100 ms to spare. The real Pi 5 latency is **unmeasured**; Stage C `scan-once` reports it.

## Known limitations (documented, not hidden)

* **Mirror and phantom returns.** They are now rejected only because they are WEAK in simulation (quality 12 < 20). Real specular returns may be strong; the quality threshold must be calibrated against real glass and mirrors at Stage C. A strong phantom would still read as free space.
* **Corridor geometry.** It is a 2D rectangle in the scan plane. Obstacles below or above the plane (curbs, overhangs, table tops) are invisible to it. The corridor ignores turning and strafing; it covers forward motion only.
* **Footprint, fiducial and occlusion values.** The simulation uses placeholders (`SIM_ROBOT_WIDTH_M` 0.20 m and so on), labelled SIMULATED. The real values are unmeasured.
* **Orientation monitor resolution.** It is about tol + the fiducial's half-width (≈ 8° with the simulated mast). Smaller miscalibrations rely on the Stage C alignment procedure.
* Thresholds (0.35/0.75 m, quality 10, coverage 60 %, 7–13 Hz) are placeholders.
