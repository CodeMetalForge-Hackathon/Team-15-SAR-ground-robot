# RPLIDAR C1 architecture (Team-15 ground robot)

**Status: implemented and SIMULATION-TESTED. Not hardware-tested.** No physical LiDAR has been powered or scanned. Grove stays the default range source (migration Stage A/B).

| Capability | State |
|---|---|
| Legacy protocol codec (STOP/RESET/SCAN/GET_INFO/GET_HEALTH, 5-byte nodes) | Implemented; tested on synthetic bytes |
| Driver: connect, health, scan, revolution assembly, timeouts, disconnect, cleanup | Implemented; tested against `MockLidarDevice` |
| C1 answering legacy SCAN at 460800 baud on our unit | **Proposed**: unverified, checked at Stage C |
| 8-sector processing, freshness, fail-closed assessment | Implemented; simulation-tested |
| Rover adapter (`team15.rover_range_fields/1`) | Implemented. Today's rover **rejects** it (source allowlist) → UNKNOWN |
| Dashboard compatibility snapshot (`team15.range_snapshot/1`) | Implemented; renders on the existing card, display only |
| Replay server + polar view (port 8775) | Implemented; SIMULATED only |
| Qwen optional `lidar` context field | Implemented (adapter); the Qwen repo has not consumed it yet |
| Physical scan, calibration, alignment | **Blocked**: hardware checklist plus explicit approval |
| LiDAR-driven motion | **Blocked**: Issue #9, Stage D/E review |

## Data flow

```
RPLIDAR C1 ──TTL UART── [verified USB adapter] ──USB── Raspberry Pi 5
                                                    │  /dev/serial/by-id/<explicit>, exclusive lock
                                                    ▼
  lidar.transport.SerialTransport (pyserial, lazy)   │   MockLidarDevice (CI)
                                                    ▼
  lidar.driver.RplidarC1Driver ── Scan (team15.lidar_scan/1, SENSOR frame, capture_start_mono_ns)
                                                    ▼
  lidar.processing.LidarAssessor ── LidarAssessment (team15.lidar_sectors/1, ROBOT-frame sectors)
         │                 │                         │                         │
         ▼                 ▼                         ▼                         ▼
  adapters.to_rover_fields  adapters.to_range_snapshot  panel.panel_view      adapters.to_advisory_context
  rover_range_fields/1      range_snapshot/1            lidar_panel/1         lidar_advisory_context/1
  source "rplidar-c1"       forward_motion_allowed      replay server :8775   association NOT_ESTABLISHED
  → rover rejects (ERROR)   always False → card         polar/top-down view   → Qwen (explain only)
```

## Frames (never mixed)

* **SENSOR**: the protocol angle, degrees **clockwise** from the sensor's own 0 mark, seen from above. Scan samples, `closest.sensor_bearing_deg` and unaligned panel points use it.
* **ROBOT**: 0° = robot forward axis, **counter-clockwise** positive (left = +90°), the same as `rover/sensors.py`. Conversion: `robot = (sign·sensor + forward_offset_deg) mod 360`, with `sign = −1` for a clockwise sensor.
* **WORLD**: none. A 2D scan gives no position, heading or GPS. Nothing in `lidar/` emits world coordinates.

`forward_offset_deg` has **no default**. Until a named person records a measured alignment (`alignment_verified_by/_at`), every sector is UNKNOWN. The simulator deliberately mounts the sensor with 0° facing the robot's **rear**, so any "sensor 0 = forward" bug fails the tests (scenario 15).

## Safety boundaries

* `lidar/` imports no GPIO, motor, servo, I²C or rover-actuation module. A test enforces this through the AST; pyserial is imported only inside `SerialTransport`.
* Hardware mode needs every item of `LIDAR_C1_HARDWARE_CHECKLIST.md` recorded by name, plus an independent inspector. The gate refuses **before** any transport is constructed.
* The first physical scan (`python -m lidar scan-once`) also needs `--approved-by`. It is stationary, and it touches no rover code.
* A real device is `HARDWARE_UNVERIFIED`. That label never allows motion and never shows a plain HARDWARE badge. `HARDWARE_VERIFIED` is reserved, and no code path sets it.
* LiDAR ranges are reflecting surfaces. They are never person distances; `person_distance_m` is always null and `is_person` is always null.
* Qwen receives validated structure only, with `may_authorize_motion: false` and `may_authorize_release: false`.
