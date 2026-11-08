# 00 · Project overview

Team-15 built the software stack for a small search-and-rescue ground robot during the CodeMetal Forge hackathon (6–8 November 2026). A Raspberry Pi 5 with a Sony IMX708 camera streams frames to a MacBook. The Mac detects people and obstacles, estimates distances with stated uncertainty, builds a robot-relative map, judges whether the corridor ahead is passable, and shows all of it on an operator dashboard. A local Qwen3.5-2B model, backed by a retrieval knowledge base, explains the scene in plain language. Navigation, the safety supervisor, the motor bridge and the range sensors are implemented and tested in **simulation and with mocks**. Their hardware paths are deliberately locked behind gates that had not been passed by the end of the event. This document explains the problem, what was built, and exactly what was and was not demonstrated.

**Status:** Implemented. Camera perception and the dashboard are hardware-verified on the bench (Pi camera stream, Mac detector). Navigation, the motors, the LiDAR and the ultrasonic sensor are simulation-tested only, or not tested on hardware.

**Related:** [01 System architecture](01_SYSTEM_ARCHITECTURE.md) · [17 Safety architecture](17_SAFETY_ARCHITECTURE.md) · [19 Testing and benchmarks](19_TESTING_AND_BENCHMARKS.md) · [26 Hackathon demo guide](26_HACKATHON_DEMO_GUIDE.md) · [27 Project timeline](27_PROJECT_TIMELINE.md) · [28 Contributors](28_CONTRIBUTORS.md) · [docs index](README.md)

---

## 1. The problem

The hackathon brief, as recorded in the build guide ([`TEAM15_DRONE_SEARCH_BUILD.md`](../TEAM15_DRONE_SEARCH_BUILD.md) §0, which quotes the official event page), asked teams to:

- locate isolated people when GPS, cell service and fixed communications are unreliable;
- detect life and hazards;
- map changing conditions;
- deliver critical information over degraded communications.

Judging was on mission relevance, a working live demonstration, and deployability. The build window in that guide is Saturday 7 November 10:00 to Sunday 8 November 12:00 (local time).

In a real search, a false "all clear" is far worse than an honest "I don't know". A robot that announces "no person here" or "path is clear" when it simply cannot see is dangerous. Rescuers would skip the room, or drive into a drop-off. That single idea shaped almost every design decision in this repository:

> **Unknown is never treated as clear, and no machine output is treated as a confirmed fact until a human confirms it.**

## 2. The mission, and how it changed

The project started as an **aerial drone search plan** and pivoted to a **wheeled ground robot** during the event. The full history is in [27 Project timeline](27_PROJECT_TIMELINE.md). In short:

