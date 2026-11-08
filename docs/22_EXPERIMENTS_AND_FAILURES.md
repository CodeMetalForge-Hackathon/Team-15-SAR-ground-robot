# 22 · Experiments and failures

This document records what went wrong during the Team-15 build (6–8 November 2026), how each problem was investigated, what caused it (or that the cause is still **UNKNOWN**), what was done about it, where it stands at `d1b607a`, and what we learned. It merges the failure lists from the six domain audits into one narrative, ordered roughly from the physical layer upwards, followed by a master table. Many of the most important entries are **hardware** failures that software could not fix. They explain why no wheel turned and why no real distance was measured.

**Status:** Reference. Failures are documented; some are fixed, many hardware blockers remain OPEN.

**Related:** [Experiment registry](experiments/EXPERIMENT_REGISTRY.md) · [Experiment summary](experiments/EXPERIMENT_SUMMARY.md) · [Benchmark results](experiments/BENCHMARK_RESULTS.md) · [21 Troubleshooting](21_TROUBLESHOOTING.md) · [17 Safety architecture](17_SAFETY_ARCHITECTURE.md) · [23 Design decisions](23_DESIGN_DECISIONS.md) · [25 Limitations and future work](25_LIMITATIONS_AND_FUTURE_WORK.md) · [27 Project timeline](27_PROJECT_TIMELINE.md)

---

## 1. How to read this document

Each entry follows the same six-part shape:

- **Symptom:** what was observed.
- **Debugging evidence:** the measurements or logs that narrowed it down. Experiment IDs link to the [registry](experiments/EXPERIMENT_REGISTRY.md).
- **Root cause:** what caused it, or **UNKNOWN** if the evidence cannot decide.
- **Fix:** what was attempted, with commit or PR.
- **Status:** at `d1b607a` (FIXED, WORKAROUND, MITIGATED, OPEN, DOCUMENTED).
- **Lesson:** what to do differently.

