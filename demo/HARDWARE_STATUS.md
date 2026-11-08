# Hardware status

> **Bottom line**
> * **No RoverC wheel has turned under Team-15 control.**
> * **No drone has flown.**
> * **No distance has been measured against ground truth.**
>
> What is real: the camera pipeline on a Raspberry Pi 5 + IMX708 (live frames, person detection,
> latency) and read-only probes of the rover controller and sensors.

Labels: **PHYSICAL** (real hardware) · **PHYSICAL, read-only** (inspected; nothing actuated) ·
**REPLAYED** (recorded real data processed again) · **MOCKED** (a software model of the hardware) ·
**SIMULATED**.

Main sources:

* the team's [experiment registry](../docs/experiments/EXPERIMENT_REGISTRY.md) and
  [benchmark results](../docs/experiments/BENCHMARK_RESULTS.md), compiled at `d1b607a`, on main via
  PR #18;
* the reports linked below;
* for the rover controller, a private identification record from 2026-11-08 (summarised and redacted
  here, raw file not published).

Raw evidence stays private. Reports cite it by SHA-256.

## Raspberry Pi camera

Setup: Pi 5 + IMX708 at 1280 × 720, 5 fps, JPEG q80, rotated 180°. Frames go to a Mac for detection.

| Item | Result | Type | Sample / conditions | Source |
|---|---|---|---|---|
| Live capture and transport | 40/40 frames, 4.86 fps, mean 256 ms. A 90.2 s run gave 448 frames at 4.97 fps, 0 malformed, 0 reconnects | PHYSICAL | runs of 4–90 s | [CAM-15](../docs/experiments/reports/CAM-15-pi-transport-and-first-e2e.md) |
| Camera geometry | sensor IMX708; fx = fy = 1410.7 px; HFOV 48.8° (**nominal**, not a checkerboard calibration). Rotation 180° confirmed upright | PHYSICAL | 1 probe | [CAM-20](../docs/experiments/reports/CAM-20-pi-orientation-check.md), `docs/camera_mapping/EVALUATION.md` |
| Faster R-CNN person detection, 4 poses | **378/378** frames detected: standing 96/96, seated 94/94, lying feet-first 94/94, lying side 94/94. HOG baseline 0/94 on seated and lying | PHYSICAL | **1 consenting person, 1 room**, about 1.5–2 m (operator estimate), robot stationary, about 20 s per pose | [CAM-23](../docs/experiments/reports/CAM-23-pi-live-person-poses.md) |
| False alarms | empty room 0/96 frames (95 % upper bound about 3.1 %). Chair 101/101 never called a person, but got false "surfboard" labels. Drone 0/100 recognised (INCONCLUSIVE) | PHYSICAL | 96 / 101 / 100 frames | [CAM-24](../docs/experiments/reports/CAM-24-pi-live-empty-and-object.md) |
| Detection accuracy as precision/recall | **NOT MEASURED**: no labelled boxes exist | — | — | BENCHMARK_RESULTS |
| Camera → dashboard latency | 499 / 593 / 508 ms (three runs). Capture → state: median 479.8 ms, P90 563.3 ms at 4.68 fps; second run 542.2 / 670.3 ms at 3.76 fps | PHYSICAL | runs of 24.8 s and 70.4 s; Pi and Mac clocks not synchronised | [MAP-01](../docs/experiments/reports/MAP-01-live-pi-run-1-latency.md), [MAP-06](../docs/experiments/reports/MAP-06-live-pi-run-2-person-chair.md) |
| Robot-relative mapping | 40 × 40 grid of 0.1 m cells. Every real run: **1,600 UNKNOWN cells, 0 FREE**; route `NO_SUPPORTED_ROUTE`. Never run on a moving robot | PHYSICAL + REPLAYED | MAP-01…08 | `docs/06_OBSTACLE_MAPPING.md`, BENCHMARK_RESULTS |
| Distance | **UNCALIBRATED.** Mount not measured; the tape calibration (MAP-09) was **not run**. A chair cut off by the frame edge produced 7.9 m and 6.8 m height-based estimates; that bug was fixed in `73539a7` | REPLAYED / PHYSICAL | — | [MAP-09](../docs/experiments/reports/MAP-09-tape-distance-calibration.md), [MAP-06](../docs/experiments/reports/MAP-06-live-pi-run-2-person-chair.md) |
| Real vs simulated labelling | Live sightings start UNCONFIRMED with `confidence: null`. Replays are labelled `RECORDED`. Mislabelled Pi sightings are rejected (HTTP 422). Simulated data carries `SIMULATED` | design + tests | — | `docs/04_CAMERA_PERCEPTION.md`, `perception/SIGHTING_FORMAT.md` |

Limitations:

* The 4-pose result covers one person in one room.
* The person-pose runner lives on an unmerged branch (`test/camera-live-countdown`).
* The recorded-frame regression test needs private frames and has never run in CI.

## RoverC-Pro and M5StickC controller

