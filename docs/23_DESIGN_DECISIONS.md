# 23 Design decisions

This document collects the design decisions behind the Team-15 search-and-rescue ground-robot stack as Architecture Decision Records (ADRs). Each record gives the context, the decision, the alternatives considered, the rationale, the evidence (commits, pull requests, tests, experiment reports), the consequences, and the current status. The records were merged and de-duplicated from the per-component audit notes and checked against the code at `d1b607a`. A decision is listed only if the repository, a pull request, or a dated evidence record shows it was actually made. Where the reasoning is inferred from history rather than written down at the time, the record says so.

**Status:** Reference document. The decisions describe code that is **implemented** and, for the motion path, **simulation-tested only**. No motion-safety decision has been hardware-verified ([17 Safety architecture](17_SAFETY_ARCHITECTURE.md) §4).

**Related:** [00 Project overview](00_PROJECT_OVERVIEW.md) · [01 System architecture](01_SYSTEM_ARCHITECTURE.md) · [17 Safety architecture](17_SAFETY_ARCHITECTURE.md) · [22 Experiments and failures](22_EXPERIMENTS_AND_FAILURES.md) · [24 Learning guide](24_LEARNING_GUIDE.md) · [25 Limitations and future work](25_LIMITATIONS_AND_FUTURE_WORK.md) · [27 Project timeline](27_PROJECT_TIMELINE.md)

---

## Contents