Times are UTC unless marked ET (UTC−5). "Session console log" means an engineering console transcript, cited by date and time only. `$TEAM15_EVIDENCE`, `$QWEN_WORKSPACE` and `$ROBOT_WORKSPACE` are private local stores ([docs/README](README.md#private-evidence-stores)).

A recurring theme: **a fix that passes its tests proves the logic, not the hardware.** Several entries below were "fixed" in code while the physical problem underneath stayed open.

---

## 2. Sensors: Grove ultrasonic and RPLIDAR C1

### 2.1 Grove wiring uncertainty and the unverified fix

- **Symptom:** before the real run, a photo review at 09:41 on 2026-11-08 (RNG-WIR-01) found the red lead possibly on header pin 2 (5 V). The photo could not resolve it. The yellow signal lead appeared to be on the wrong pin, and no 1 kΩ series resistor was visible. The verdict was "can't be used as-is". The team then reported the wiring as "corrected/reset" (09:46) and "fixed" (09:57, 10:04, 10:26) without a new photo. The values supplied at 10:33 still contained placeholders ("V2.x", "actual PCB photo", "900–1100 Ω").
- **Debugging evidence:** session console log 09:41–10:43. The assistant refused four times to fill config fields from a verbal report and accepted only explicit values. A PCB photo confirmed board revision V2.0. Self-reported VCC 3.25 V and SIG idle 0.8 V were the only electrical numbers given. The only independent-verification record is a yes/no answer.
- **Root cause:** process. Under time pressure, verbal confirmation stood in for evidence.
- **Fix:** config provenance is recorded in a sidecar. The header was **never re-photographed**.
- **Status:** OPEN.
- **Lesson:** ask for the header close-up photo first; it answers "which pin" faster than any software check. A passing gate proves only that fields were filled in.

### 2.2 GPIO 3.3 V vs 5 V sensor-voltage risk

- **Symptom / risk:** the Grove SIG output swings to about VCC (Seeed schematic). With VCC = 5 V, about 5 V would reach a Pi GPIO that is not 5 V-tolerant. A 1 kΩ series resistor alone would still push ≈1.4 mA continuously into the GPIO protection diode.
- **Debugging evidence:** [ranging WIRING](../ranging/WIRING.md) §1–2; the 09:41 photo review (red lead possibly on pin 2).
- **Root cause (design hazard):** the 5 V header pins 2 and 4 sit right beside the 3V3 pin 1.
- **Fix:** 3.3 V supply is the default. `check_electrical` in `ranging/config.py` allows 5 V only with a bidirectional BSS138 level shifter, checks that the VCC pin and the voltage agree, and refuses SIG idle above `SIG_IDLE_MAX_V` = 1.2 V (`ee56359`, merged via PR #7). An earlier wiring guide expected SIG idle "≤ 3.4 V, about 3.3 V". The schematic shows a 10 kΩ pull-down, so the right expectation is ≈0.3–0.9 V, and ≈3.3 V indicates a *missing* pull-down. The guide was corrected.
- **Status:** MITIGATED in software. **Whether the board was ever powered from 5 V is unknown.**
- **Lesson:** encode electrical facts in the gate, and remember that the gate can only check what people type in. Read the schematic, not just the spec table.

A related gap (OPEN): the real runs were gated by `python3 -m ranging diagnose`. Its gate does not check `series_resistor_ohm`, header-pin protrusion, or a stricter SIG-idle limit. The stricter robotics wrapper `sensor_only_test.py` does check them, but it was not the path used. Two gates, with the weaker one reachable directly, should become one gate.

### 2.3 NO_ECHO diagnostics: 0/50 valid, twice

- **Symptom:** RNG-HW-01 (10:43) and RNG-HW-02 (10:50): 50/50 pings `NO_ECHO` in each run, 0 echo edges, health FAULT, diagnosis `NO_RESPONSE_EVER`. The target was at 100 cm (taped, as reported).
- **Debugging evidence:** the driver's per-ping records rule some causes **out**:
  - no `MISSED_ECHO_START`, so it is not a slow release;
  - no `ECHO_TIMEOUT`, so the echo line is not stuck;
  - no `LINE_STUCK_HIGH`, so SIG is not high or shorted at idle;
  - no `DRIVER_ERROR`, so there was no GPIO or library error;
  - throttled 0x0, so there was no under-voltage.

  The data **cannot distinguish** between: SIG not on GPIO5, an open resistor or jumper, no VCC at the sensor, a board that does not respond at 3.3 V, a trigger that does not register, or earlier damage. The release time was 96.1 µs in run 1 and 64.8 µs in run 2 (last-ping values).
- **Root cause:** **UNKNOWN.**
- **Fix:** none applied. The recommended continuity and VCC checks *at the sensor connector* were never reported as done.
- **Status:** OPEN. No real Grove distance exists. The diagnose JSONs are on the Pi and **unhashed**, because the Pi was unreachable during the audit.
- **What worked:** fail-closed behaviour. NO_ECHO maps to UNKNOWN and then STOP at three layers: ranging, `rover/sensors.py` with `hardware=True`, and the dashboard. The real motion verdict was STOP. NO_ECHO is ambiguous by design ("disconnected" and "nothing in range" look the same), which is why `NO_RESPONSE_EVER` and `NO_RESPONSE_AFTER_ECHOES` are distinguished by echo history, and why `floor-check` exists. It was never run.
- **Lesson:** measure at the sensor connector, not the header, and require photo plus written meter evidence.
- Report: [RNG-HW-01](experiments/reports/RNG-HW-01-grove-real-hardware-diagnose.md) · gate runs [RNG-PF-01](experiments/reports/RNG-PF-01-grove-preflight-gate-runs.md) · doc [14 Grove ultrasonic](14_GROVE_ULTRASONIC.md).

### 2.4 LiDAR: adapter flapping, and a gate that never opened

- **Symptom:** the CP2102N USB adapter (`10c4:ea60`) was detected at 08:21. It was **missing** after two Pi boots (08:31, 08:46) until it was re-plugged. There was a 4 s connect/disconnect at 08:34:57–08:35:01 and an incomplete enumeration at 08:35:21 (LDR-HW-01a–g). GET_INFO and GET_HEALTH were never sent, because the gate stayed closed on 15–17 physical checklist items (label photo, adapter identity, pinout, voltage, start current, headroom, strain relief, cut-off, location, two-person sign-off). The demo fell back to simulated replay (LDR-HW-01f).
- **Debugging evidence:** session console log 08:21–09:12. The 08:22 log stopped abruptly, and a LiDAR-related brownout was first suspected. At 08:33 the operator said the restart had been intentional. The 3 A supply's ≈600 mA USB budget is below the C1's ≈800 mA start current; the 5 A supply (≈1.6 A budget) resolves that.
- **Root cause:** for the adapter disappearing, **UNKNOWN** (cable moved between ports, a marginal connector, or boot behaviour). For "no scan", process: the physical checklist was not prepared.
- **Fix:** none in code. Audit-found design gaps (OPEN):
  - `expected_model_id` must be set before connecting, but the checklist says to read it via GET_INFO, which is a deadlock;
  - there is no GET_INFO-only command (`scan-once` always proceeds to SCAN);
  - the voltage bound is 5.25 V, above the datasheet's 5.2 V maximum.
- **Status:** OPEN. Real scan **NOT VERIFIED**.
- **Lesson:** a USB VID:PID never proves the device behind it. Run a deliberate 3-replug test, and prepare the physical checklist before the session. Ask the operator before inferring a power fault.
- Report: [LDR-HW-01](experiments/reports/LDR-HW-01-lidar-usb-enumeration-and-gate.md) · doc [15 RPLIDAR C1](15_RPLIDAR_C1.md).

---

## 3. Raspberry Pi: power interruptions, reboots and connectivity loss

### 3.1 No connectivity on the venue Wi-Fi

- **Symptom:** at 20:09 and 20:50 on 2026-11-07, the Mac could not reach the Pi: 100 % ping loss, no SSH, no ARP entry (CAM-32).
- **Root cause:** most likely client isolation on the guest Wi-Fi (inferred, not confirmed).
- **Fix:** an overlay network on both machines (relayed path).
- **Status:** working via the relay. The direct path is NOT TESTED.
- **Lesson:** plan for client isolation at venues.

### 3.2 Pi offline after moving onto the robot's power

- **Symptom:** at 23:05–23:08 on 2026-11-07 the Pi went offline twice after being moved onto the robot's supply (CAM-33). It came back on the CanaKit adapter (throttled 0x0, 5.18 V).
- **Root cause:** insufficient supply suspected (a Pi 5 needs 5 V / 5 A), **not measured**.
- **Fix:** handoff rules: 5 A PD supply; check `max_current` and `get_throttled` first.
- **Status:** MITIGATED. Battery endurance NOT TESTED. Later camera streaming on the adapter was clean: 0x0, 5.139–5.198 V (CAM-21).

### 3.3 Repeated reboots and drop-outs on 2026-11-08

- **Symptom:** the Pi dropped off the overlay network at about 11:38 and again at about 11:55 UTC, during live mapping run 2 (MAP-06 `camera.log` shows `ssh rc=255`). During the wheel-test attempts it showed uptime 2 min at 11:46 and under 1 min at 12:28 (reset code 0x1000). The supply limit reported was 3000 mA, compared with 5000 mA on the 27 W wall supply earlier. Throttled was 0x0, with no undervoltage messages after boot. The Pi was unreachable again during this audit.
- **Debugging evidence:** session console logs 11:38–12:29. A photo suggested the Pi's USB-C was fed from a USB-C hub on a power bank (inferred).
- **Root cause:** **UNKNOWN.** The journal is volatile, so the pre-reboot logs were lost. Suspects: a brown-out through the hub or power bank; CPU load from an earlier llama-server benchmark; back-feed through the StickC charging path.
- **Fix:** none in code.
- **Status:** OPEN.
- **Lesson:** never run motor tests on non-wall power. Enable a persistent journal (`Storage=persistent`), and monitor `get_throttled` and EXT5V continuously.
- Doc: [02 Raspberry Pi setup](02_RASPBERRY_PI_SETUP.md).

---

## 4. Rover controller and firmware

### 4.1 USB controller (M5StickC) never detected

- **Symptom:** the operator reported the StickC as connected (about 11:37 and 12:28 on 2026-11-08). On the **team Pi**, `lsusb` showed root hubs only, there was no `/dev/serial/by-id` entry, and the kernel logged **no attach attempt**. The **main Mac** showed no USB serial device either.
- **Debugging evidence:** eight read-only checks between 2026-11-07 23:27 and 2026-11-08 12:28 (ROV-02.C1–C8), all NOT DETECTED. Header I²C was not enabled, and nothing answered at 0x38.
- **Root cause:** **UNKNOWN.** Hypotheses: the StickC was plugged into the hub or power bank rather than the Pi; a charge-only cable; a non-data port.
- **Fix:** none (process recommendations only).
- **Status:** OPEN. The bench runbook's Gate 5 is blocked. The two requested wheel tests were **NOT RUN** (ROV-03a/b).
- **Lesson:** before declaring "connected", confirm the data cable, the Pi port, 5 A power and a photo. Script the read-only detection so that it is a single command.
- Report: [ROV-02](experiments/reports/ROV-02-controller-connectivity-inspection.md) · doc [12 RoverC motor control](12_ROVERC_MOTOR_CONTROL.md).

### 4.2 Rover firmware integration blockers, and two firmware efforts never reconciled

- **Symptom:** no firmware on `main` has ever run on a StickC. The PR #15 bridge firmware `firmware/stickc_roverc_bridge/stickc_roverc_bridge.ino` is a **draft that was never compiled or flashed**. Separately, the **unmerged** PR #6 (branch `culubo/sensor-id-specs`, commit `45481e4`, 2026-11-08 04:28 UTC, author `culubo`) adds a different control path: a `roverc_usb` receiver firmware, a keyboard client, Wi-Fi setup and a mission-control verification note. Its branch README says a "working USB receiver image" was uploaded to a StickC Plus from a teammate's own Mac. The original firmware was backed up privately first, and **restoring it was never tested**. The README also says "MOVE is acknowledged only after the requested motor registers are read back; this does not prove wheel rotation", and that `READY=0` means the base's I²C controller was not detected. The branch's verification note (2026-11-07) says no physical robot was operated: 270 + 41 tests passed against a loopback fake receiver, and "powered RoverC directions/stop behavior" is listed as a pending hardware gate (EXT-01, EXT-02).
- **Debugging evidence:** the PR #15 independent review found that the draft wrote the motor zero only *after* `M5.begin()`, so a reset while moving would leave the wheels running during initialisation. It was fixed in `dbc17b3` (zero first, then again after). The review also found and fixed: partial I²C writes leaving the output unknown, a remote e-stop clear, ack/sequence matching, and differences between the model and the firmware. A firmware-model test failed during the fixes (1 failed, 62 passed, `assert (0 == 40)`, session console log 10:42), because `FakeI2C` did not model a NACK after the first data byte. A `partial` counter was added to `rover/tests/bridge_model.py`.
- **Root cause:** time and hardware access. Firmware cannot be validated without an enumerated controller (§4.1). Two people built two firmware paths in parallel, with different wire protocols, and the two **were never reconciled**.
- **Fix:** design fixes in PR #15; PR #6 left open (its review comment at 12:15 UTC lists add/add conflicts, tracked screenshots that fail the privacy test, committed evidence, and about 80k lines).
- **Status:** OPEN. **Real wheel movement NOT TESTED / NOT VERIFIED.** The firmware watchdog has been measured only in the Python model (0.251 s, BRG-01b).
- **Lesson:** agree on one firmware and one wire protocol before two people write them. An independent review of safety firmware finds ordering hazards that model tests cannot. Model partial failures, not only total ones.
- Reports: [BRG-01](experiments/reports/BRG-01-bridge-watchdog-mocked-tests.md) · doc [13 M5StickC bridge](13_M5STICKC_BRIDGE.md).

### 4.3 Fail-open forward gate (Issue #9) and a crashing safety loop

- **Symptom:** MOVE_FORWARD was refused only when `forward_allowed is False`; a value of `None` passed. Separately, after a controller link died, `tick()` raised on every cycle, because the latched branch called `_hard_zero()`, which re-raised the driver error.
- **Root cause:** a fail-open default (not an active hazard, because hardware readings always carried a boolean), and a zero-assert path that re-raised.
- **Fix:** PR #14 (`1b942e3`, `7efa570`) requires `is True` + CLEAR + fresh + hardware OK. `14fde0d` added `_zero_never_raise` with the regression test `test_dead_link_never_crashes_tick_and_stays_latched`. The cross-PR USB-bridge end-to-end test found the crash.
- **Status:** FIXED (ROV-01a/b, 40/40).
- **Lesson:** gates should require positive evidence, not the absence of a veto. A safety loop must never die from the fault it is reacting to.
- Open design items in the contract: the `t = now` fallback in `snapshot_to_rover_fields` (`ranging/rover_io.py`) makes a reading without `mono_ns` look fresh. The 0.1 s ping interval against the 0.20 s freshness limit means one or two missed pings latch SENSOR_STALE. Both are listed in `contracts/ROVER_NAV_CONTRACT.md` §2 and are OPEN.
- Report: [ROV-01](experiments/reports/ROV-01-issue9-fail-closed-tests.md) · doc [17 Safety architecture](17_SAFETY_ARCHITECTURE.md).

---

## 5. Camera perception

### 5.1 Camera calibration limitations

- **Symptom:** no camera distance can be validated. `camera_mapping/configs/imx708_robot.json` has `mount.measured: false`, and tape calibration was **NOT RUN** (MAP-09). As a result, every demo-script state (1,292 states, MAP-04…08) shows corridor UNKNOWN and `NO_SUPPORTED_ROUTE`, and JUDGE_DEMO steps 2–4 (ground-plane distance, BLOCKED, alternate route) **cannot occur at `d1b607a`**.
- **Root cause:** the physical measurements (mount height, pitch, tape samples) were never taken.
- **Fix:** none. The tooling exists ([CALIBRATION](camera_mapping/CALIBRATION.md)). The [demo guide](26_HACKATHON_DEMO_GUIDE.md) corrects the narrative.
- **Status:** **OPEN blocker.** All camera distances are UNCALIBRATED.
- **Lesson:** schedule the physical measurements before building features that depend on them, and rehearse demo scripts against the shipped config.
- Report: [MAP-09](experiments/reports/MAP-09-tape-distance-calibration.md) · doc [05 Depth and distance](05_DEPTH_AND_DISTANCE_ESTIMATION.md).

### 5.2 Head-clipped and partially visible detections

- **Symptom:** the recorded Pi frame used by every replay has its person box cut at the top ([22, 1, 739, 627]). Persons in live run 2 were UNKNOWN because their boxes were truncated (MAP-06). A chair cut off at the side of the frame got a KNOWN_HEIGHT distance of **7.91 m, then 6.76 m** (MAP-06, frames 122–131). One lying person produced `count_in_frame` = 2 (CAM-28), and another produced 2–3 boxes per frame (CAM-29).
- **Root cause:** size-based monocular ranging assumes the whole object is visible. A truncated box is shorter, so the range comes out too *far*. The truncation check covered only the top and bottom edges. Faster R-CNN emits overlapping whole-body and part boxes, and `count_in_frame` counts boxes, not people.
- **Fix:** `73539a7` refuses a box cut at **any** edge (`test_known_height_refuses_side_truncated_box`). The truncated persons were correctly refused. Box grouping for counting exists only on an unmerged branch (`417f45b`, `4fe0508`).
- **Status:** ranging FIXED; counting OPEN on `main`. The field is documented as a box count.
- **Lesson:** partial views make size-based ranging err towards "farther", which is the unsafe direction, so refuse them. Do not present box counts as head counts.

### 5.3 HOG and Haar baselines failed on rescue-relevant poses

- **Symptom:** HOG missed a standing person in 36 of 97 frames (CAM-06) and missed seated and lying people in **every** frame (CAM-08 0/98; CAM-27/28/29 0/94 each). The face cascade fired on a blank wall in 80 of 97 frames.
- **Root cause:** HOG + linear SVM models upright pedestrian silhouettes, and Haar cascades have high false-positive rates on textures.
- **Fix:** Faster R-CNN R50-FPN-v2 became `PERSON_DETECTOR` (`44b7031`, PR #3). HOG and Haar remain as labelled secondary families, and only the person family triggers alerts by default.
- **Status:** resolved by design.
- **Lesson:** validate a baseline on the poses that matter (lying, seated, partly hidden) before trusting it.

### 5.4 False sighting from window reflections

- **Symptom:** in a physically empty room facing windows, the detector placed 1,767 person boxes on the glass, up to 393 px tall, and raised a **false sighting at 0.991** (CAM-12).
- **Root cause:** an appearance-only detector cannot tell reflections, or people behind glass, from people in the room.
- **Fix:** `--min-box-frac 0.15` (`65684e3`) removes small reflections but not tall ones. The other mitigation is to aim the camera away from glass. An ignore mask was proposed but not built.
- **Status:** OPEN.
- **Lesson:** test empty scenes in front of glass, and never present camera sightings as confirmed.

### 5.5 "Empty" scenes that were not empty, and a consent gap

- **Symptom:** five of the six 60 s "empty" Mac runs had real people in view (CAM-09/10/11/13/14). Two "standing" runs detected the operator instead of the teammate (CAM-04/05). A Pi scene requested as "empty" contained a standing person, and the full pipeline **saved a photo** of them (CAM-23).
- **Root cause:** an uncontrolled open office; no start delay at first; the "empty" mode ran the normal sighting path.
- **Fix:** `--start-delay-s` and a CONTAMINATED verdict (`65684e3`). On the **unmerged** branch, empty scenes cannot store images (`a7d9628`).
- **Status:** the Mac empty test never passed. The Pi empty test passed (CAM-25). The consent fix is not on `main`.
- **Lesson:** control the scene, pre-register the verdict rules, and enforce consent modes in code.

### 5.6 Orientation, warm-up and exposure

- **Symptom and fix:**
  - The first Pi sighting image was upside down on the bench (CAM-17), because the default rotation 180 assumes an inverted mount. A session briefly concluded the default should be 0. A check on the real robot mount (CAM-20) confirmed 180, in `d847270`.
  - The first live Pi run reached only 0.68 fps, because the first MPS call took 3.71 s. `warm_up()` (`ae8b088`) fixed it, giving 4.36–5.0 fps afterwards.
  - Nearly black frames (mean ≈16/255 at the 66.7 ms exposure cap, CAM-19) were traced to a covered or mis-aimed lens. `frame_stats()` in `perception/orientation_check.py` now checks exposure.
- **Status:** FIXED. Rotation is a per-mount parameter.
- **Lesson:** re-run the orientation check after any remount; always warm up GPU models before timing.
- Reports: [CAM-15](experiments/reports/CAM-15-pi-transport-and-first-e2e.md) · [CAM-20](experiments/reports/CAM-20-pi-orientation-check.md) · [CAM-09](experiments/reports/CAM-09-mac-empty-scene-60s.md) · doc [04 Camera perception](04_CAMERA_PERCEPTION.md).

---

## 6. Camera mapping

### 6.1 Incorrect free-space inference

- **Symptoms:** an independent review of PR #16 confirmed the following with synthetic reproduction scripts (MAP-12):
  - (a) A tracked obstacle that later filled the bottom of the frame read **CLEAR**, with FREE cells in front of it.
  - (b) FREE space persisted for up to **1.5 s behind a new obstacle**: 96 cells behind a chair at 1.0 m stayed FREE. The first tentative frame of a detection read CLEAR.
  - (c) An observed-free (SUPPORTED) route was never found.

  Before that, the live run 1 code suggested `ROUTE_THROUGH_UNOBSERVED_SPACE` in all 117 states even though the mount was unmeasured, so no cell could be FREE (MAP-01).
- **Root causes:**
  - (a) `range_known` stayed True once a track had history, so an old far median was used.
  - (b) Masks only stopped refreshing `last_obs`, so FREE cells survived until their TTL expired.
  - (c) The `not_free` inflation covered the unobservable blind band over the start cell, and the test accepted either outcome.
  - MAP-01: A\* ran over an all-UNKNOWN grid in NEEDS_OBSERVATION mode.
- **Fix:**
  - `c7ed6c5`: the footprint uses range only while the current estimate is ESTIMATED, and a bottom-cut box gives BLOCKED. `last_obs[masked] = −inf` is set in the same frame. The blind band is exempt. Regression tests: `test_tracked_obstacle_cut_by_frame_bottom_is_never_clear`, `test_space_behind_new_obstacle_loses_old_free_immediately`, `test_supported_route_found_around_side_obstacle`.
  - `suggest_route` returns `NO_SUPPORTED_ROUTE` when the mount is not usable; this was present from the first commit `f482f21` (`test_no_route_when_mount_unmeasured`).
- **Status:** FIXED, in SYNTHETIC tests only. It has never been exercised on real data, because the mount is unmeasured.
- **Lesson:** invalidate safety-relevant state positively in the same frame; never rely on expiry. Filters must not outlive the validity of their latest input. Tests that accept "either outcome" hide bugs. A "fallback" route is still a claim.

### 6.2 Stale map behaviour

- **Symptom:** a stale or NO_DATA view still drew FREE and OCCUPIED cells, and when polling failed, the browser kept showing the last status.
- **Root cause:** `stale_view` (`camera_mapping/pipeline.py`) did not touch the map rows, and the JavaScript kept its previous state.
- **Fix:** `c7ed6c5`: `stale_view` blanks rows and footprints, the browser marks the client stale after 2 s, and outdated advisories are hidden (`test_stale_view_draws_no_free_or_occupied_cells`). The recorded camera-loss test (MAP-05) showed STALE / UNKNOWN / all cells unknown within 2 s, and an automatic restart gap of 9.98 s.
- **Status:** FIXED. The JavaScript part is not covered by CI.
- **Lesson:** degrade every derived view, not only the headline status.
- Reports: [MAP-01](experiments/reports/MAP-01-live-pi-run-1-latency.md) · [MAP-05](experiments/reports/MAP-05-camera-loss-stale-restart.md) · [MAP-06](experiments/reports/MAP-06-live-pi-run-2-person-chair.md) · doc [06 Obstacle mapping](06_OBSTACLE_MAPPING.md).

Other review findings fixed in `c7ed6c5`: the Advisor thread could die silently; fusion used only two of three methods; the lens setback was ignored; a frame post could stall the loop for 3 s (now 1 s). Still open: pending-jump samples need not agree with each other, and `lateral_offset_m` is unused.

---

## 7. Dashboard: duplicate runners and shutdown

- **Symptom:** during live run 2 (2026-11-08 11:52), the dashboard alternated between LIVE and RECORDED. There were 6 source flips in 15 polls, the advisory statuses were mixed, and the detector slowed (246 ms vs 186 ms) (DSH-02). A stray `--source replay` runner was still posting alongside the live Pi runner. The demo script also survived INT/TERM and restarted its runner.
- **Debugging evidence:** dashboard polls, MAP-05/06 JSONL, a process listing, and `pkill -f "camera_mapping.live --source replay"` in the session log.
- **Root cause:** the dashboard accepted any producer and had no producer identity. `trap cleanup EXIT INT TERM` returned into the restart loop.
- **Fix:** `73539a7` added a single-producer lock (HTTP 409; the runner exits with code 4; panel D shows the conflict) and `trap 'cleanup; exit 130' INT TERM`.
- **Status:** FIXED. SIGTERM was verified: 0 processes left. **Interactive Ctrl-C is UNVERIFIED**, because a SIGINT sent to a background job left 3 processes, which is inconclusive (MAP-07).
- **Lesson:** shared displays need a single-writer rule enforced at the sink. Test signal handling the way the operator will actually use it.
- Report: [DSH-02](experiments/reports/DSH-02-dashboard-duplicate-producer.md) · doc [16 Dashboard](16_DASHBOARD.md).

---

## 8. Qwen advisory model

### 8.1 RAG threading issue

- **Symptom:** every HTTP `C_QWEN_RAG` request to `rescue_qwen.service` returned **HTTP 500 `sqlite3.ProgrammingError`** (about 11:20 on 2026-11-08, DSH-04).
- **Root cause:** the in-memory SQLite FTS index was built in the main thread and used from FastAPI worker threads. The RAG path had never been tested over HTTP.
- **Fix:** a workaround in the repo, `camera_mapping/qwen_launcher.py` (PR #16): it opens the index with `check_same_thread=False` and refuses to run unless `sqlite3.threadsafety == 3`. Afterwards, advisories returned `QWEN_GUARDED` in 4.0–5.9 s. The proper fix is on the Qwen-workspace branch `fix/rag-index-threading` (`9619bf9`), which is **not merged**.
- **Status:** WORKAROUND. It depends on how SQLite was built.
- **Lesson:** test every configuration over the real transport; fix at the source.

### 8.2 LoRA deployment limitations

- **Symptom:** the published adapter (ckpt-0088, Hugging Face revision `21013d4`, QWN-031) cannot be served in the demo. The live demo uses **base Qwen + RAG**.
- **Debugging evidence:** the runtime audit's E6 step showed that Ollama 0.40.2 rejects the adapter with "LoRA adapters are no longer supported" (QWN-018). Merge and GGUF tooling was not installed. `rescue_qwen.service` has no HF backend, and `camera_mapping/qwen_launcher.py` uses an Ollama backend only.
- **Further limits found in evaluation:**
  - ckpt-0088 is over-permissive on LiDAR (14/60, and 9/60 with RAG; 0/60 schema-valid; QWN-022), because it was trained only on mission and fusion formats.
  - It drifts towards over-conservative answers on delivery.
  - It missed 2 timeout stops in 230 steps (QWN-017).
  - The LiDAR pilot regressed the mission score from 218 to 182, with 13 unsafe (QWN-026), and was not promoted.
  - Every model fails the promotion gate (QWN-029).
- **Status:** OPEN. The deterministic `SafetySupervisor`, which is independent of Qwen, remains the motion authority.
- **Lesson:** check the deployment path before training. Gate an adapter's safety per task family. Never rely on the LLM for stops.
- Reports: [QWN-018](experiments/reports/QWN-018-runtime-comparison-audit.md) · [QWN-017](experiments/reports/QWN-017-frozen-mission-230.md) · [QWN-022](experiments/reports/QWN-022-lidar-frozen-eval.md) · [QWN-029](experiments/reports/QWN-029-safety-regression.md) · docs [08 Qwen](08_QWEN_MODEL.md), [09 LoRA](09_LORA_TRAINING.md).

### 8.3 Unsuccessful training runs

| Run | Symptom | Root cause | Fix | Status |
|---|---|---|---|---|
| Smoke (QWN-010, 2026-11-07 19:04 ET) | 21.7–24.4 GB on MPS, swap 7.6/8 GB; validation 0/20 parseable | full-vocabulary logits (248,320 × ~2k tokens) materialised for the loss | `logits_to_keep` on assistant tokens only (Qwen workspace `1b57993`); memory dropped to about 7–8 GB with the loss unchanged (1.782 vs 1.782) | FIXED |
| **run1** (QWN-011, 19:19:02 ET) | crashed at start-up: `RuntimeError: invalid low watermark ratio 1.4` | only `PYTORCH_MPS_HIGH_WATERMARK_RATIO` was set | set both the high (0.7) and low (0.5) ratios | FIXED |
| **run1b** (QWN-012, 19:19:18 ET) | MPS out of memory at the first backward pass (9.04 GiB allocation, cap 12.43 GiB) | as the smoke run, under a memory cap | as the smoke run | FIXED; **run2** (QWN-013) then trained 89 steps on 689 records, peaking at 8.54 GB |
| run2 coverage | all 6 camera–range disagreement rows and 9 of 16 images were skipped as too long | `--max-len 2400` with long RAG context | proposed `--max-len 2700`; not done | OPEN |
| LiDAR benchmark run 1 (QWN-023) | harness crash on list-typed fields; raw outputs truncated at 600 chars | an untested harness | type-safe metrics, full raw outputs, equal token limits (`93e1848`, Qwen workspace) | FIXED |
| Generalization eval with Ollama (QWN-034) | `KeyError: 'scenario_id'` | generalization rows lack that field | re-run as `gen_ollama_base_norag` | the Ollama + RAG row was never produced |
| v0.1 train-split eval (QWN-007) | every request fell back | the Ollama desktop app quit mid-run (18:04 and 18:27 ET); cause **UNKNOWN** | `run_eval` marks such runs INVALID; the demo script health-checks Ollama | FIXED (detection) |

Reports: [QWN-010](experiments/reports/QWN-010-lora-smoke.md) · [QWN-011](experiments/reports/QWN-011-lora-run1-failed.md) · [QWN-012](experiments/reports/QWN-012-lora-run1b-oom.md) · [QWN-013](experiments/reports/QWN-013-lora-run2.md).

Other documented Qwen issues:
- The guard regex treated "No person is confirmed" as a confirmation claim. Fixed with `affirmative_search`.
- The fallback advisory understated a hazard. Fixed with `minimum_evidence` (`94ee31c`); a re-score shows 0/120 more permissive (QWN-033).
- 4 frozen gold labels are not identifiable from the prompt (documented).
- One validation row duplicates a training row (documented).
- The checkpoint-selection tie was broken by list order (documented).
- RAG **increased** forbidden claims for the untuned model (delivery 24 → 34; LiDAR 19 → 35). This is mitigated by the guard.
- One reworded unsafe request ("roll the rover over to him") was refused by neither the regex nor the model. It was deliberately left unpatched to avoid overfitting the frozen set.
- The trainer's demo guard detects only `perception.live_camera`, not `camera_mapping.live`. OPEN.

---

## 9. Integration: PR conflicts and regression fixes

| Problem | Evidence | Root cause | Fix | Status |
|---|---|---|---|---|
| add/add conflict on `.github/workflows/ci.yml` between PR #3 and PR #5/#8 | session console log 2026-11-08 01:38, 02:05; `8f351fe` | two branches created the same file path | the perception workflow was renamed to `perception.yml` (`8f351fe`) | FIXED |
| two workflows both named "ci" on `main` | PR #10 | `perception.yml` created with `name: ci` | PR #10 (`edb6756`) | FIXED |
| stacked PRs needed a strict merge order (#2 → #3 → #7 → #5 → #8; #14 → #15) | PR #2, #8 descriptions | dependency merges between stacked branches | merged in the documented order. The PR #8 merge message `82f5079` cites the wrong ranging commit; it was re-merged at `a980eed` (`0f08721`) | FIXED (message error historical) |
| PR #8's old head `09333d3` failed the ranging contract test | PR #8 | its vendored ranging copy lacked the SIG-idle gate | `dac82f4` pins PR #7 ≥ `ee56359` | FIXED |
| contract drift between the dashboard draft (`T15F` binary, `PiFrameSource`) and what shipped | `contracts/PI_CAMERA_CONTRACT.md` note | two owners without a frozen interface | the contract was rewritten to match what shipped (`4d3093d`) | FIXED |
| `__pycache__` committed | `9efbed7` | python run without `-B` | removed and ignored | FIXED |
| PR #6 unmergeable | review comment 2026-11-08 12:15 | add/add conflicts in `.gitignore` and `README.md`; 5 tracked screenshots fail the privacy test; committed evidence; no CI; ~80k lines | none | OPEN (left open) |
| camera-live consent runner and live-test reports exist only on the local unpushed branch `test/camera-live-countdown` | timeline | not merged before the deadline | none | OPEN |

Lesson: give per-package workflows unique filenames, record the stack order in the PR text, let contract tests catch stale vendored copies, and keep evidence out of Git.

## 10. CI failures

Of 184 GitHub Actions runs, 3 failed (CI-001). Both causes were fixed within minutes.

- **OpenCV 5 removed `HOGDescriptor`.** The first CI run (2026-11-07 18:59, runs 42403983799 and 42404031282, `3797530`) failed `test_blank_image_no_person` with `AttributeError: module 'cv2' has no attribute 'HOGDescriptor'` (1 failed / 30 passed). The install log showed opencv-python-headless 5.0.0.93, because `requirements.txt` was unpinned. **Fix:** `a36a658` pinned every requirement to the bench Mac's versions (opencv 4.13.0.92) about a minute later, and `cee428e` set `>=4.8,<5` in the perception workflow. **Lesson:** pin dependencies from day one; a major version bump can silently remove an API.
- **Leaflet icons tripped the privacy test.** PR #17's CI (2026-11-08 11:59, run 42478121738, `eddef53`) failed `test_no_photos_tracked_in_git` (1 failed / 332 passed / 7 skipped), because the PR vendored 5 Leaflet marker PNGs. The branch had forked from the initial commit and had never seen the test. **Fix:** `95b6f67` merged main. `159c678` added the exact-path `VENDORED_ICONS` allow-list in `dashboard/tests/test_dashboard.py` and untracked a 10 MB GIF. **Lesson:** a privacy guard needs a narrow, explicit exception mechanism, and long-lived forks should merge main early.
- **Open CI gaps:**
  - On `d1b607a` only `ci` (532 passed + 8 skipped) and `perception` ran. lidar, ranging and qwen were last green on `159c678` (path filters).
  - The 8 skips need private data or weights.
  - `team15_starter/tests` and `test_link.py` have no CI workflow.
  - Every PR commit runs each workflow twice (push and pull_request).
- Reports: [CI-001](experiments/reports/CI-001-ci-regression-history.md) · [CI-002](experiments/reports/CI-002-local-test-suite-d1b607a.md) · doc [19 Testing](19_TESTING_AND_BENCHMARKS.md).

## 11. Simulation reproducibility: the fleet CSVs

- **Symptom:** re-running `team15_starter/fleet_eval.py --study fleet` and `--study emcon` (20 seeds) at `d1b607a` gives numbers that differ from the committed CSVs. EMCON success drops from 90 % to 65 %, and the shared-map t_found rises from 100.8 s to 128.0 s (SIM-02/03 vs SIM-07/08). Within one commit the runs are deterministic (byte-identical).
- **Root cause:** the code changed after the CSVs were generated (`e47c1bf` battery fix; `eddef53` roles and a faster planner), and the generating command lines were not recorded. Similarly, commit `4018ff9` says "60 scenarios x 2 budgets", but the script writes fixed filenames, so the 30 km run was overwritten and survives only in `7ed29a5`.
- **Fix:** none.
- **Status:** OPEN (documented).
- **Lesson:** commit results together with the code, and store the argv, the commit SHA and the run parameters in the output itself.
- Reports: [SIM-02](experiments/reports/SIM-02-drone-fleet-eval.md) · [SIM-05](experiments/reports/SIM-05-sarenv-bench.md) · doc [18 Simulation](18_SIMULATION.md).

---

## 12. Master table

| # | Failure | Domain | Root cause | Fix (commit / PR) | Status | Section |
|---|---|---|---|---|---|---|
| 1 | Grove wiring uncertain; "fix" unverified | sensors | process (verbal confirmation) | none | OPEN | §2.1 |
| 2 | 5 V on a 3.3 V GPIO risk | sensors | header layout hazard | `ee56359` (PR #7) gate checks | MITIGATED | §2.2 |
| 3 | Grove 0/50 VALID ×2, `NO_RESPONSE_EVER` | sensors | **UNKNOWN** | none | OPEN | §2.3 |
| 4 | Two Grove gates; the weaker one used for real runs | sensors | design | none | OPEN | §2.2 |
| 5 | LiDAR adapter missing after reboots; 4 s drop | sensors | **UNKNOWN** | none | OPEN | §2.4 |
| 6 | LiDAR never queried (gate closed) | sensors | physical checklist not prepared | none | OPEN | §2.4 |
| 7 | Pi unreachable on the venue Wi-Fi | Pi | client isolation (likely) | overlay network | WORKAROUND | §3.1 |
| 8 | Pi offline on robot power | Pi | supply suspected, not measured | 5 A supply rule | MITIGATED | §3.2 |
| 9 | Pi reboots and drop-outs on 3 A power | Pi | **UNKNOWN** | none | OPEN | §3.3 |
| 10 | M5StickC never enumerated on the team Pi or the main Mac | rover | **UNKNOWN** | none | OPEN | §4.1 |
| 11 | Firmware never compiled or flashed; two firmware efforts not reconciled | rover | time, no controller; parallel work | design fixes `dbc17b3` (PR #15); PR #6 unmerged | OPEN | §4.2 |
| 12 | Fail-open forward gate; `tick()` crash | rover | fail-open default; re-raising zero | `1b942e3`, `7efa570`, `14fde0d` (PR #14) | FIXED | §4.3 |
| 13 | Camera distances uncalibrated | camera | mount and tape not measured | none | OPEN (blocker) | §5.1 |
| 14 | Side-cut box → 7.91 m | mapping | truncation check incomplete | `73539a7` | FIXED | §5.2 |
| 15 | `count_in_frame` counts boxes | camera | part boxes | unmerged `417f45b` | OPEN on main | §5.2 |
| 16 | HOG / Haar fail on rescue poses | camera | model limits | `44b7031` (PR #3) | resolved by design | §5.3 |
| 17 | Window-reflection false sighting | camera | appearance-only detector | `65684e3` (partial) | OPEN | §5.4 |
| 18 | Contaminated empty scenes; consent gap | camera | uncontrolled scene; pipeline saved images | `65684e3`; unmerged `a7d9628` | PARTIAL | §5.5 |
| 19 | Upside-down image; slow first frame; black frames | camera | mount-specific rotation; MPS warm-up; lens | `d847270`, `ae8b088` | FIXED | §5.6 |
| 20 | Incorrect free-space inference (CLEAR in front of an obstacle; FREE behind one; route through unobserved space) | mapping | stale range validity; TTL-based FREE; grid fallback | `c7ed6c5`; `f482f21` | FIXED (synthetic tests) | §6.1 |
| 21 | Stale map still drawn | mapping | `stale_view` left rows; JS kept state | `c7ed6c5` | FIXED | §6.2 |
| 22 | Duplicate producers on the dashboard | dashboard | no producer identity | `73539a7` | FIXED | §7 |
| 23 | Demo Ctrl-C did not exit | dashboard | trap returned into the loop | `73539a7` | SIGTERM FIXED; Ctrl-C UNVERIFIED | §7 |
| 24 | RAG HTTP 500 (`sqlite3.ProgrammingError`) | Qwen | SQLite thread affinity | `camera_mapping/qwen_launcher.py` (PR #16); root fix unmerged | WORKAROUND | §8.1 |
| 25 | LoRA not servable; demo uses base + RAG | Qwen | Ollama 0.40.2 rejects adapters; no HF backend | none | OPEN | §8.2 |
| 26 | LoRA smoke memory blow-up; run1 env crash; run1b OOM | Qwen | full-vocab logits; watermark env var | `1b57993` (Qwen workspace); env fix | FIXED | §8.3 |
| 27 | Workflow add/add conflict; duplicate workflow name | CI | same file path; `name: ci` | `8f351fe`; `edb6756` (PR #10) | FIXED | §9 |
| 28 | PR #6 unmergeable | integration | parallel branch never rebased; committed evidence | none | OPEN | §9 |
| 29 | CI: OpenCV 5 HOGDescriptor | CI | unpinned requirements | `a36a658`, `cee428e` | FIXED | §10 |
| 30 | CI: Leaflet icons vs privacy test | CI | blanket image ban; old fork | `95b6f67`, `159c678` | FIXED | §10 |
| 31 | Fleet CSVs not reproducible; SAREnv 30 km overwritten | sim | code changed after results; fixed filenames | none | OPEN | §11 |

## 13. Cross-cutting lessons

1. **Evidence before assertion.** The costliest delays (Grove, StickC, LiDAR) came from "it's connected" or "it's fixed" being accepted without a photo, a reading or an enumeration line. A one-line read-only check and a photo would have saved hours.
2. **Power is the first suspect, and you need logs to prove it.** A volatile journal meant three separate Pi outages have no root cause. Make the journal persistent before the first hardware session.
3. **Fail closed, and test the fail-closed path on real hardware too.** The one thing proven on real hardware about the ultrasonic is that a dead sensor leads to STOP (§2.3). That is a real result, but it is not a distance measurement.
4. **Fix at the sink, not by convention:** the single-producer lock, consent modes in code, motor-path allow-lists.
5. **Keep results next to the code that produced them, with argv and the commit SHA.** Otherwise a committed CSV becomes a historical artefact that nobody can reproduce (§11).
6. **Rehearse the demo against the shipped configuration.** The judge script described CLEAR/BLOCKED verdicts that the shipped config makes impossible (§5.1).