| Item | Status | Type | Evidence |
|---|---|---|---|
| USB serial detection | At first **not detected** in 8 checks (2026-11-07 23:27 → 11-08 12:28 UTC). **Later detected** on the team Pi as an FTDI USB-serial device and read with esptool (2026-11-08 09:42 ET) | PHYSICAL, read-only | [ROV-02](../docs/experiments/reports/ROV-02-controller-connectivity-inspection.md); private identification record |
| Controller identification | ESP32-PICO-D4 rev v1.1, 4 MB flash. Rules out StickC Plus2 and S3 sticks; consistent with M5StickC or M5StickC Plus. Verdict: **"likely M5StickC Plus, NOT CONFIRMED"** (needs the rear label). **"Plus SE" is not established** | PHYSICAL, read-only (esptool `flash_id`) | private identification record |
| Original firmware backup | 4,194,304 bytes, SHA-256 `bc1366ef08dd4ff251dc64ad3daf896a037ec9f563ae3cfe7e6dd654215bf95d`. **Two independent full reads were byte-identical.** Re-hashed for this package: matches. RoverC motor power OFF during the read. **Restoring it was never tested** | PHYSICAL, read-only | private record and backup (not published: third-party firmware) |
| Installed firmware | the earlier USB text protocol (`HELLO` / `STOP` / `MOVE`) from the PR #6 effort. **Not** the Team-15 bridge | PHYSICAL, read-only | private identification record |
| Team-15 bridge firmware flashed | **No evidence.** The bridge compiles on the closed PR #20 branch, and an approval-gated flash script exists there, but its header still says "NOT FLASHED, NOT RUN" | — | `docs/13_M5STICKC_BRIDGE.md`; PR #20 (closed) |
| DISARMED screen on the device | **No evidence** (only in the firmware state machine and its Python model) | MOCKED | [BRG-01](../docs/experiments/reports/BRG-01-bridge-watchdog-mocked-tests.md) |
| STOP acknowledgement from the device | **No evidence on hardware.** The mocked model acknowledges STOP | MOCKED | BRG-01 |
| I²C | the Pi header bus `i2c-1` is not enabled. RoverC address 0x38 not seen in sysfs (`i2cdetect` deliberately not run) | PHYSICAL, read-only | `docs/rover/HARDWARE_READINESS.md` |
| Bridge watchdog | **63/63** tests pass. The modelled watchdog stops at 0.251 s (design 250 ms, requirement ≤ 300 ms). Cable cut: host `DRIVER_FAULT` after 0.05 s | MOCKED (simulated clock) | BRG-01; `rover/tests/test_bridge.py` |
| Physical motor test | **NOT STARTED: Gate 5 blocked.** ROV-03a and ROV-03b NOT RUN: "No motor command was sent, no serial port was opened and no firmware was flashed" | — | `docs/rover/SAFETY_AND_LIMITATIONS.md`, ROV-02 |
| **Real wheel rotation** | **NOT DEMONSTRATED** | — | registry: "No row moved a real RoverC wheel" |

## Sensors

| Sensor | Result | Type | Sample / conditions | Source |
|---|---|---|---|---|
| Grove ultrasonic | **0/50 valid readings, 50 NO_ECHO, 0 echo edges**, health FAULT, motion STOP. A second run also gave 0/50. Root cause UNKNOWN; the series resistor was never measured | PHYSICAL | 2 × 50 pings, Pi 5 GPIO5, target about 100 cm | [RNG-HW-01](../docs/experiments/reports/RNG-HW-01-grove-real-hardware-diagnose.md) |
| Grove preflight gate | Pi platform checks 9/10 PASS. The electrical gate refused, then passed on the operator's attestation; "nothing physical was verified" | PHYSICAL, read-only | 10 gate runs | [RNG-PF-01](../docs/experiments/reports/RNG-PF-01-grove-preflight-gate-runs.md) |
| Grove simulator | 50/50 valid, 97.26–102.03 cm ("not measurements") | SIMULATED | 50 pings | [RNG-SIM-01](../docs/experiments/reports/RNG-SIM-01-ranging-simulation-test-suite.md) |
| RPLIDAR C1 | its USB adapter **enumerated** in 4 of 6 read-only checks. **No GET_INFO, HEALTH or SCAN was ever sent, so no distance was ever measured.** The hardware gate never opened | PHYSICAL, read-only | 6 checks | [LDR-HW-01](../docs/experiments/reports/LDR-HW-01-lidar-usb-enumeration-and-gate.md) |
| LiDAR software | 124 tests; simulated scenarios (for example BLOCKED at 0.2409 m) | SIMULATED | 23 fixtures | [LDR-SIM-01](../docs/experiments/reports/LDR-SIM-01-lidar-simulation-scenario-suite.md) |
| Camera calibration | UNCALIBRATED (see the camera section above) | — | — | MAP-09 |
| Sensor safety gates | Hardware NO_ECHO is always UNKNOWN. An unverified LiDAR never allows motion. A camera can never be used as a range sensor. The rover adapter refuses until hardware verification is filled in (it never was). The gate CLIs refuse (exit 2/3/2). Only the Grove fail-closed path ran on real hardware | MOCKED / SIMULATED; PHYSICAL refusals | — | `docs/17_SAFETY_ARCHITECTURE.md` |

## Not published, and why

* **Real camera frames:** they show people, and consent for publication was not recorded or was marked
  `public_sharing: false`. The demo video was recorded with no camera folder attached.
* **The firmware backup binary:** it is third-party firmware.
* **Device identifiers:** USB serial numbers and MAC addresses.
* **Network and host details:** Tailscale and LAN addresses, SSH aliases, account names, and local
  absolute paths.
* **GitHub handles and personal names** found in the logs.

## Remaining unverified hardware capabilities

1. Wheel rotation, motion of any kind, and every motion-safety layer on real hardware.
2. Bridge firmware flashed and running, including its DISARMED state, STOP acknowledgement and 250 ms
   watchdog.
3. The exact controller model (rear label) and a restore of the original firmware.
4. I²C to the RoverC (0x38), battery voltage and the undervoltage threshold.
5. Any valid Grove echo, and any RPLIDAR distance.
6. Camera distance against ground truth (tape calibration), precision/recall, and the false-positive
   rate.
7. Any drone hardware.
8. LoRA running live on the robot path. The closed PR #20 branch contains a startup check that refuses
   to serve unless the adapter changes the next-token logits, but **no log of that check is committed**,
   so it is unverified here.