1. [How to read these records](#how-to-read-these-records)
2. [Index](#index)
3. [A. Cross-cutting decisions](#a-cross-cutting-decisions)
4. [B. Camera perception](#b-camera-perception)
5. [C. Camera mapping and distance](#c-camera-mapping-and-distance)
6. [D. Planning](#d-planning)
7. [E. Qwen, LoRA and RAG](#e-qwen-lora-and-rag)
8. [F. Rover motion and the StickC bridge](#f-rover-motion-and-the-stickc-bridge)
9. [G. Range sensors: Grove ultrasonic and RPLIDAR C1](#g-range-sensors-grove-ultrasonic-and-rplidar-c1)
10. [H. Process, CI and repository policy](#h-process-ci-and-repository-policy)
11. [Decisions we considered but have no record of](#decisions-we-considered-but-have-no-record-of)

---

## How to read these records

Each ADR uses the same fields:

| Field | Meaning |
|---|---|
| **Context** | The problem and constraints at the time |
| **Decision** | What was chosen, stated so that it can be checked against the code |
| **Alternatives** | Options that were considered or that are the obvious choice, and why they lost |
| **Rationale** | Why this option won |
| **Evidence** | Commits, PRs, files, tests and experiment IDs. Experiment IDs (CAM-xx, MAP-xx, QWN-xxx, ...) are defined in the [experiment registry](experiments/EXPERIMENT_REGISTRY.md) |
| **Consequences** | What the decision costs, and what it made possible |
| **Status** | One of: **Accepted** (in force on `main`), **Accepted (workaround)** (in force, but a proper fix is pending), **Unmerged** (exists only on a branch), **Open** (decided in principle, not implemented) |

Provenance labels follow the [documentation index](README.md): REAL HARDWARE, RECORDED HARDWARE, SIMULATED, MOCKED, SYNTHETIC. Private evidence stores are referred to as `$TEAM15_EVIDENCE`, `$QWEN_WORKSPACE`, `$ADAPTER_BACKUPS` and `$ROBOT_WORKSPACE`. They are not in Git.

---

## Index

| ID | Decision | Area | Status |
|---|---|---|---|
| [ADR-X01](#adr-x01-pivot-from-aerial-drone-search-to-a-wheeled-ground-robot) | Pivot from drone search to a wheeled ground robot | Cross-cutting | Accepted |
| [ADR-X02](#adr-x02-ai-is-advisory-only-and-has-no-motor-authority) | AI is advisory only; no motor authority; static allow-list test | Cross-cutting | Accepted |
| [ADR-X03](#adr-x03-fail-closed-defaults-everywhere) | Fail-closed defaults everywhere | Cross-cutting | Accepted |
| [ADR-X04](#adr-x04-unknown-is-never-clear) | UNKNOWN is never CLEAR | Cross-cutting | Accepted |
| [ADR-X05](#adr-x05-heavy-inference-on-the-mac-not-the-pi) | Heavy inference on the Mac, not the Pi | Cross-cutting | Accepted |
| [ADR-X06](#adr-x06-provenance-labels-on-every-result) | Provenance labels on every result; nothing can claim VERIFIED | Cross-cutting | Accepted |
| [ADR-X07](#adr-x07-no-photos-in-git-evidence-outside-the-work-tree) | No photos in Git; evidence outside the work tree | Cross-cutting | Accepted |
| [ADR-X08](#adr-x08-hardware-gates-in-code-with-unverified-configs-and-negative-ci-tests) | Hardware gates in code, UNVERIFIED configs, negative CI tests | Cross-cutting | Accepted |
| [ADR-X09](#adr-x09-versioned-json-contracts-between-components) | Versioned JSON contracts between components | Cross-cutting | Accepted |
| [ADR-X10](#adr-x10-human-in-the-loop-for-every-consequential-decision) | Human in the loop for every consequential decision | Cross-cutting | Accepted |
| [ADR-CAM01](#adr-cam01-faster-r-cnn-resnet-50-fpn-v2-as-the-person-detector) | Faster R-CNN R50-FPN v2 as the person detector | Camera | Accepted |
| [ADR-CAM02](#adr-cam02-run-every-detector-family-label-them-separately-trigger-only-on-the-person-detector) | Separate detector families; only PERSON_DETECTOR triggers | Camera | Accepted |
| [ADR-CAM03](#adr-cam03-confidence-null-raw-scores-labelled-as-not-a-probability) | `confidence: null`, raw score labelled | Camera | Accepted |
| [ADR-CAM04](#adr-cam04-one-sighting-per-continuous-presence) | One sighting per continuous presence | Camera | Accepted |
| [ADR-CAM05](#adr-cam05-minimum-trigger-box-height-15-percent-of-the-frame) | Minimum trigger box height 15 % | Camera | Accepted |
| [ADR-CAM06](#adr-cam06-location-is-the-operator-assigned-sector-only) | Location = operator-assigned sector only | Camera | Accepted |
| [ADR-CAM07](#adr-cam07-jpeg-over-an-ssh-session-opened-by-the-mac) | JPEG over an SSH session opened by the Mac | Camera | Accepted |
| [ADR-CAM08](#adr-cam08-obs_time-is-the-sensor-capture-time) | `obs_time` = sensor capture time | Camera | Accepted |
| [ADR-CAM09](#adr-cam09-keep-only-the-newest-frame) | Keep only the newest frame | Camera | Accepted |
| [ADR-CAM10](#adr-cam10-exactly-one-software-rotation-on-the-receiver) | One software rotation on the receiver | Camera | Accepted |
| [ADR-CAM11](#adr-cam11-warm-up-the-detector-on-one-discarded-real-frame) | Warm up on one discarded real frame | Camera | Accepted |
| [ADR-CAM12](#adr-cam12-consent-gated-live-test-runner) | Consent-gated live test runner | Camera | Unmerged |
| [ADR-MAP01](#adr-map01-nominal-intrinsics-from-the-datasheet-and-the-measured-scalercrop) | Nominal intrinsics from datasheet + measured ScalerCrop | Mapping | Accepted |
| [ADR-MAP02](#adr-map02-ground-plane-ranging-only-with-a-measured-mount) | Ground-plane ranging only with a measured mount | Mapping | Accepted |
| [ADR-MAP03](#adr-map03-known-height-ranging-with-wide-priors-refusing-truncated-or-non-upright-boxes) | Known-height ranging refuses truncated boxes | Mapping | Accepted |
| [ADR-MAP04](#adr-map04-fuse-only-when-every-pair-agrees-within-2σ) | Fuse only when every pair agrees within 2σ | Mapping | Accepted |
| [ADR-MAP05](#adr-map05-monocular-depth-is-an-optional-unfused-cross-check) | Monocular depth is an unfused cross-check | Mapping | Accepted |
| [ADR-MAP06](#adr-map06-three-state-robot-relative-grid-with-positive-invalidation-no-slam) | Three-state robot-relative grid; no SLAM | Mapping | Accepted |
| [ADR-MAP07](#adr-map07-camera-never-becomes-a-range-reading) | Camera never becomes a range reading | Mapping | Accepted |
| [ADR-MAP08](#adr-map08-the-dashboard-validates-perception-state-and-judges-freshness-itself) | Dashboard validates perception state | Mapping | Accepted |
| [ADR-MAP09](#adr-map09-single-producer-lock-on-perception-posts) | Single-producer lock on perception posts | Mapping | Accepted |
| [ADR-PLN01](#adr-pln01-deterministic-corridor-verdict-with-two-mode-advisory-routes) | Deterministic corridor verdict, two-mode advisory routes | Planning | Accepted |
| [ADR-PLN02](#adr-pln02-dijkstra-on-the-synthetic-trail-graph-a-is-a-benchmark-only) | Dijkstra on the synthetic trail graph; A\* benchmark only | Planning | Accepted |
| [ADR-PLN03](#adr-pln03-reroute-by-retreating-to-the-previous-node-no-local-bypass) | Reroute = retreat to the previous node | Planning | Accepted |
| [ADR-QWN01](#adr-qwn01-qwen35-2b-as-the-advisory-model) | Qwen3.5-2B as the advisory model | Qwen | Accepted |
| [ADR-QWN02](#adr-qwn02-ollama-q4-with-a-json-grammar-on-the-mac-thinking-mode-off) | Ollama Q4 + JSON grammar on the Mac; thinking off | Qwen | Accepted |
| [ADR-QWN03](#adr-qwn03-bounded-tool-loops-with-read-only-or-request-only-tools-and-a-minimum-evidence-fallback) | Bounded tool loops; minimum-evidence fallback | Qwen | Accepted |
| [ADR-QWN04](#adr-qwn04-sqlite-fts5-bm25-retrieval-with-a-bounded-context-and-an-injection-quarantine) | SQLite FTS5 BM25 retrieval, bounded context, quarantine | Qwen | Accepted |
| [ADR-QWN05](#adr-qwn05-lora-on-every-language-projection-vision-frozen-assistant-only-loss) | LoRA on all language projections; assistant-only loss | Qwen | Accepted |
| [ADR-QWN06](#adr-qwn06-frozen-test-sets-validation-only-selection-and-a-safety-gate-in-eligibility) | Frozen tests; validation-only selection; safety eligibility | Qwen | Accepted |
| [ADR-QWN07](#adr-qwn07-the-live-demo-runs-base-qwen--rag-not-the-lora-adapter) | Demo runs base + RAG, not the LoRA adapter | Qwen | Accepted |
| [ADR-QWN08](#adr-qwn08-publish-only-the-selected-adapter-keep-data-and-corpus-private) | Publish only ckpt-0088; keep data and corpus private | Qwen | Accepted |
| [ADR-QWN09](#adr-qwn09-delivery-decisions-stay-deterministic) | Delivery decisions stay deterministic | Qwen | Accepted |
| [ADR-QWN10](#adr-qwn10-do-not-patch-the-guard-to-the-frozen-sets-wording) | Do not patch the guard to the frozen set's wording | Qwen | Accepted |
| [ADR-QWN11](#adr-qwn11-launch-the-qwen-service-through-an-in-repo-launcher) | In-repo launcher for the SQLite threading bug | Qwen | Accepted (workaround) |
| [ADR-QWN12](#adr-qwn12-stdlib-only-qwen_advisory-port-with-its-own-ci) | Stdlib-only `qwen_advisory/` with its own CI | Qwen | Accepted |
| [ADR-ROV01](#adr-rov01-usb-serial-stickc-bridge-with-a-firmware-watchdog) | USB-serial StickC bridge with a firmware watchdog | Rover | Accepted (draft firmware) |
| [ADR-ROV02](#adr-rov02-forward-motion-requires-forward_allowed-is-true-issue-9) | Forward motion requires `forward_allowed is True` | Rover | Accepted |
| [ADR-ROV03](#adr-rov03-latch-and-require-an-operator-reset-never-auto-restart) | Latch; never auto-restart | Rover | Accepted |
| [ADR-ROV04](#adr-rov04-normalised-single-axis-bounded-duration-motion-primitives) | Normalised, single-axis, bounded primitives | Rover | Accepted |
| [ADR-ROV05](#adr-rov05-port-the-vendor-mixer-and-require-three-measured-signs) | Port the vendor mixer; three measured signs | Rover | Accepted |
| [ADR-ROV06](#adr-rov06-scan-by-rotating-the-chassis-on-its-wheels-closed-loop-heading-only) | Scan by rotating the chassis; closed-loop heading only | Rover | Accepted |
| [ADR-ROV07](#adr-rov07-only-simulator-ground-truth-pose-authorises-autonomous-motion) | Only SIM_TRUTH pose authorises autonomous motion | Rover | Accepted |
| [ADR-ROV08](#adr-rov08-per-process-random-session-in-the-bridge-arm) | Per-process random bridge session | Rover | Accepted |
| [ADR-ROV09](#adr-rov09-separate-freshness-limits-for-motion-and-display) | Separate freshness limits for motion and display | Rover | Accepted |
| [ADR-ROV10](#adr-rov10-keep-the-drone-fleet-simulation-separate) | Keep the drone-fleet simulation separate | Rover | Accepted (inferred) |
| [ADR-SEN01](#adr-sen01-power-the-grove-ranger-from-33-v) | Power the Grove ranger from 3.3 V | Sensors | Accepted |
| [ADR-SEN02](#adr-sen02-a-two-person-electrical-gate-in-software) | Two-person electrical gate in software | Sensors | Accepted |
| [ADR-SEN03](#adr-sen03-kernel-timestamped-gpio-edges-via-libgpiod-v2) | Kernel-timestamped edges via libgpiod v2 | Sensors | Accepted |
| [ADR-SEN04](#adr-sen04-asymmetric-range-filter) | Asymmetric range filter | Sensors | Accepted |
| [ADR-SEN05](#adr-sen05-one-process-owns-the-sensor-readers-re-check-freshness) | One process owns the sensor | Sensors | Accepted |
| [ADR-SEN06](#adr-sen06-own-rplidar-codec-on-pyserial) | Own RPLIDAR codec on pyserial | Sensors | Accepted |
| [ADR-SEN07](#adr-sen07-robot-width-footprint-corridor-and-orientation-fiducial-for-the-lidar) | Robot-width LiDAR corridor + orientation fiducial | Sensors | Accepted |
| [ADR-SEN08](#adr-sen08-lidar-data-never-authorises-motion-grove-stays-the-default) | LiDAR never authorises motion; Grove stays default | Sensors | Accepted |
| [ADR-SEN09](#adr-sen09-never-fill-gate-fields-from-verbal-reports) | Never fill gate fields from verbal reports | Sensors | Accepted (operational) |
| [ADR-PRC01](#adr-prc01-per-package-ci-workflows-with-path-filters) | Per-package CI workflows | Process | Accepted |
| [ADR-PRC02](#adr-prc02-pin-requirements-to-the-bench-mac) | Pin requirements to the bench Mac | Process | Accepted |
| [ADR-PRC03](#adr-prc03-merge-commits-documented-stack-order-user-approval) | Merge commits; documented stack order | Process | Accepted |
| [ADR-PRC04](#adr-prc04-leave-pr-6-open-at-the-deadline) | Leave PR #6 open at the deadline | Process | Accepted |

---

## A. Cross-cutting decisions

### ADR-X01 Pivot from aerial drone search to a wheeled ground robot

- **Context.** The original build guide ([TEAM15_DRONE_SEARCH_BUILD.md](../TEAM15_DRONE_SEARCH_BUILD.md)) describes a simulated drone fleet searching sectors A–Z. Real aircraft were a staff-only upgrade path. On the evening of 7 November the Raspberry Pi was physically moved onto the wheeled RoverC-Pro robot.
- **Decision.** Build a ground robot: Raspberry Pi 5 + IMX708 camera, Mac-side detection, range sensing, a navigation simulator, and a supervisor in front of the RoverC motors. Keep the sighting format with its drone and sector fields.
- **Alternatives.** Continue with simulated drones only; request staff-flown drones.
- **Rationale.** The build guide's "Bottom line" made real aircraft unavailable to teams. A wheeled robot can carry the camera that already worked.
- **Evidence.** Session console log 2026-11-07 23:06 UTC ("moved the Raspberry Pi onto the wheeled robot"); first ranging commit `ff635ad` (23:37 UTC) and first rover commit `241faec` (23:45 UTC); [27 Project timeline](27_PROJECT_TIMELINE.md).
- **Consequences.** Every ground-robot subsystem was built in about 12 hours, which is why most of them are simulation-tested only. The drone simulation continued separately in `team15_starter/` ([ADR-ROV10](#adr-rov10-keep-the-drone-fleet-simulation-separate)).
- **Status.** Accepted.

### ADR-X02 AI is advisory only and has no motor authority

- **Context.** The stack has three AI or AI-adjacent producers: the camera detector and map (`camera_mapping/`), the LiDAR panel and advisory context (`lidar/`), and the Qwen language model (`qwen_advisory/`, `camera_mapping/advisory.py`). None has a validated error rate. A 2B model in particular can produce fluent, wrong text.
- **Decision.** No AI component can command a motor. Every advisory output carries `advisory_only: true` / `authority: "NONE"` or `validated_for_driving: false`. Deterministic code decides corridor status, forward permission and delivery. Qwen only explains. This is enforced by a **static allow-list test**: `rover/tests/test_issue9_fail_closed.py` `test_nothing_outside_the_allow_list_can_reach_the_motor_path` scans every Python file and fails if a file outside `MOTOR_PATH_ALLOWED` names a motor-path symbol.
- **Alternatives.** Let Qwen choose actions or call motion tools; rely on code review alone; an import-graph analysis.
- **Rationale.** No model passed the pre-declared zero-critical-error safety gate ([QWN-029](experiments/reports/QWN-029-safety-regression.md)). A wrong recommendation must be harmless by construction. A substring scan is cheap and catches accidental coupling.
- **Evidence.** PR #14; `camera_mapping/advisory.py` `MOTOR_PATTERN` and `advise`; `test_qwen_output_never_changes_perception_state`; [11 AI agent and tools](11_AI_AGENT_AND_TOOLS.md) §4; [17](17_SAFETY_ARCHITECTURE.md) §8.
- **Consequences.** Qwen adds explanation, never capability. Every display path has a deterministic fallback. The substring scan fires on prose too: commit `1f5c8db` had to reword camera-mapping docstrings that merely *named* motor symbols. It can be evaded by a dynamic import, so it is a tripwire, not a proof.
- **Status.** Accepted.

### ADR-X03 Fail-closed defaults everywhere

- **Context.** Many inputs can be missing, stale or malformed: range readings, power readings, heading, pose, configs, controller acknowledgements.
- **Decision.** Every default is the safe one. Missing configuration values are `None` and make the hardware path refuse (`MotionLimits.min_voltage_v = None` refuses physical motion; `WheelMapping()` has three `None` signs; `mount.height_m` is `null`). `PiRobotIO.read_power()` and `read_heading()` return `None`, and `PiRobotIO.pose()` returns an `UNKNOWN` pose, so real-hardware motion is refused today. The safety tick zeroes output with `_zero_never_raise`, which never raises.
- **Alternatives.** Reasonable-looking defaults (for example a typical camera height, or a typical battery cut-off); fail-open with warnings.
- **Rationale.** A guessed default looks like a measurement and is never revisited. Issue #9 showed how a fail-open check (`is False`) let an unasserted verdict pass ([ADR-ROV02](#adr-rov02-forward-motion-requires-forward_allowed-is-true-issue-9)).
- **Evidence.** `rover/motion.py`, `rover/protocol.py`, `rover/pi_io.py`, `camera_mapping/configs/imx708_robot.json`; PR #14 (`14fde0d`, `test_dead_link_never_crashes_tick_and_stays_latched`).
- **Consequences.** The robot cannot move on real hardware until battery, wheel signs, heading and pose sources are measured. That is intended. The camera map is all-UNKNOWN until the mount is measured.
- **Status.** Accepted.

### ADR-X04 UNKNOWN is never CLEAR

- **Context.** Several sensors have a "nothing came back" outcome that is indistinguishable from "nothing is there": an ultrasonic NO_ECHO, a LiDAR sector with missing returns, a camera that sees no detector-class object.
- **Decision.** Absence of evidence is `UNKNOWN`, and `UNKNOWN` never permits forward motion. On real hardware a Grove `NO_ECHO` is always `UNKNOWN` (`NoEchoPolicy.CLEAR_TO_MAX` is simulation-only and refused with physical IO by `Navigator.__init__`). Camera FREE means only "no detected obstacle" and is never marked while the mount is unmeasured. Weak LiDAR returns count as obstacles, never as clear evidence. `combine()` in `rover/sensors.py` ranks UNKNOWN above BLOCKED above CLEAR.
- **Alternatives.** Treat NO_ECHO as "clear to max range"; mark everything without a detection FREE.
- **Rationale.** A disconnected sensor reads NO_ECHO. The real Grove runs on 2026-11-08 proved this: 0/50 valid, 50/50 NO_ECHO, twice ([RNG-HW-01](experiments/reports/RNG-HW-01-grove-real-hardware-diagnose.md), REAL HARDWARE). A naive policy would have read a dead sensor as an empty corridor.
- **Evidence.** `ranging/reading.py`, `ranging/obstacle.py`, `rover/sensors.py` `assess`, `camera_mapping/local_map.py`, `lidar/footprint.py` `assess_corridor`.
- **Consequences.** The robot stalls in open space, near soft or angled targets, and whenever a sensor is unplugged. Bench tests need a target about 1–1.5 m away. All real camera maps so far are all-UNKNOWN.
- **Status.** Accepted. Vindicated on real hardware by the Grove result.

### ADR-X05 Heavy inference on the Mac, not the Pi

- **Context.** The Pi 5 has four Cortex-A76 cores (a Hailo-8 HAT was fitted but not used). Faster R-CNN and Qwen3.5-2B are both heavy.
- **Decision.** The Pi only captures and streams JPEG frames; detection, depth and Qwen run on the Mac (M4 Pro, MPS). Nothing is installed on the Pi for perception: the sender script is piped over SSH ([ADR-CAM07](#adr-cam07-jpeg-over-an-ssh-session-opened-by-the-mac)).
- **Alternatives.** Hailo-8 on the Pi (no LLM support; would need a model conversion for detection); Pi CPU inference; an installed Pi daemon.
- **Rationale.** Measured: Faster R-CNN median 195–200 ms per 720p frame on MPS (REAL HARDWARE, [CAM-01](experiments/reports/CAM-01-detector-latency-benchmark.md)); Qwen advisory 1.7 s median on the Mac vs 47.6 s median on the Pi with llama.cpp (REAL HARDWARE, [QWN-004](experiments/reports/QWN-004-runtime-benchmarks-mac-pi.md)). Decode is memory-bandwidth-bound ([03](03_MAC_AI_INFERENCE.md) §3).
- **Evidence.** `perception/pi_source.py` docstring; PR #3; [03 Mac AI inference](03_MAC_AI_INFERENCE.md).
- **Consequences.** Perception depends on the network (the Pi dropped off Tailscale several times, F-PROC-1 in [22](22_EXPERIMENTS_AND_FAILURES.md)). Motion decisions must therefore stay on the Pi: the rover rejects range data from another host's clock (`rover/pi_io.py` `clock_domain`). The Mac is a single point of failure for AI features, not for safety.
- **Status.** Accepted.

### ADR-X06 Provenance labels on every result

- **Context.** In a 48-hour build, simulated, mocked and real results sit side by side. Mixing them up would be the easiest way to mislead a judge or a teammate.
- **Decision.** Every data product carries its provenance: sightings carry `source_mode` and camera provenance (`contracts/camera_provenance.py`); camera distances are `CAMERA_ESTIMATE` with label `UNCALIBRATED_ESTIMATE` (`camera_mapping/distance.py` `label_for`); LiDAR panels carry `badge: SIMULATED`; rover status carries hard-coded claims flags (`autonomous_navigation_operational: false`, `physical_motion_verified: false`). Nothing in `camera_mapping/` can produce a `VERIFIED` label, and `dashboard/perception_source.py` `validate_state` rejects any state that claims one.
- **Alternatives.** Free-form status strings; trusting producers.
- **Rationale.** A label that cannot be upgraded by a bug or by a hopeful producer is the cheapest honesty guarantee.
- **Evidence.** The modules above; `test_status_contract.py`; [16 Dashboard](16_DASHBOARD.md) §8.
- **Consequences.** More schema code and more 422 responses during development. Labels in the docs follow the same scheme.
- **Status.** Accepted.

### ADR-X07 No photos in Git; evidence outside the work tree

- **Context.** Camera evidence frames contain people, including bystanders. The repository is public.
- **Decision.** Evidence frames are saved losslessly (PNG) with SHA-256, only outside any Git work tree: `perception/sightings.py` `ensure_evidence_dir` refuses an evidence directory inside Git. `dashboard/tests/test_dashboard.py` `test_no_photos_tracked_in_git` fails if any image is tracked, except an exact-path allow-list of vendored map icons. The dashboard serves photos only from configured directories. Docs cite checksums, never images.
- **Alternatives.** `.gitignore` only; JPEG evidence inside the repo.
- **Rationale.** Privacy of bystanders; integrity of evidence (lossless and hashed).
- **Evidence.** `test_evidence_dir_refused_inside_git`, `test_save_evidence_is_exact_frame`; PR #17 fix `159c678` (`VENDORED_ICONS`).
- **Consequences.** Evidence is local to the capturing Mac and cannot be reviewed from the repo. PR #17 needed a narrow exception for 5 map icons. PR #6 fails the test (5 tracked screenshots) and was left open ([ADR-PRC04](#adr-prc04-leave-pr-6-open-at-the-deadline)). Two CI-skipped tests exist because the private frames are absent on runners ([19](19_TESTING_AND_BENCHMARKS.md) §3.2).
- **Status.** Accepted.

### ADR-X08 Hardware gates in code, with UNVERIFIED configs and negative CI tests

- **Context.** Several teammates could "just try" the hardware. A wrong wire can damage a Pi GPIO; an unproven motor driver can drive the robot off a table.
- **Decision.** Each physical actuator or sensor path refuses to open until a gate object is completely filled from real measurements by a named person, plus an independent verifier where wiring is involved: `rover/protocol.py` `HardwareVerification` (checked by `RoverCAdapter`), `ranging/config.py` `check_electrical`, `lidar/config.py` `check_hardware_gate`. The shipped hardware configs are named `*.UNVERIFIED.json`. CI asserts that `check-config --hardware` **fails** on them (`.github/workflows/lidar.yml`, `.github/workflows/ranging.yml`).
- **Alternatives.** Paper checklists; a single `--i-know-what-im-doing` flag.
- **Rationale.** Make the unsafe path impossible by default, and prove in CI that the gates fire.
- **Evidence.** The modules above; [17](17_SAFETY_ARCHITECTURE.md) §11; [RNG-PF-01](experiments/reports/RNG-PF-01-grove-preflight-gate-runs.md) (10 refusal/acceptance runs).
- **Consequences.** No actuator was proven by the end of the event, but the gates themselves were proven to fire. A gate checks only that fields were filled in, not that they are true (F-SENS-01/05 in [22](22_EXPERIMENTS_AND_FAILURES.md)). The negative CI tests do not show that a correctly verified config would be accepted.
- **Status.** Accepted.

### ADR-X09 Versioned JSON contracts between components

- **Context.** Parallel human and AI sessions built components on separate branches and merged them late.
- **Decision.** Every interface is a versioned JSON schema named `team15.<name>/<n>` (for example `team15.rover_range_fields/1`, `team15.camera_perception/1`, `team15.rover_nav_status/1`, `team15.lidar_panel/1`). Consumers validate strictly and fail closed on unknown or missing fields. Contract tests pin the producer version (`rover/tests/test_ranging_contract.py`).
- **Alternatives.** Shared Python objects; unversioned dicts.
- **Rationale.** Contract tests catch drift between independently developed branches. They did: PR #8's vendored ranging copy failed 4 contract tests because it lacked the SIG-idle gate (F-MRG-4).
- **Evidence.** [contracts/ROVER_NAV_CONTRACT.md](../contracts/ROVER_NAV_CONTRACT.md), [contracts/PI_CAMERA_CONTRACT.md](../contracts/PI_CAMERA_CONTRACT.md); `dac82f4`.
- **Consequences.** It made the late pivot integration possible. It added validation boilerplate. One contract was rewritten after the fact to describe what shipped (`4d3093d`, F-CAM-13).
- **Status.** Accepted.

### ADR-X10 Human in the loop for every consequential decision

- **Context.** Detector false positives are real (a window reflection scored 0.991, [CAM-09](experiments/reports/CAM-09-mac-empty-scene-60s.md)), and the rover has no verified autonomy.
- **Decision.** Every sighting starts `UNCONFIRMED` and changes only via `POST /operator_decision` with an operator name (`core/store.py` `MissionStore.decide`). Every motion needs a named `approve_motion`. Rerouting needs approval (`auto_approve` is simulation-only). Clearing a blocked edge needs an independent source and a named operator (`ObservationLog.clear_edge`).
- **Alternatives.** Auto-confirm high scores; autonomous rerouting.
- **Rationale.** Scores are not probabilities ([ADR-CAM03](#adr-cam03-confidence-null-raw-scores-labelled-as-not-a-probability)); the cost of a false "person confirmed" in rescue is high.
- **Evidence.** `core/store.py`; `rover/motion.py` `approve_motion`; `rover/navigator.py` `NavConfig.auto_approve`; [17](17_SAFETY_ARCHITECTURE.md) §12.
- **Consequences.** Operator workload. No autonomous rescue decisions.
- **Status.** Accepted.

---

## B. Camera perception

### ADR-CAM01 Faster R-CNN ResNet-50 FPN v2 as the person detector

- **Context.** The starter's HOG + linear SVM detector missed seated, lying and back-turned people ([CAM-03](experiments/reports/CAM-03-mac-bench-person-poses.md): HOG 61/97 standing frames, 0/98 seated-from-behind; on the Pi 0/94 seated and lying).
- **Decision.** torchvision `fasterrcnn_resnet50_fpn_v2` with COCO_V1 weights, on the Mac's MPS, is the `PERSON_DETECTOR` (`perception/detectors.py` `TorchPersonDetector`). MobileNet-V3 stays selectable with `--dnn-model`.
- **Alternatives.** HOG + SVM; Haar cascades; Faster R-CNN MobileNet-V3-FPN; YOLOv8s on the Hailo-8.
- **Rationale.** Higher published accuracy (box mAP 46.7 vs 32.8 for MobileNet in the torchvision model table); about 158 ms on MPS on a synthetic input, close to the 5 fps stream; no training needed.
- **Evidence.** PR #3 (`44b7031`); [CAM-01](experiments/reports/CAM-01-detector-latency-benchmark.md); [04 Camera perception](04_CAMERA_PERCEPTION.md).
- **Consequences.** About 200 ms per frame caps the pipeline at about 5 fps. It needs torch on the Mac (about 167 MB of weights). Detection cannot run on the Pi as built. COCO has no "drone" class (F-CAM-16). Reflections still fool it ([ADR-CAM05](#adr-cam05-minimum-trigger-box-height-15-percent-of-the-frame)).
- **Status.** Accepted.

### ADR-CAM02 Run every detector family, label them separately, trigger only on the person detector

- **Context.** The starter's `PersonDetector.detect` was a first-hit cascade: a face or upper-body hit was reported as a person.
- **Decision.** All families (`PERSON_DETECTOR`, `FULL_BODY_HOG`, `UPPER_BODY_HAAR`, `FACE_ONLY`) run on every frame and are labelled separately. Only `PERSON_DETECTOR` triggers a sighting by default (`--trigger person`).
- **Alternatives.** Keep the cascade; merge everything into one "person" label.
- **Rationale.** The face cascade fired on a blank wall in 80/97 frames (F-CAM-02). Keeping the baselines visible lets operators compare.
- **Evidence.** `perception/detectors.py` (`FAMILIES`); PR #3.
- **Consequences.** About 11 ms more compute per frame; clear provenance on the dashboard.
- **Status.** Accepted.

### ADR-CAM03 `confidence: null`, raw scores labelled as "not a probability"

- **Context.** Faster R-CNN's softmax score is not calibrated.
- **Decision.** Sightings set `confidence: null` and carry the raw score with `detector_score_kind`.
- **Alternatives.** Report the score as a confidence.
- **Rationale.** Window reflections scored up to 0.998 (CAM-12).
- **Evidence.** `perception/sightings.py`; [perception/SIGHTING_FORMAT.md](../perception/SIGHTING_FORMAT.md).
- **Consequences.** Operators see raw scores. Score calibration is future work ([25](25_LIMITATIONS_AND_FUTURE_WORK.md)).
- **Status.** Accepted.

### ADR-CAM04 One sighting per continuous presence

- **Decision.** `SightingGate` emits one sighting after 3 consecutive person frames, attaches later frames to it, and re-arms only after 60 s of absence.
- **Alternatives.** One sighting per frame; identity tracking.
- **Rationale.** Avoid alert storms. The 60 s window matches the build guide's (SYNTHETIC) de-duplication window.
- **Evidence.** `perception/sightings.py` `SightingGate`; `perception/tests/test_sightings.py`; every CAM run produced exactly one sighting per continuous presence ([04](04_CAMERA_PERCEPTION.md) §14).
- **Consequences.** Two people in view at once give one sighting. The gate adds 0.4–0.6 s of delay (REAL HARDWARE, CAM-27/28/29).
- **Status.** Accepted.

### ADR-CAM05 Minimum trigger box height 15 percent of the frame

- **Decision.** `--min-box-frac 0.15`: a person box shorter than 15 % of the frame height cannot trigger.
- **Alternatives.** No filter; an ignore mask; a higher score threshold.
- **Rationale.** Removes small reflection boxes (80–130 px at 1080p) without touching the score threshold. On replay, eligible frames fell from 236 to 38 (RECORDED HARDWARE, PR #3).
- **Evidence.** Commit `65684e3`; [CAM-09](experiments/reports/CAM-09-mac-empty-scene-60s.md).
- **Consequences.** Tall reflections still pass (F-CAM-03 remains open). Distant people (box under 108 px at 720p) may not trigger; this is untested.
- **Status.** Accepted.

### ADR-CAM06 Location is the operator-assigned sector only

- **Decision.** A sighting's location is the operator-assigned sector (`SECTOR_ONLY`, `cell_source: OPERATOR_ASSIGNED`). Ingest rejects coordinate fields (`core/ingest.py` `COORDINATE_FIELDS`).
- **Alternatives.** Estimate position from the image.
- **Rationale.** There is no measured camera pose or robot pose; honesty by construction.
- **Consequences.** The dashboard shows "candidate in sector G (assigned)". Camera distances live only in `camera_mapping/` and are UNCALIBRATED.
- **Status.** Accepted.

### ADR-CAM07 JPEG over an SSH session opened by the Mac

- **Context.** The venue Wi-Fi isolated clients, so the Mac could not reach the Pi directly (F-CAM-06).
- **Decision.** The Mac runs `ssh -T -o BatchMode=yes` to the Pi over Tailscale, pipes `SENDER_SCRIPT` to `python3 -` on stdin, and reads a binary stream of `T15HELLO`/`T15FRAME` headers plus JPEG bytes (`perception/pi_source.py` `build_ssh_command`, `PiCameraSource`).
- **Alternatives.** `rpicam-vid` H.264 over TCP; an MJPEG HTTP server; Hailo detection on the Pi sending sightings only.
- **Rationale.** Works through client isolation; installs nothing on the Pi; one-file wire format that cannot drift; per-frame sensor timestamps; BatchMode keeps host-key checks.
- **Evidence.** [CAM-15](experiments/reports/CAM-15-pi-transport-and-first-e2e.md); [02](02_RASPBERRY_PI_SETUP.md) §3–4.
- **Consequences.** About 1.4 Mbit/s at 4.86 fps and about 0.2–0.3 s of relay delay (REAL HARDWARE, session console log 2026-11-07). Depends on a pre-trusted host key.
- **Status.** Accepted.

### ADR-CAM08 `obs_time` is the sensor capture time

- **Decision.** `obs_time` is the Pi's `SensorTimestamp` mapped to wall time. Ingest rejects a Pi sighting whose `obs_time` differs from `camera.capture_time` by more than 2 ms (`contracts/camera_provenance.py` `CAPTURE_TIME_TOLERANCE_S`, `core/ingest.py` `_check_camera`).
- **Alternatives.** Use the Mac's arrival time.
- **Rationale.** A sighting must say when the photo was taken, not when it arrived.
- **Evidence.** `perception/tests/test_pi_source.py` (`test_capture_timestamp_preserved_not_arrival_time`).
- **Consequences.** Delay figures compare two clocks (about ±0.19 s); a `clock_skew` flag is raised if a time is more than 2 s in the future.
- **Status.** Accepted.

### ADR-CAM09 Keep only the newest frame

- **Decision.** `PiCameraSource` keeps only the latest frame; older unprocessed frames are dropped and counted (`frames_dropped_stale`).
- **Rationale.** Bounds latency when the detector is slower than the stream. 1–18 frames were dropped per run (REAL HARDWARE).
- **Consequences.** Processed fps is slightly below the stream rate (4.66–5.01 fps at 5 fps).
- **Status.** Accepted.

### ADR-CAM10 Exactly one software rotation, on the receiver

- **Decision.** One rotation, applied on the Mac; default 180°, verified per mount with `perception/orientation_check.py`. The dashboard never rotates.
- **Alternatives.** Rotate on the Pi; trust the device-tree `Rotation` value.
- **Rationale.** The device-tree value does not follow the physical mount: the camera was upright on the bench (first evidence image inverted, F-CAM-08) and inverted on the robot.
- **Evidence.** `d847270`; [CAM-20](experiments/reports/CAM-20-pi-orientation-check.md).
- **Consequences.** The orientation check must be re-run after any remount.
- **Status.** Accepted.

### ADR-CAM11 Warm up the detector on one discarded real frame

- **Decision.** `perception/live_camera.py` `warm_up` runs the detector once on the first real frame and discards the result.
- **Rationale.** The first MPS call took 3.71 s (kernel compilation), which made the first live run report 0.68 fps (F-CAM-07).
- **Evidence.** `ae8b088`; CAM-17 vs CAM-19.
- **Consequences.** About 0.4 s extra start-up; nothing from that frame is logged or saved.
- **Status.** Accepted.

### ADR-CAM12 Consent-gated live test runner

- **Context.** An "empty scene" run saved a photo of a person who walked in (F-CAM-12, [CAM-23](experiments/reports/CAM-23-pi-live-person-poses.md)).
- **Decision.** A test runner (`perception.live_test`) with typed consent for person scenes, a 10 s countdown with the camera off, and no image storage in no-people modes.
- **Alternatives.** Run `perception/live_camera.py` directly and rely on convention.
- **Evidence.** Local branch `test/camera-live-countdown` (last commit `4fe0508`, 2026-11-08 08:08 UTC). It is **not on `main`** and not pushed.
- **Consequences.** On `main`, `perception/live_camera.py` can still save person images in any run. The consent procedure is not reproducible from `main`.
- **Status.** **Unmerged.** See [25](25_LIMITATIONS_AND_FUTURE_WORK.md).

---

## C. Camera mapping and distance

### ADR-MAP01 Nominal intrinsics from the datasheet and the measured ScalerCrop

- **Context.** Distances need the focal length in pixels. There was no checkerboard and no time for an intrinsic calibration.
- **Decision.** Derive `fx = fy = 1410.7 px` (HFOV 48.8°) from the IMX708 datasheet (1.4 µm pixels, 4.74 mm focal length) **and** the ScalerCrop measured on the Pi: a 1280×720 picamera2 stream is a 3072×1728 centre crop, so one output pixel spans 2.4 sensor pixels (`camera_mapping/config.py` `nominal_imx708_fx`). The config records `source: NOMINAL_DATASHEET` and zero distortion.
- **Alternatives.** Full-sensor focal length (fx ≈ 940 px); a checkerboard calibration.
- **Rationale.** The crop was measured (REAL HARDWARE, session console log 2026-11-08 ~11:08 UTC). Using the full sensor width would have been 1.5× wrong and scaled every known-height distance by 1.5.
- **Evidence.** [05](05_DEPTH_AND_DISTANCE_ESTIMATION.md) §4.1.
- **Consequences.** Intrinsics are nominal; lens distortion is unmodelled.
- **Status.** Accepted.

### ADR-MAP02 Ground-plane ranging only with a measured mount

- **Decision.** `GROUND_PLANE` ranging runs only when `MountGeometry.usable` is true (height and pitch measured). Otherwise it returns `UNKNOWN` with `MOUNT_UNMEASURED`, and no FREE cells, CLEAR verdicts or routes can be produced.
- **Alternatives.** Assume a typical height and pitch.
- **Rationale.** Ground-plane error grows as roughly x²·δα/h. For an illustrative 0.135 m / 4° mount, 1° of pitch error turns 2 m into 1.59 m (SYNTHETIC, [05](05_DEPTH_AND_DISTANCE_ESTIMATION.md) §4.4). A guessed pitch makes the number meaningless.
- **Evidence.** `camera_mapping/config.py` `MountGeometry`; `test_no_route_when_mount_unmeasured`.
- **Consequences.** The shipped mount is unmeasured, so every real map has been all-UNKNOWN and no real BLOCKED or CLEAR verdict exists. The judge-demo steps 2–4 require `calibrate set-mount` first (F-PROC-2).
- **Status.** Accepted.

### ADR-MAP03 Known-height ranging with wide priors, refusing truncated or non-upright boxes

- **Decision.** `Z = fy·H/h_px` with wide class priors (person 1.70 ± 0.12 m, chair 0.88 ± 0.12 m). Refuse boxes within 4 px of **any** frame edge (`BOX_TRUNCATED_BY_FRAME`), non-upright boxes, and boxes under 24 px.
- **Alternatives.** Use any box; narrow priors.
- **Rationale.** A truncated box is shorter than the object, so the range is overestimated, the dangerous direction. On the live Pi on 2026-11-08 ~11:52 UTC a chair cut by the left edge got 7.91 m and 6.76 m (REAL HARDWARE, [MAP-06](experiments/reports/MAP-06-live-pi-run-2-person-chair.md)). The check then covered only top and bottom edges.
- **Evidence.** `camera_mapping/distance.py` `known_height`; `73539a7`; `test_known_height_refuses_side_truncated_box`.
- **Consequences.** On a low camera, standing people closer than about 8 m are always head-clipped and refused. Every person box in every recorded run was refused.
- **Status.** Accepted.

### ADR-MAP04 Fuse only when every pair agrees within 2σ

- **Decision.** `fuse` combines estimates by inverse-variance weighting only if every pair satisfies `|d_a − d_b| ≤ 2·sqrt(σ_a² + σ_b²)`; otherwise the result is `REJECTED` (`INCONSISTENT_METHODS`).
- **Alternatives.** Always average; pick the lowest-σ method.
- **Rationale.** Two confident methods that disagree mean an assumption is broken; averaging hides it. The first version compared only the first two methods; the independent review fixed it to all pairs (`c7ed6c5`).
- **Evidence.** `test_inconsistent_methods_are_rejected`, `test_three_methods_fuse_only_if_all_agree`.
- **Consequences.** Fewer, more honest numbers.
- **Status.** Accepted.

### ADR-MAP05 Monocular depth is an optional, unfused cross-check

- **Decision.** Depth Anything V2 (Small) runs only if `--depth` is set. The relative model is never converted to metres. The metric-indoor model is shown as `METRIC_UNVALIDATED` and is fused only if `depth_model_validated` is true, which only `calibrate report --apply` can set. No fine-tuning.
- **Alternatives.** Use the metric output directly; fine-tune on our data.
- **Rationale.** No ground truth; a single image has an unresolvable scale ambiguity; a 10–15 cm viewpoint is rare in indoor training data.
- **Evidence.** `camera_mapping/depth.py`; [MAP-03](experiments/reports/MAP-03-mono-depth-recorded-frame.md) (0.41 m for one recorded person, no ground truth, RECORDED HARDWARE).
- **Status.** Accepted.

### ADR-MAP06 Three-state robot-relative grid with positive invalidation; no SLAM

- **Decision.** `LocalMap` is a 40×40 grid of 0.1 m cells in the robot frame with states UNKNOWN / FREE / OCCUPIED. FREE expires after 1.5 s. Cells behind or inside a new detection are invalidated in the same frame (`last_obs[masked] = −inf`). Robot motion clears the map instead of shifting it.
- **Alternatives.** Log-odds occupancy; SLAM.
- **Rationale.** No pose source and no calibrated sensor model, so probabilities would be invented. The review found that relying on expiry alone left 96 FREE cells behind a new chair for up to 1.5 s (F-MAP-3, SYNTHETIC repro).
- **Evidence.** `camera_mapping/local_map.py`; `c7ed6c5`; `test_space_behind_new_obstacle_loses_old_free_immediately`.
- **Consequences.** The map is valid only for a stationary robot. `camera_mapping/live.py` never passes `robot_moving`, so the demo requires the robot to stand still.
- **Status.** Accepted.

### ADR-MAP07 Camera never becomes a range reading

- **Decision.** `camera_mapping/rover_adapter.py` `as_range_reading` always raises `NotARangeSensor`. The adapter emits only bearing-only detections and `UNCONFIRMED` observations.
- **Alternatives.** Feed camera distances into the forward-motion gate.
- **Rationale.** Camera ranging is unvalidated and only covers detector classes.
- **Consequences.** The forward-motion gate still needs a real range sensor, and none is working ([ADR-SEN08](#adr-sen08-lidar-data-never-authorises-motion-grove-stays-the-default)).
- **Status.** Accepted.

### ADR-MAP08 The dashboard validates perception state and judges freshness itself

- **Decision.** `dashboard/perception_source.py` `validate_state` checks every posted state (`kind: CAMERA_ESTIMATE`, motion authority NONE, no `VERIFIED` labels) and returns 422 on a violation. Freshness is computed on the dashboard's own clock; a state older than 2 s is shown as STALE with an all-UNKNOWN map. The browser applies the same rule if polling fails.
- **Rationale.** Prevent mislabelled or upgraded provenance; a stale view must degrade every derived panel, not just the headline (F-MAP-4).
- **Status.** Accepted.

### ADR-MAP09 Single-producer lock on perception posts

- **Context.** On 2026-11-08 06:52 ET a stray `--source replay` runner and the live Pi runner posted to the same dashboard, which then alternated LIVE and RECORDED states ([DSH-02](experiments/reports/DSH-02-dashboard-duplicate-producer.md)).
- **Decision.** The dashboard accepts frames from one producer at a time and answers others with HTTP 409; the runner exits with code 4 on conflict. Takeover is allowed after 4 s of silence.
- **Alternatives.** Accept all; last writer wins.
- **Evidence.** `73539a7`; `dashboard/perception_source.py` `ConflictingProducer`; `camera_mapping/live.py` `ProducerConflict`.
- **Consequences.** A second runner fails fast and visibly.
- **Status.** Accepted.

---

## D. Planning

### ADR-PLN01 Deterministic corridor verdict with two-mode advisory routes

- **Decision.** `camera_mapping/assess.py` `assess` computes CLEAR / CAUTION / BLOCKED / UNKNOWN from fixed rules with human-readable reasons. `suggest_route` runs grid A\* first in `SUPPORTED` mode (FREE cells only) and then in `NEEDS_OBSERVATION` mode (UNKNOWN cost 25). Routes are always `validated_for_driving: false`, and no consumer executes them.
- **Alternatives.** An LLM or learned policy decides; a single planning mode; executable waypoints.
- **Rationale.** Auditability; telling "observed free" apart from "unobserved" for the operator. Live run 1 suggested a route through unobserved space in all 117 states because the gate on the mount was missing (F-MAP-1); the shipped code returns `NO_SUPPORTED_ROUTE` when the mount is unmeasured.
- **Evidence.** [07](07_PATH_PLANNING.md) Parts A–B; `test_no_route_when_mount_unmeasured`.
- **Consequences.** Dashed versus solid routes; no CLEAR, CAUTION, BLOCKED or alternate route has ever come from real data.
- **Status.** Accepted.

### ADR-PLN02 Dijkstra on the synthetic trail graph; A\* is a benchmark only

- **Context.** The mission graph (`fixtures/trail_graph_synthetic.json`, 26 nodes, 15 edges, SYNTHETIC) has no coordinates.
- **Decision.** `planner/route.py` `compute_route` (Dijkstra with a binary heap) is the route of record for the dashboard and the rover navigator. `planner/astar.py` `astar_route` with ALT landmarks is kept as a verified benchmark and never replaces it.
- **Alternatives.** A\* as primary; a Euclidean heuristic (impossible without coordinates).
- **Rationale.** Dijkstra is simple and exact; the graph is tiny, so speed is irrelevant. ALT is proven equal on every ordered pair under five blocked-edge sets (`test_astar_matches_dijkstra`).
- **Evidence.** `planner/astar.py` docstring; [PLN-01](experiments/reports/PLN-01-trail-graph-route-tests.md) (19 tests, SYNTHETIC).
- **Consequences.** One code path for navigation. Distances are synthetic; nothing is known about real terrain.
- **Status.** Accepted.

### ADR-PLN03 Reroute by retreating to the previous node; no local bypass

- **Decision.** When an edge is confirmed blocked, the navigator marks it in `ObservationLog`, verifies the detour, retreats to the previous node, and replans with Dijkstra. It never side-steps around an obstacle.
- **Alternatives.** Local bypass around the obstacle.
- **Rationale.** One forward ranger cannot measure an obstacle's depth or the space beside it.
- **Evidence.** `rover/navigator.py`; [docs/rover/SAFETY_AND_LIMITATIONS.md](rover/SAFETY_AND_LIMITATIONS.md) §3; scenarios B–E ([SIM-01](experiments/reports/SIM-01-rover-scenario-suite.md), SIMULATED).
- **Consequences.** Longer routes (scenario C: 46 m planned after the reroute, 83.9 m simulated travel).
- **Status.** Accepted.

---

## E. Qwen, LoRA and RAG

### ADR-QWN01 Qwen3.5-2B as the advisory model

- **Decision.** Qwen3.5-2B (Apache-2.0, natively multimodal).
- **Alternatives.** Qwen3.5-0.8B (about 30 % faster, half the memory); 4B; cloud models.
- **Rationale.** About 2.2 GiB at Q4, so it also runs on the Pi; offline; the licence lets the adapter be published.
- **Evidence.** `$QWEN_WORKSPACE/docs/MODEL_SELECTION.md`; [QWN-004](experiments/reports/QWN-004-runtime-benchmarks-mac-pi.md).
- **Consequences.** Untuned, 2B does not follow the tool protocol without a grammar or LoRA. The 0.8B model was never evaluated on a frozen set.
- **Status.** Accepted.

### ADR-QWN02 Ollama Q4 with a JSON grammar on the Mac; thinking mode off

- **Decision.** Serve with Ollama (Q4_K_M) on the Mac, with JSON-schema-constrained output and `think: False`.
- **Alternatives.** llama.cpp on the Pi (47.6 s per advisory); HF transformers on the Mac (slower, more memory, no grammar).
- **Rationale.** 1.7 s median on the Mac (REAL HARDWARE); the grammar guarantees parseable output; disabling thinking saves latency and avoids leaking reasoning text.
- **Evidence.** [QWN-004](experiments/reports/QWN-004-runtime-benchmarks-mac-pi.md), [QWN-018](experiments/reports/QWN-018-runtime-comparison-audit.md).
- **Consequences.** Constrained and unconstrained results are not comparable: base Qwen scored 0/230 under HF without a grammar (a format failure, no parseable step) but 39/230 (no RAG) and 56/230 (RAG) under Ollama's grammar. Every result must state runtime, weights, grammar and sampler. This runtime cannot load a LoRA adapter ([ADR-QWN07](#adr-qwn07-the-live-demo-runs-base-qwen--rag-not-the-lora-adapter)).
- **Status.** Accepted.

### ADR-QWN03 Bounded tool loops with read-only or request-only tools, and a minimum-evidence fallback

- **Decision.** Agent tools are read-only or request-only (the LiDAR agent contract has no motion tool at all); one tool call per step; hard budgets (10 or 12 calls, 120 s); a deterministic gate validates every step. If the model fails, the orchestrator fetches the minimum evidence itself (robot, camera, sectors, review) and shows the deterministic advisory.
- **Alternatives.** Free-form plans; model self-checks; a fallback built only from tools the model chose to call.
- **Rationale.** Safety must hold for every model output, not just good ones ([11](11_AI_AGENT_AND_TOOLS.md) §4). The original fallback understated a hazard (F10); after the fix, 0/120 displayed advisories were more permissive than the reference.
- **Evidence.** `$QWEN_WORKSPACE/rescue_qwen/agent.py`; [QWN-028](experiments/reports/QWN-028-agentic-tool-traces.md) (0 forbidden tool calls in 665, SIMULATED).
- **Consequences.** Model-driven agents completed 0/120 episodes; the value today is bounded orchestration and audit, not autonomy.
- **Status.** Accepted.

### ADR-QWN04 SQLite FTS5 BM25 retrieval with a bounded context and an injection quarantine

- **Decision.** Stdlib SQLite FTS5 (BM25, `porter unicode61`); at most 4 chunks, 2,600 characters and 2 chunks per document; sources wrapped as data; chunks matching an injection regex quarantined; cited ids must be retrieved ids.
- **Alternatives.** `rank_bm25`; MiniLM embeddings; hybrid RRF; unbounded top-k.
- **Rationale.** FTS5 was best or tied on every metric (hit@4 18/20, MRR@10 0.852, 0.17 ms per query), needs nothing extra, and runs on the Pi ([QWN-002](experiments/reports/QWN-002-rag-retrieval-eval.md), 20 hand-labelled queries, 34-document corpus).
- **Consequences.** Lexical retrieval misses paraphrases. The comparison was not re-run on the 47-document corpus. RAG raised forbidden claims for the untuned model on delivery and LiDAR (F14), so retrieval is grounding, not safety.
- **Status.** Accepted.

### ADR-QWN05 LoRA on every language projection, vision frozen, assistant-only loss

- **Decision.** LoRA r = 16, α = 32, dropout 0.05, on `q/k/v/o_proj`, the Gated-DeltaNet projections (`in_proj_qkv`, `in_proj_z`, `out_proj`) and the MLP of every layer; vision tower, embeddings and `lm_head` frozen; 15.63 M trainable parameters. Loss on assistant tokens only, with `logits_to_keep`.
- **Alternatives.** Attention-only LoRA (would skip 18 of 24 layers' token mixing); full fine-tuning; QLoRA (needs CUDA, not available on MPS).
- **Rationale.** Memory on a 24 GB Mac; the hybrid architecture. Full-vocabulary logits made the smoke run use 21.7–24.4 GB and swap (F1); `logits_to_keep` brought it to 7–8 GB with an identical loss (1.782 vs 1.782).
- **Evidence.** `LORA_EXPERIMENT_CONFIG.yaml`; [09](09_LORA_TRAINING.md) §2–4; [QWN-013](experiments/reports/QWN-013-lora-run2.md).
- **Consequences.** The 7 Co-GLANCE images (part of the 689 trained records) train only the language side.
- **Status.** Accepted.

### ADR-QWN06 Frozen test sets, validation-only selection, and a safety gate in eligibility

- **Decision.** Hash and freeze every test set before any model run. Select checkpoints on validation only, with rules committed before training. A checkpoint is ineligible if it makes more unsafe motion requests or unsupported claims than the base model. Run each selected checkpoint once on the frozen set.
- **Rationale.** Avoid overfitting and selection bias; a better-scoring but less safe checkpoint must lose.
- **Evidence.** `FROZEN_MANIFEST.json`; `select_checkpoint.py`; `select_lidar_ckpt.py` (rules committed 00:52 ET, before pilot checkpoints were evaluated). ckpt-0022/0044/0066 were excluded for unsafe motion; every LiDAR pilot checkpoint was excluded ([QWN-024](experiments/reports/QWN-024-lidar-lora-pilot.md)).
- **Consequences.** The LiDAR pilot was correctly rejected. A tie (ckpt-0088 vs ckpt-0089 at 1.851) was broken by list order, not a declared rule (F19).
- **Status.** Accepted.

### ADR-QWN07 The live demo runs base Qwen + RAG, not the LoRA adapter

- **Context.** ckpt-0088 scored 218/230 on the frozen synthetic mission benchmark (SYNTHETIC, [QWN-017](experiments/reports/QWN-017-frozen-mission-230.md)) and was published.
- **Decision.** The camera demo uses base Qwen3.5-2B + RAG through Ollama, behind the guard and deterministic policies.
- **Alternatives.** Serve the adapter through an HF/PEFT backend, or merge it and convert to GGUF.
- **Rationale.** Three independent blockers ([08](08_QWEN_MODEL.md) §5): (1) Ollama 0.40.2 refuses adapters and `rescue_qwen.service` has only Ollama and OpenAI-compatible backends; merge + GGUF tooling was not installed; (2) the adapter learned the mission tool-step task, not the camera advisory task, and showed no transfer (LiDAR 0/60 schema-valid, 14/60 over-permissive); (3) the pre-declared safety promotion gate failed. Accuracy without RAG was never measured.
- **Consequences.** The 218/230 result is not what a judge sees live. Demo talking points must not claim the fine-tuned model is running.
- **Status.** Accepted.

### ADR-QWN08 Publish only the selected adapter; keep data and corpus private

- **Decision.** Publish ckpt-0088 only (Hugging Face `MOHDMUBASHIR/team15-qwen3.5-2b-rescue-mission-lora`, revision `21013d4`) with checksums. Keep training data, the RAG corpus, benchmarks and pilot checkpoints private.
- **Rationale.** Reproducibility of the artefact versus corpus licences (several are NC or ND) and privacy.
- **Evidence.** [QWN-031](experiments/reports/QWN-031-hf-publication.md); `.gitignore` (`*.safetensors`, `*.gguf`).
- **Consequences.** The published score cannot be reproduced without the private corpus; the model card says so.
- **Status.** Accepted.

### ADR-QWN09 Delivery decisions stay deterministic

- **Decision.** No delivery LoRA was trained; delivery decisions are made by deterministic code, and Qwen is limited to explanation text.
- **Rationale.** The best raw delivery accuracy was 17/77 (SIMULATED, [QWN-019](experiments/reports/QWN-019-delivery-frozen-eval.md)); the review-first instruction.
- **Evidence.** [QWN-030](experiments/reports/QWN-030-delivery-lora-not-run.md).
- **Status.** Accepted.

### ADR-QWN10 Do not patch the guard to the frozen set's wording

- **Decision.** One reworded unsafe request ("roll the rover over to him") was missed by the guard regex and the model. The regex was deliberately **not** patched to that wording.
- **Rationale.** Patching to a frozen item overfits the test set; the controller and operator remain the authority.
- **Evidence.** `$QWEN_WORKSPACE/docs/BASELINE_VS_RAG.md` (F22).
- **Status.** Accepted.

### ADR-QWN11 Launch the Qwen service through an in-repo launcher

- **Context.** Every RAG request to `rescue_qwen.service` returned HTTP 500 (`sqlite3.ProgrammingError`): the in-memory FTS index was built in the main thread and used from FastAPI worker threads (F16, 2026-11-08).
- **Decision.** `camera_mapping/qwen_launcher.py` starts the service with `check_same_thread=False` and refuses to run unless `sqlite3.threadsafety == 3`. The root fix was put on a Qwen-workspace branch (`fix/rag-index-threading`, `9619bf9`) for its owner to review.
- **Alternatives.** Patch the Qwen workspace in place; drop RAG from the demo.
- **Rationale.** Ownership boundary: the Qwen workspace belongs to another workstream; minimal change.
- **Evidence.** PR #16; [16](16_DASHBOARD.md) §10.
- **Consequences.** Depends on the SQLite build mode. The proper fix is **unmerged**.
- **Status.** Accepted (workaround).

### ADR-QWN12 Stdlib-only `qwen_advisory/` port with its own CI

- **Decision.** The repo holds only the LiDAR advisory contract and guard (`qwen_advisory/lidar.py`, `qwen_advisory/client.py`), stdlib-only, tested by a path-filtered workflow (`.github/workflows/qwen.yml`, 23 tests). The RAG and training code stay in the Qwen workspace.
- **Rationale.** No new dependencies; no model needed in CI. Parity 314/314 against the workspace implementation.
- **Evidence.** PR #12.
- **Status.** Accepted.

---

## F. Rover motion and the StickC bridge

### ADR-ROV01 USB-serial StickC bridge with a firmware watchdog

- **Context.** The RoverC-Pro's STM32 is an I²C slave at `0x38` mastered by the M5StickC. The STM32 documents no watchdog, so if the commanding computer dies the wheels may keep turning.
- **Decision.** The Pi talks to the StickC over USB serial (115200 baud, ASCII frames with CRC-8, sequence numbers, sessions). Draft StickC firmware relays only registers `0x00–0x03` and zeroes the motors if no accepted frame arrives for 250 ms (`firmware/stickc_roverc_bridge/stickc_roverc_bridge.ino`; Pi side `rover/bridge.py` `BridgeTransport`).
- **Alternatives.** The Pi as a second I²C master via the Grove port (two masters unsupported); StickC firmware over Wi-Fi UDP; a host-side watchdog only.
- **Rationale.** Only a controller-side timeout can stop the wheels when the Pi or link dies; USB is wired and deterministic.
- **Evidence.** PR #15; [13](13_M5STICKC_BRIDGE.md); [BRG-01](experiments/reports/BRG-01-bridge-watchdog-mocked-tests.md) (63 MOCKED tests against a Python model of the firmware).
- **Consequences.** The firmware has never been compiled or flashed. The controller was **not detected** on the team Pi or the main Mac in the reported checks ([ROV-02](experiments/reports/ROV-02-controller-connectivity-inspection.md)). Residual risks: DTR/RTS auto-reset and download mode.
- **Note on a parallel effort.** The unmerged open PR #6 (branch `culubo/sensor-id-specs`, commit `45481e4`) contains a separate keyboard and Wi-Fi control path (roverc_usb firmware, a keyboard control script and a mission-control folder, all on the PR #6 branch only). Its README says a teammate uploaded a USB receiver firmware image to a StickC Plus from their own Mac, that MOVE acknowledgements are register read-backs which "does not prove wheel rotation", and that powered direction and stop behaviour is a pending gate. None of it is on `main`, it has no link-loss watchdog review, and wheel movement remains **NOT VERIFIED**.
- **Status.** Accepted (draft firmware, not flashed). Reconciling the two firmware efforts is future work ([25](25_LIMITATIONS_AND_FUTURE_WORK.md)).

### ADR-ROV02 Forward motion requires `forward_allowed is True` (Issue #9)

- **Context.** Before PR #14, `MOVE_FORWARD` was refused only on an explicit `forward_allowed is False`; `None` passed (Issue #9).
- **Decision.** Forward motion needs assessment CLEAR **and** `forward_allowed is True` **and** a fresh reading **and** (on hardware) a healthy service status. A hardware `RangeReading` without a verdict cannot be constructed.
- **Alternatives.** Veto-only (`is False`).
- **Rationale.** The guarantee must not depend on every producer remembering to set the field. Gates require positive evidence, not the absence of a veto.
- **Evidence.** PR #14 (`1b942e3`, `7efa570`); `rover/tests/test_issue9_fail_closed.py` (40 tests, MOCKED); [ROV-01](experiments/reports/ROV-01-issue9-fail-closed-tests.md).
- **Consequences.** The simulator must assert verdicts explicitly.
- **Status.** Accepted.

### ADR-ROV03 Latch and require an operator reset; never auto-restart

- **Decision.** A safety stop (`COMMS_LOST`, `SENSOR_STALE`, `DRIVER_FAULT`, `POWER_UNKNOWN`, `UNDERVOLTAGE`, `LOCALIZATION_LOST`, `ESTOP`) latches, zeroes output and revokes approval (`SafetySupervisor._latch`). Recovery needs `reset_latch(operator)` and a fresh `approve_motion(operator)`.
- **Alternatives.** Auto-resume when the fault clears.
- **Rationale.** A recovered sensor or link does not prove the situation is safe.
- **Evidence.** Scenario G ([SIM-01](experiments/reports/SIM-01-rover-scenario-suite.md)); the Issue #9 test that the robot does not restart when the verdict returns.
- **Consequences.** Transient faults halt missions; with a 0.1 s ping interval against 0.20 s motion freshness, one or two missed pings latch `SENSOR_STALE` (F-ROV-10, untested on hardware).
- **Status.** Accepted.

### ADR-ROV04 Normalised, single-axis, bounded-duration motion primitives

- **Decision.** Commands are normalised (caps 0.30), single-axis (`MOVE_FORWARD`, `TURN_LEFT`, ...), last at most 1.0 s, and ramp up at most 1.0 per second but stop instantly. The navigator issues 0.15 s pulses, each after a fresh check. `MOVE_TO_WAYPOINT` is always refused.
- **Alternatives.** Physical units; continuous velocity streaming; combined motions.
- **Rationale.** No encoders, so no calibration to m/s; short pulses limit exposure.
- **Evidence.** `rover/motion.py` `MotionLimits`, `SafetySupervisor._ramp`; [12](12_ROVERC_MOTOR_CONTROL.md) §7.
- **Consequences.** No arc turns; what 0.30 means in m/s on the real robot is NOT MEASURED.
- **Status.** Accepted.

### ADR-ROV05 Port the vendor mixer and require three measured signs

- **Decision.** `rover/protocol.py` `library_mix` is a byte-for-byte port of the M5Stack `setSpeed(x, y, z)`. `body_to_motor_speeds` refuses to run until a `WheelMapping` with three measured signs and evidence exists.
- **Alternatives.** A textbook mixer; a per-wheel permutation table.
- **Rationale.** Match the vendor reference exactly; the register-to-wheel mapping is undocumented, so signs must be measured.
- **Consequences.** If the bench test reveals a register permutation, three signs cannot fix it and the code must change ([12](12_ROVERC_MOTOR_CONTROL.md) §5.1).
- **Status.** Accepted.

### ADR-ROV06 Scan by rotating the chassis on its wheels; closed-loop heading only

- **Context.** One forward ultrasonic sensor and no pan servo.
- **Decision.** To look left, right or back, the robot rotates in place (`Navigator._directional_scan`, `_sweep`, `_face`), with closed-loop heading control, bounded segments of at most 90° and a stall timeout. The servo registers are never written. Scanning is refused without a measured heading.
- **Alternatives.** A servo pan; timed open-loop turns.
- **Rationale.** Timed turns are not angles; the servo path was deliberately kept unreachable.
- **Consequences.** On real hardware scanning is refused today, because `PiRobotIO.read_heading()` returns `None`. The StickC IMU has never been read or calibrated.
- **Status.** Accepted.

### ADR-ROV07 Only simulator ground-truth pose authorises autonomous motion

- **Decision.** `TRUSTED_FOR_MOTION = {SIM_TRUTH}`. `OPERATOR_CONFIRMED` poses are for stationary use only. On the Pi the navigator raises `POSE_UNKNOWN` and allows operator-assisted waypoints only.
- **Rationale.** No encoders, no localisation.
- **Evidence.** `rover/navigator.py`.
- **Status.** Accepted.

### ADR-ROV08 Per-process random session in the bridge ARM

- **Decision.** Each `BridgeTransport` picks a random 8-hex session; the firmware accepts motion only from the session that armed it and zeroes and disarms on a foreign session.
- **Rationale.** A restarted or duplicate Pi process must never drive motors armed by an earlier one, even inside the 250 ms watchdog window.
- **Evidence.** PR #15; restart and reconnect tests in `rover/tests/test_bridge.py`.
- **Status.** Accepted.

### ADR-ROV09 Separate freshness limits for motion and display

- **Decision.** Motion requires a range reading at most 0.20 s old (`MotionLimits.sensor_max_age_s`); display tolerates 0.5 s.
- **Rationale.** A display may lag; motion may not.
- **Evidence.** PR #8 description; `ObstacleConfig`.
- **Status.** Accepted.

### ADR-ROV10 Keep the drone-fleet simulation separate

- **Decision.** The Aurora drone-fleet simulation (`team15_starter/`) shares no imports with the ground-robot stack. It is not in `pytest.ini` `testpaths` or in any workflow.
- **Rationale (inferred from history, not a recorded decision).** It forked from the initial commit and merged at the end (PR #17).
- **Consequences.** Its results are not comparable with the rover's, and its tests are not CI-gated ([19](19_TESTING_AND_BENCHMARKS.md) §3).
- **Status.** Accepted (inferred).

---

## G. Range sensors: Grove ultrasonic and RPLIDAR C1

### ADR-SEN01 Power the Grove ranger from 3.3 V

- **Decision.** VCC from Pi pin 1 (3V3); require a V2.x board; 1 kΩ series resistor on SIG. 5 V is allowed only with a bidirectional BSS138 level shifter.
- **Alternatives.** 5 V + shifter (allowed fallback); 5 V + divider (rejected: SIG is bidirectional); 5 V + resistor only (rejected: about 1.4 mA into the clamp diode); the RoverC Grove port (rejected: it is I²C).
- **Rationale.** SIG high is about VCC (Seeed schematic) and Pi GPIO is not 5 V tolerant.
- **Evidence.** [ranging/WIRING.md](../ranging/WIRING.md) §2; `ranging/config.py` `check_electrical`.
- **Consequences.** 0.1 V margin above the 3.2 V minimum; range at 3.3 V may be reduced. Whether this contributed to the 0/50 result is UNKNOWN.
- **Status.** Accepted.

### ADR-SEN02 A two-person electrical gate in software

- **Decision.** `check_electrical` refuses GPIO unless every checklist field is recorded and a **different** independent verifier is named. It runs in `validate()` and again in `GpiodDriver.__init__`, and the CLI also needs `--hardware`. SIG idle above 1.2 V (`SIG_IDLE_MAX_V`) is refused, because the schematic shows a 10 kΩ pull-down.
- **Alternatives.** Documentation only; one verifier.
- **Evidence.** PR #7 (`19c43d8`, `82f5079`, `ee56359`); [RNG-PF-01](experiments/reports/RNG-PF-01-grove-preflight-gate-runs.md).
- **Consequences.** It worked as designed. It cannot check the truth of what is typed in, and it does not check the series resistance (F-SENS-05).
- **Status.** Accepted.

### ADR-SEN03 Kernel-timestamped GPIO edges via libgpiod v2

- **Decision.** `ranging/drivers.py` `GpiodDriver` requests the line with both-edge detection and `CLOCK_MONOTONIC` event timestamps and computes the echo width from kernel timestamps; the pure function `echo_from_events` is testable without a Pi.
- **Alternatives.** RPi.GPIO (does not support the Pi 5's RP1); lgpio; Python busy-wait polling.
- **Rationale.** Timing precision independent of Python scheduling.
- **Consequences.** Needs the kernel ≥ 6.6 RP1 layout; the identity check refuses other chips. The real SIG release was measured at 65–96 µs (REAL HARDWARE, 2026-11-08).
- **Status.** Accepted.

### ADR-SEN04 Asymmetric range filter

- **Decision.** Decision range = min(latest valid reading, median of 5). Relaxing to a less restrictive state needs threshold + 5 cm for 3 consecutive readings.
- **Rationale.** A single short reading causes a safe stop; a single long spike cannot clear a block.
- **Evidence.** `ranging/obstacle.py` `ObstacleAssessor`; `test_single_long_spike_cannot_clear_a_block`, `test_rapid_approach_blocks_on_the_next_ping`.
- **Consequences.** Near-spike noise can cause false stops; accepted.
- **Status.** Accepted.

### ADR-SEN05 One process owns the sensor; readers re-check freshness

- **Decision.** `ranging/service.py` `RangeService` owns the GPIO line and publishes a snapshot to `/dev/shm`, HTTP on 127.0.0.1 and JSONL. `RangeClient` and `apply_freshness` recompute age on the reader side. Navigation consumes the versioned `team15.rover_range_fields/1` via `ranging/rover_io.py` `GroveRangeIO`, never raw snapshots.
- **Rationale.** No GPIO contention; a crashed service becomes UNKNOWN within 0.5 s.
- **Evidence.** [ranging/INTEGRATION.md](../ranging/INTEGRATION.md); PR #8 review (CHANGES REQUIRED at `cba304d`, accepted at `09333d3`).
- **Consequences.** The rover must run on the same Pi. One open contract item: `snapshot_to_rover_fields` substitutes the current time when `mono_ns` is missing (F-ROV-9; [25](25_LIMITATIONS_AND_FUTURE_WORK.md)).
- **Status.** Accepted.

### ADR-SEN06 Own RPLIDAR codec on pyserial

- **Decision.** A small legacy-protocol codec (`lidar/protocol.py`) and driver (`lidar/driver.py` `RplidarC1Driver`) on pyserial.
- **Alternatives.** The SLAMTEC C++ SDK (native build + FFI, no CI); the PyPI `rplidar` package (unmaintained; drives the motor with DTR).
- **Rationale.** Small, auditable, fully mockable in CI.
- **Evidence.** [docs/lidar/LIDAR_C1_DRIVER.md](lidar/LIDAR_C1_DRIVER.md) §1.
- **Consequences.** Whether the C1M1-R2 accepts the legacy SCAN command is **UNVERIFIED**; the fallback is the SDK's `ultra_simple`.
- **Status.** Accepted.

### ADR-SEN07 Robot-width footprint corridor and orientation fiducial for the LiDAR

- **Decision.** `lidar/footprint.py` `assess_corridor` checks a bumper-referenced corridor as wide as the robot plus margin (100 % ray evidence in the near zone, at least 90 % with gaps of at most 2° in the far zone). `check_orientation` requires a measured body fiducial to appear where the mount predicts; `forward_offset_deg` has no default.
- **Alternatives.** The original FRONT ±22.5° sector minimum.
- **Rationale.** A 45° wedge is only ±0.14 m wide at 0.35 m and misses wheel-edge obstacles (simulation scenarios 21 and 22).
- **Evidence.** Commit `9027320`; [docs/lidar/GROVE_TO_LIDAR_MIGRATION.md](lidar/GROVE_TO_LIDAR_MIGRATION.md); 29 corridor tests ([LDR-SIM-01](experiments/reports/LDR-SIM-01-lidar-simulation-scenario-suite.md), SIMULATED).
- **Consequences.** Needs a measured footprint, occlusion and fiducial, all unset, so the corridor is UNKNOWN on hardware.
- **Status.** Accepted.

### ADR-SEN08 LiDAR data never authorises motion; Grove stays the default

- **Decision.** In PR #11, `HARDWARE_UNVERIFIED` LiDAR data never sets `forward_motion_allowed`; `HARDWARE_VERIFIED` is reserved and nothing sets it. The LiDAR uses its honest source name `rplidar-c1`, which today's rover rejects. Grove remains the default range sensor; migration is staged A–F and needs an explicit decision.
- **Rationale.** No motion from an uncalibrated sensor; no source spoofing.
- **Evidence.** `lidar/adapters.py`, `lidar/processing.py`; `lidar/tests/test_contracts_compat.py`.
- **Consequences.** Both range sensors are unverified on hardware: Grove 0/50 valid, the LiDAR never queried.
- **Status.** Accepted.

### ADR-SEN09 Never fill gate fields from verbal reports

- **Decision (operational, 2026-11-08).** The assistant entered only explicitly supplied measured values, refused placeholders and verbal "fixed" reports, asked directly about the independent check, and ran clearly labelled SIMULATED fallbacks when a gate failed.
- **Evidence.** Session console log 2026-11-08 08:56, 10:04, 10:26–10:43 UTC; [14](14_GROVE_ULTRASONIC.md) §14.2.
- **Consequences.** The real Grove runs happened only after explicit values arrived. No fabricated hardware result exists. The lesson recorded: ask for a header close-up photo first.
- **Status.** Accepted (operational practice).

---

## H. Process, CI and repository policy

### ADR-PRC01 Per-package CI workflows with path filters

- **Decision.** `ci`, `perception`, `lidar`, `ranging` and `qwen-advisory` are separate workflows with path filters, instead of adding every package to `pytest.ini`.
- **Rationale.** PRs promised not to touch `pytest.ini` or `requirements.txt`, to avoid cross-PR conflicts.
- **Evidence.** PR #7, #11, #12 descriptions; `.github/workflows/`.
- **Consequences.** On `d1b607a` only `ci` and `perception` ran. `team15_starter/tests` has no workflow (F-CI-5). Every commit runs workflows twice, for push and PR (F-CI-4).
- **Status.** Accepted.

### ADR-PRC02 Pin requirements to the bench Mac

- **Decision.** Pin `requirements.txt` to the versions on the bench Mac (for example OpenCV 4.13.0.92); `perception.yml` separately tests the range `>=4.8,<5` on Python 3.13.
- **Rationale.** The first CI run failed because unpinned OpenCV 5 removed `HOGDescriptor` (F-CI-1, [CI-001](experiments/reports/CI-001-ci-regression-history.md)).
- **Evidence.** `a36a658`, `cee428e`.
- **Status.** Accepted.

### ADR-PRC03 Merge commits, documented stack order, user approval

- **Decision.** Merge with merge commits (no squash); record the stacked-PR order in PR text (#2→#3→#7→#5→#8; #14→#15); nothing merges without the project owner's approval.
- **Rationale.** Keep reviewed commit ids referenced across PRs (for example `a980eed`, `ee56359`) valid.
- **Consequences.** Readable provenance. One merge commit message cites the wrong ranging commit (F-MRG-3, historical).
- **Status.** Accepted.

### ADR-PRC04 Leave PR #6 open at the deadline

- **Decision.** PR #6 was not merged.
- **Rationale.** Add/add conflicts in `.gitignore` and `README.md`, 5 tracked screenshots that fail the privacy test, committed evidence, no CI, and about 80,000 lines (PR #6 review comment, 2026-11-08 12:15 UTC).
- **Consequences.** BLE, Crazyflie and the separate RoverC keyboard/Wi-Fi control work (see [ADR-ROV01](#adr-rov01-usb-serial-stickc-bridge-with-a-firmware-watchdog)) are absent from `main`.
- **Status.** Accepted.

---

## Decisions we considered but have no record of

These are sometimes assumed. We found no evidence that they were decided, so they are not ADRs:

- **Choice of Tailscale over another overlay.** Tailscale was used (F-CAM-06), but no comparison is recorded.
- **Choice of the 1.0 m lookahead and 0.28 m blocked threshold.** These are placeholders derived from unmeasured speed and deceleration ([14](14_GROVE_ULTRASONIC.md) §4.5), not decisions based on measurement.
- **Why the Hailo-8 was not used for detection.** It was considered as an alternative ([ADR-CAM01](#adr-cam01-faster-r-cnn-resnet-50-fpn-v2-as-the-person-detector)), but no Hailo benchmark exists.
- **A drone-to-rover hand-off design.** The sighting format kept drone fields, but no integration was designed.