1. **Drone search plan (PR #1, 7 Nov 18:39 UTC).** The build guide proposed three SIMULATED aerial scouts, a live laptop-camera person detector, a synthetic trail graph with Dijkstra routing, a base-station dashboard, and Qwen as an optional tool-caller. The first implementation PRs follow that plan: the A→G planner (#2), the bench camera detector (#3) and the dashboard (#5). The sector letters A–Z and the "drone D1" fields in the sighting format come from this phase.
2. **Ground-robot pivot (evening of 7 Nov).** The session console log at 2026-11-07 23:06 UTC records the operator moving the Raspberry Pi onto the wheeled robot. Within about 20 minutes, separate workstreams were set up for the Grove ultrasonic sensor (PR #7), RoverC-Pro navigation (PR #8) and the ground-rescue Qwen work. The robotics PRs from #7 onwards target the M5Stack RoverC-Pro.
3. **Integration (7–8 Nov).** The RPLIDAR C1 (#11), Qwen advisory contract (#12), Qwen model docs (#13), fail-closed forward motion (#14), the USB StickC bridge (#15) and camera-only obstacle mapping (#16) landed on `main` between 12:10 and 12:12 UTC on 8 Nov. A separate drone-fleet simulation (`team15_starter/`, PR #17) from other teammates merged at 12:14 UTC. That merge is commit `d1b607a`, the revision these documents describe.

## 3. Summary for judges

**What you can see working live:** a Raspberry Pi 5 camera on the robot streams to the Mac. A COCO-pretrained Faster R-CNN finds people and furniture at about 4–5 frames per second. The dashboard shows every detection as an **unconfirmed candidate** with its evidence and provenance badge. Next to it you see a robot-relative map, a corridor verdict, which was UNKNOWN in every recorded run because the mount is unmeasured (the code can also produce CLEAR / CAUTION / BLOCKED), and a guarded Qwen explanation that cites its retrieval sources. If the camera dies, the dashboard turns STALE and the verdict becomes UNKNOWN within about 2 seconds.

**What is honest about it:**

- Camera distances are **uncalibrated estimates**. The tape-measure calibration and the mount measurement were never done.
- At `d1b607a` the mount height and pitch are unmeasured. The pipeline therefore reports the corridor as UNKNOWN and suggests no route, by design. Every recorded run of the demo script shows UNKNOWN on every frame (see [26](26_HACKATHON_DEMO_GUIDE.md)).
- The robot **never drove** under this software. Wheel movement is NOT TESTED.

**What is engineered but not hardware-proven:** a navigation stack with a fail-closed safety supervisor (scenarios A–H in simulation), a USB-serial StickC bridge with a 250 ms firmware watchdog (mocked, firmware never compiled), a Grove ultrasonic service, and an RPLIDAR C1 driver. Each sits behind an explicit hardware gate that refuses to run until a human checklist is filled in. The gates are tested in CI.

**Qwen:** a LoRA adapter was trained and published on Hugging Face. With RAG it scored 218/230 correct mission steps and 0 unsafe motion requests on a frozen **synthetic** benchmark (`README.md`, [docs/qwen/MODEL.md](qwen/MODEL.md)). The live demo runs **base** Qwen3.5-2B through Ollama with RAG and a guard, because the demo service cannot load PEFT adapters ([docs/camera_mapping/EVALUATION.md](camera_mapping/EVALUATION.md) §6, [08](08_QWEN_MODEL.md)). Qwen has **no motor authority** anywhere in the code.

## 4. Capability matrix

Labels follow the [docs index](README.md): **REAL HARDWARE**, **RECORDED HARDWARE**, **SIMULATED**, **MOCKED**, **SYNTHETIC**, and **NOT TESTED / NOT MEASURED / UNVERIFIED**. "Demonstrated" means a record of it actually running exists. Code or tests existing is not enough.

| Capability | Code at `d1b607a` | Best evidence that it ran | Label | Where documented |
|---|---|---|---|---|
| Bench person detection, MacBook camera (Faster R-CNN, HOG, Haar) | `perception/` | PR #3 bench trials, 7 Nov about 14:10–14:45 local: person detector 96–97/97 standing frames, 98/98 seated-back; 60 s empty-scene test **not passed** (reflections, bystanders) | REAL HARDWARE (bench) | [04](04_CAMERA_PERCEPTION.md), PR #3 |
| Pi 5 IMX708 → Mac JPEG-over-SSH stream | `perception/pi_source.py` | PR #5: 90 s, 448 frames at 4.97 fps, capture→Mac 0.264 s, 0 malformed. EVALUATION §3: 117 frames at 4.68 fps | REAL HARDWARE | [02](02_RASPBERRY_PI_SETUP.md), [contracts/PI_CAMERA_CONTRACT.md](../contracts/PI_CAMERA_CONTRACT.md) |
| Camera orientation on the robot mount (rotation 180) | `perception/orientation_check.py` | Orientation check on 7 Nov (PR #3 comment) | REAL HARDWARE | [04](04_CAMERA_PERCEPTION.md) |
| Live sighting → dashboard → operator confirm/reject → route A→G | `core/`, `dashboard/`, `planner/` | e2e tests with a fake Pi sender. PR #5 states that no live Pi **person** sighting had reached the dashboard at that point (the camera was aimed at a close object) | MOCKED (end-to-end); live Pi frames REAL HARDWARE | [16](16_DASHBOARD.md) |
| Camera-only obstacle mapping, corridor verdict, panels A–D | `camera_mapping/` | EVALUATION §3b: 266 LIVE frames, 3.76 fps; real person and chair detected; corridor UNKNOWN throughout (mount unmeasured) | REAL HARDWARE (perception); verdict logic exercised only in its UNKNOWN branch live | [06](06_OBSTACLE_MAPPING.md), [07](07_PATH_PLANNING.md) |
| Camera distance accuracy | `camera_mapping/distance.py`, `calibrate.py` | **NOT MEASURED**: no tape samples; mount unmeasured; status `UNCALIBRATED` | NOT MEASURED | [05](05_DEPTH_AND_DISTANCE_ESTIMATION.md), [CALIBRATION](camera_mapping/CALIBRATION.md) |
| Monocular depth (Depth-Anything-V2) | `camera_mapping/depth.py` | One recorded Pi frame, about 117 ms on MPS; output plausible but **unvalidated**; never fused | RECORDED HARDWARE | EVALUATION §4 |
| Qwen advisory in the camera demo (base + RAG + guard) | `camera_mapping/advisory.py`, `qwen_launcher.py` | EVALUATION §6: 4.0–5.9 s per advisory, `QWEN_GUARDED`, RAG citations | REAL HARDWARE (Mac inference on live and recorded states) | [08](08_QWEN_MODEL.md), [10](10_RAG_PIPELINE.md) |
| Qwen LoRA mission benchmark 218/230 | private Qwen workspace; adapter on HF | Frozen simulated benchmark, measured with RAG | SYNTHETIC | [09](09_LORA_TRAINING.md), [qwen/MODEL.md](qwen/MODEL.md) |
| LiDAR advisory contract + guard | `qwen_advisory/` | 23 unit tests, 8 SIMULATED cases | SIMULATED | [11](11_AI_AGENT_AND_TOOLS.md), [QWEN_ADVISORY_CONTRACT](qwen/QWEN_ADVISORY_CONTRACT.md) |
| Route planning (Dijkstra A→G = 60 m, rerouting) | `planner/`, `rover/navigator.py` | CI asserts it on every push; `rover.simrun` scenarios A–H | SIMULATED (synthetic graph) | [07](07_PATH_PLANNING.md), [18](18_SIMULATION.md) |
| RoverC-Pro wheel motion | `rover/hardware.py` (`RoverCAdapter` refuses to construct) | **NOT TESTED**: no wheel has been driven | NOT TESTED | [12](12_ROVERC_MOTOR_CONTROL.md), [rover/HARDWARE_READINESS](rover/HARDWARE_READINESS.md) |
| Safety supervisor, fail-closed forward motion (Issue #9) | `rover/motion.py` | 40 + 21 unit tests; sim scenarios | SIMULATED / MOCKED | [17](17_SAFETY_ARCHITECTURE.md) |
| USB-serial M5StickC bridge + 250 ms firmware watchdog | `rover/bridge.py`, `firmware/stickc_roverc_bridge/` | 63 tests against an executable firmware model. The `.ino` is a **draft: never compiled or flashed**. No StickC was detected on the Pi in reported checks | MOCKED | [13](13_M5STICKC_BRIDGE.md), [rover/BRIDGE_PROTOCOL](rover/BRIDGE_PROTOCOL.md) |
| Grove ultrasonic forward range | `ranging/` | Two real diagnostic runs on the Pi 5, 8 Nov about 10:43 and 10:50 UTC: **0/50 VALID** each, 50/50 NO_ECHO, health FAULT; root cause UNKNOWN | REAL HARDWARE — **FAILED** | [14](14_GROVE_ULTRASONIC.md) |
| RPLIDAR C1 360° scan | `lidar/` | 124 tests on mock serial and 20+ SIMULATED scenarios. **No physical scan**: `scan-once` needs a filled checklist and a named approver | SIMULATED / MOCKED; real scan **NOT VERIFIED** | [15](15_RPLIDAR_C1.md), [lidar/LIDAR_C1_TEST_REPORT](lidar/LIDAR_C1_TEST_REPORT.md) |
| Drone-fleet search simulation (Aurora, `team15_starter/`) | `team15_starter/` | 5 pytest tests plus a 30-check Python↔C protocol script; result CSVs in `team15_starter/results/` | SIMULATED | [18](18_SIMULATION.md), [team15_starter/HARDWARE.md](../team15_starter/HARDWARE.md) |
| BLE authenticated identity, Crazyflie demos | branch `culubo/sensor-id-specs` (PR #6, **open**) | Not on `main`; not reviewed here | UNVERIFIED (not merged) | [27](27_PROJECT_TIMELINE.md) |

## 5. What is original here

Most components are standard techniques: COCO Faster R-CNN, pinhole geometry, occupancy grids, A\*/Dijkstra, LoRA, SQLite FTS5 retrieval. The original contribution is how they are put together so that the system stays honest under uncertainty:

1. **Provenance travels with every value.** Each sighting, distance and range carries a label (`LIVE-HW`, `RECORDED`, `SIMULATED`; `CAMERA_ESTIMATE`; `UNCALIBRATED_ESTIMATE`). Consumers refuse values that claim more than they can prove. For example, `dashboard/perception_source.py` `validate_state` rejects any camera distance labelled `VERIFIED`. The range card shows HARDWARE only when three independent fields agree (PR #5).
2. **UNKNOWN is a first-class state** in every verdict: the camera corridor, the Grove obstacle assessment, the LiDAR sectors and the rover range fields. Each verdict has its own refusal reasons.
3. **Advice is separated from authority by construction, and tested.** Qwen and the camera pipeline emit `authority: "NONE"` records. A static test (`rover/tests/test_issue9_fail_closed.py`) fails if any module outside an explicit allow-list imports the supervisor, the hardware driver, the motor protocol or the bridge.
4. **Hardware gates are code, not checklists on paper.** The Grove, LiDAR and RoverC paths refuse to open a device until a config records a two-person sign-off. CI asserts that the unverified configs are refused (`.github/workflows/lidar.yml`, `ranging.yml`).
5. **Defence in depth for the motors.** A host-side supervisor latches faults and never restarts by itself. The (draft) StickC firmware zeroes the motors on its own after 250 ms without valid frames. The design does not trust the Pi to stay alive.

These are design properties backed by unit tests. They are **not** measurements of physical safety; see [19 §7](19_TESTING_AND_BENCHMARKS.md#7-what-the-tests-do-not-prove).

## 6. Hardware

| Item | Role | Verified how |
|---|---|---|
| Raspberry Pi 5 (16 GB, Debian 13 per session briefs) | Camera host, planned sensor host | REAL: read-only inspection; Pi 5 Rev 1.1, `throttled=0x0` ([rover/HARDWARE_READINESS](rover/HARDWARE_READINESS.md)) |
| Sony IMX708 camera module | Primary sensor | REAL: picamera2 probe, ScalerCrop measured (EVALUATION §2) |
| MacBook Pro M4 Pro, 24 GB | Detector (PyTorch MPS), dashboard, Qwen (Ollama) | REAL (EVALUATION header) |
| M5Stack RoverC-Pro (mecanum) + M5StickC | Drive base and motor MCU host | Controller **not detected** on USB, I²C or Bluetooth in the team Pi/Mac checks. The unmerged PR #6 branch claims a StickC Plus was flashed from a teammate's Mac. Wheel rotation is **not verified** on any path |
| Seeed Grove Ultrasonic Ranger | Forward range | Wired; 0/50 valid twice; cause unknown |
| Slamtec RPLIDAR C1 | Planned 360° range | Never powered or scanned under this code |
| Hailo-8 HAT | Listed in the build guide | No code on `main` runs inference on it. It appears only as a power-headroom item in the LiDAR checklist (`lidar/config.py`) |

The Pi was **unreachable** (Tailscale SSH timeout) during this documentation audit on 8 Nov 2026, so nothing here was re-measured on hardware.

## 7. Repository map

| Path | What | Doc |
|---|---|---|
| `perception/` | Bench and Pi camera person detector, sighting format | [04](04_CAMERA_PERCEPTION.md) |
| `camera_mapping/` | Distance, tracking, local map, corridor, advisory, live runner | [05](05_DEPTH_AND_DISTANCE_ESTIMATION.md), [06](06_OBSTACLE_MAPPING.md), [07](07_PATH_PLANNING.md) |
| `dashboard/`, `core/` | FastAPI base station, mission store, ingest rules | [16](16_DASHBOARD.md) |
| `planner/` | Trail graph, Dijkstra, ALT A\* | [07](07_PATH_PLANNING.md) |
| `rover/`, `firmware/` | Navigator, supervisor, simulator, StickC bridge | [12](12_ROVERC_MOTOR_CONTROL.md), [13](13_M5STICKC_BRIDGE.md) |
| `ranging/` | Grove ultrasonic service | [14](14_GROVE_ULTRASONIC.md) |
| `lidar/` | RPLIDAR C1 driver and processing | [15](15_RPLIDAR_C1.md) |
| `qwen_advisory/` | LiDAR advisory contract and guard | [11](11_AI_AGENT_AND_TOOLS.md) |
| `contracts/` | Pi camera and rover navigation contracts | [01](01_SYSTEM_ARCHITECTURE.md) |
| `team15_starter/` | Aurora drone-fleet simulation (separate project) | [18](18_SIMULATION.md) |
| `scripts/camera_demo.sh` | One-command judge demo | [20](20_DEPLOYMENT_AND_RUNBOOK.md), [26](26_HACKATHON_DEMO_GUIDE.md) |

## 8. Team

Git and pull-request history show these GitHub accounts: `machackgo` (repository integration, perception, dashboard, robotics, LiDAR, Qwen docs), `hafsaah1` and `GavinPrescott` (Aurora drone-fleet simulation), `ithlambelle` and `culubo` (BLE identity and mission-control work on the open PR #6 branch), and `dennisnahas` (initial commit). Most `machackgo` commits carry a Claude Code co-author trailer. Counts and areas are in [28 Contributors](28_CONTRIBUTORS.md).

## 9. Limitations in one list

- No camera distance has been compared against ground truth.
- No wheel has turned under this code; the StickC firmware has never been compiled.
- The only real ultrasonic data is 100 NO_ECHO pings.
- No physical LiDAR scan exists.
- The person detector false-alerts on window reflections. The 60 s empty-scene test never passed.
- The Qwen benchmark is synthetic and in-distribution. The deployed demo model is the base model, not the adapter.
- The dashboard's mission store is in memory only.

The full list is in [25 Limitations and future work](25_LIMITATIONS_AND_FUTURE_WORK.md).
