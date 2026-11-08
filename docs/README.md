# Team-15 documentation index

This is the entry point for the Team-15 search-and-rescue ground-robot documentation (CodeMetal Forge hackathon, 6–8 November 2026).

**How to read the status labels.** Every result in these documents carries one of these provenance labels:

| Label | Meaning |
|---|---|
| **REAL HARDWARE** | Measured live on the physical device (Raspberry Pi 5, camera, sensor) |
| **RECORDED HARDWARE** | Real captures replayed later (for example, saved Pi camera frames) |
| **SIMULATED** | Produced by one of our simulators |
| **MOCKED** | Produced against a test double (for example, a fake serial port) |
| **SYNTHETIC** | Generated data (for example, the synthetic mission records used for Qwen) |
| **NOT MEASURED / NOT TESTED / UNVERIFIED** | No supporting record exists. We say so rather than guess |

**Ground truth in one paragraph.** The camera pipeline ran live on a Raspberry Pi 5 with an IMX708 camera, with detection running on the Mac. Camera distances are **uncalibrated**: the tape calibration has not been done. The rover navigation stack, the safety supervisor and the StickC bridge are tested in **simulation and with mocks only**. Real wheel movement is **NOT TESTED**. The StickC controller was **not detected** in the reported checks, and its firmware is a draft that has never been flashed. The only real Grove ultrasonic runs gave **0 of 50 valid readings, twice**. A real RPLIDAR C1 scan is **NOT VERIFIED**. The Qwen LoRA adapter was trained and published, but the live demo uses **base Qwen with RAG**. Qwen has **no motor authority**.

## Start here

| If you are… | Read |
|---|---|
| A judge with 10 minutes | [00 Project overview](00_PROJECT_OVERVIEW.md) → [26 Hackathon demo guide](26_HACKATHON_DEMO_GUIDE.md) → [Experiment summary](experiments/EXPERIMENT_SUMMARY.md) |
| A developer who needs to run it | [01 Architecture](01_SYSTEM_ARCHITECTURE.md) → [20 Deployment and runbook](20_DEPLOYMENT_AND_RUNBOOK.md) → [19 Testing](19_TESTING_AND_BENCHMARKS.md) → [21 Troubleshooting](21_TROUBLESHOOTING.md) |
| Studying the project in depth | [24 Learning guide](24_LEARNING_GUIDE.md); it sets out a full reading order |

## Numbered documents

| # | Document | Topic |
|---|---|---|
| 00 | [Project overview](00_PROJECT_OVERVIEW.md) | Problem, mission, capability matrix |
| 01 | [System architecture](01_SYSTEM_ARCHITECTURE.md) | Components, hosts, data flows, contracts |
| 02 | [Raspberry Pi setup](02_RASPBERRY_PI_SETUP.md) | Pi 5, IMX708 capture, Pi→Mac transport |
| 03 | [Mac AI inference](03_MAC_AI_INFERENCE.md) | Why inference runs on the Mac; runtimes |
| 04 | [Camera perception](04_CAMERA_PERCEPTION.md) | Faster R-CNN, HOG, sightings, provenance |
| 05 | [Depth and distance estimation](05_DEPTH_AND_DISTANCE_ESTIMATION.md) | Pinhole geometry, ground-plane and known-height ranging, monocular depth |
| 06 | [Obstacle mapping](06_OBSTACLE_MAPPING.md) | Tracking, robot-relative local map, unknown/free/occupied |
| 07 | [Path planning](07_PATH_PLANNING.md) | Corridor assessment, advisory routes, Dijkstra/A* |
| 08 | [Qwen model](08_QWEN_MODEL.md) | Qwen3.5-2B, base vs LoRA, deployment status |
| 09 | [LoRA training](09_LORA_TRAINING.md) | Training runs, hyperparameters, checkpoint selection |
| 10 | [RAG pipeline](10_RAG_PIPELINE.md) | FTS5 retrieval, provenance, prompt construction |
| 11 | [AI agent and tools](11_AI_AGENT_AND_TOOLS.md) | Tool contracts, safety guard, no motor authority |
| 12 | [RoverC motor control](12_ROVERC_MOTOR_CONTROL.md) | Mecanum kinematics, navigator, motion primitives |
| 13 | [M5StickC bridge](13_M5STICKC_BRIDGE.md) | USB-serial protocol, firmware watchdog |
| 14 | [Grove ultrasonic](14_GROVE_ULTRASONIC.md) | Time of flight, ranging service, the 0/50 hardware result |
| 15 | [RPLIDAR C1](15_RPLIDAR_C1.md) | Protocol, scan processing, footprint corridor |
| 16 | [Dashboard](16_DASHBOARD.md) | Operator dashboard, panels, system health |
| 17 | [Safety architecture](17_SAFETY_ARCHITECTURE.md) | Defence in depth, fail-closed design, hardware gates |
| 18 | [Simulation](18_SIMULATION.md) | Rover, ranging, LiDAR and drone-fleet simulators |
| 19 | [Testing and benchmarks](19_TESTING_AND_BENCHMARKS.md) | Test suites, CI, what tests do and do not prove |
| 20 | [Deployment and runbook](20_DEPLOYMENT_AND_RUNBOOK.md) | Verified commands, start-up and shutdown |
| 21 | [Troubleshooting](21_TROUBLESHOOTING.md) | Symptom → cause → fix |
| 22 | [Experiments and failures](22_EXPERIMENTS_AND_FAILURES.md) | What went wrong, and what we learned |
| 23 | [Design decisions](23_DESIGN_DECISIONS.md) | Decision records with alternatives and rationale |
| 24 | [Learning guide](24_LEARNING_GUIDE.md) | 17 modules from beginner to advanced |
| 25 | [Limitations and future work](25_LIMITATIONS_AND_FUTURE_WORK.md) | What is missing and what comes next |
| 26 | [Hackathon demo guide](26_HACKATHON_DEMO_GUIDE.md) | Judge demo flow and honest talking points |
| 27 | [Project timeline](27_PROJECT_TIMELINE.md) | Commit and pull-request history |
| 28 | [Contributors](28_CONTRIBUTORS.md) | Who worked on what |

## Experiments and evidence

| Document | Contents |
|---|---|
| [Experiment registry](experiments/EXPERIMENT_REGISTRY.md) | Every experiment with identifiable records, one row each |
| [Benchmark results](experiments/BENCHMARK_RESULTS.md) | Consolidated numbers, with conditions and evidence |
| [Dataset inventory](experiments/DATASET_INVENTORY.md) | Every dataset: source, size, licensing, biases |
| [Experiment summary](experiments/EXPERIMENT_SUMMARY.md) | Counts, the strongest results, and the work that remains |
| [Detailed reports](experiments/reports/) | One standalone report per major experiment |

## Component documents that already existed

The numbered documents summarise these and link to them. They are not copied.

- Camera mapping: [CALIBRATION](camera_mapping/CALIBRATION.md), [DEMO](camera_mapping/DEMO.md), [EVALUATION](camera_mapping/EVALUATION.md), [JUDGE_DEMO](camera_mapping/JUDGE_DEMO.md), [package README](../camera_mapping/README.md)
- LiDAR: [architecture](lidar/LIDAR_C1_ARCHITECTURE.md), [data contract](lidar/LIDAR_C1_DATA_CONTRACT.md), [driver](lidar/LIDAR_C1_DRIVER.md), [demo runbook](lidar/LIDAR_C1_DEMO_RUNBOOK.md), [hardware checklist](lidar/LIDAR_C1_HARDWARE_CHECKLIST.md), [stationary scan procedure](lidar/LIDAR_C1_STATIONARY_SCAN_PROCEDURE.md), [test report](lidar/LIDAR_C1_TEST_REPORT.md), [merge audit](lidar/LIDAR_C1_MERGE_AUDIT.md), [Grove→LiDAR migration](lidar/GROVE_TO_LIDAR_MIGRATION.md), [implementation journal](lidar/IMPLEMENTATION_JOURNAL.md)
- Qwen: [MODEL](qwen/MODEL.md), [advisory contract](qwen/QWEN_ADVISORY_CONTRACT.md)
- Rover: [bench runbook](rover/BENCH_RUNBOOK.md), [bridge protocol](rover/BRIDGE_PROTOCOL.md), [hardware readiness](rover/HARDWARE_READINESS.md), [safety and limitations](rover/SAFETY_AND_LIMITATIONS.md)
- Ranging: [README](../ranging/README.md), [wiring](../ranging/WIRING.md), [integration](../ranging/INTEGRATION.md), [hardware validation](../ranging/HARDWARE_VALIDATION.md)
- Contracts: [Pi camera](../contracts/PI_CAMERA_CONTRACT.md), [rover navigation](../contracts/ROVER_NAV_CONTRACT.md), [sighting format](../perception/SIGHTING_FORMAT.md)
- Drone-fleet simulation: [build guide](../TEAM15_DRONE_SEARCH_BUILD.md), [hardware notes](../team15_starter/HARDWARE.md), [role changes](../team15_starter/CHANGES_ROLES.md)

## Private evidence stores

Raw evidence (camera frames, Pi logs, model weights, training data) is **not in Git**. That is deliberate, for privacy. The documents refer to the private stores through placeholders:

| Placeholder | What it is |
|---|---|
| `$TEAM15_EVIDENCE` | The operator's local camera and mapping evidence store (JSON and JSONL summaries, logs; frames are never published) |
| `$QWEN_WORKSPACE` | The private Qwen development workspace (training and evaluation code, logs, dataset cards, RAG corpus) |
| `$ADAPTER_BACKUPS` | Local backups of the LoRA adapter checkpoints and training logs (the weights are never committed) |
| `$ROBOT_WORKSPACE` | The private robotics workspace (bench notes, calibration plans) |
| Session console log | Engineering console transcripts from the build sessions. We cite these by date and time only |

Where a SHA-256 is given, anyone who holds the private store can check that it is the same file.
