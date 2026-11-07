# RoverC-Pro navigation: safety and limitation report

Date: 2026-11-07. Branch `feature/rover-navigation`.

## 0. Gate status
| Gate | Status | Evidence |
|---|---|---|
| 1 Protocol understood | **Partly: documentation only.** Hardware inspected read-only on 2026-11-07: see `HARDWARE_READINESS.md` | Datasheet facts are encoded in `rover/protocol.py`. The undocumented items are listed in section 1 below. |
| 2 Simulated motor commands + watchdog | **PASS (sim)** | `rover/tests/test_supervisor.py`, `test_protocol_hardware.py` |
| 3 Dynamic shortest-path rerouting | **PASS (sim)** | `rover/tests/test_scenarios.py` A–F, `test_scanning.py`, `planner/tests/test_astar.py` |
| 4 Sensor integration with fake readings | **PASS (sim + PR #7 interface)** | Scenarios G and H, plus `rover/tests/test_grove_adapter.py`, which runs PR #7's own `rover_io`/`RangeClient` |
| 5 Physical motor tests | **NOT STARTED: blocked** | Section 1 |
| 6 Supervised movement with real sensors | **NOT STARTED** | Needs Gate 5 and the Grove contract |
| 7 Localization/odometry validation | **NOT POSSIBLE with current hardware** | No encoders, no calibrated heading |

**Autonomous navigation is not operational. Only the simulation has been demonstrated.**

## 1. Hardware facts and blockers
Verified from M5Stack documentation (not from our unit):
- K036-B, I²C address `0x38`.
- Motor registers `0x00–0x03` hold INT8 values from −127 to 127.
- Servo registers `0x10/0x11` and `0x20–0x23`. This package never writes them.
- 16340 700 mAh battery, charged through the StickC.
- The pinmap puts SDA on G0 and SCL on G26 of the StickC.
- The MCU part number conflicts between pages (STM32F030C6T6 or C8T6).
- The library clamps each wheel to ±100.
- The library's `setPulse`/`setAllPulse` write to the motor registers. **Do not call them.**

Not verified, so each one blocks Gate 5:
1. **Exact controller model and firmware.** We don't yet know whether it is a StickC or a StickC Plus, nor what sketch is flashed. Nothing on this Mac shows a USB serial device for it (only Bluetooth and debug ports).
2. **The Pi-to-RoverC link does not exist.** Inspected over Tailscale (100.97.93.118): no USB devices, no serial devices, and the header I²C bus is not enabled. See `HARDWARE_READINESS.md`.
   - The RoverC bus is mastered by the StickC.
   - Wiring the Pi into a Grove I²C port would put two masters on one bus. That is unsupported.
   - **Recommendation:** add StickC bridge firmware that takes commands over USB serial (or Wi-Fi UDP) and **zeroes the motors when commands stop arriving** (for example after 300 ms). Then measure that timeout and record it in `HardwareVerification.stop_on_link_loss_ms`.
3. **No watchdog on the motor MCU is documented.** Assume the STM32 holds the last speed forever. A host-side watchdog alone can't stop the wheels if the link dies, so the firmware-side timeout in item 2 is required.
4. **Wheel mapping and signs are unknown.** We don't know which register drives which wheel, or which sign is forward, strafe-left or CCW. Measure these with the wheels lifted (runbook step 3).
5. **Power.** There is no RoverC battery-voltage register. The StickC's PMIC may report its own battery, but whether that reflects the RoverC battery is unverified. With no measured undervoltage threshold, the supervisor refuses all physical motion.
6. **There is no pose and no heading source.** The RoverC has no encoders. The StickC IMU (MPU6886/SH200Q, depending on the model) is unverified and uncalibrated. Without a measured heading:
   - in-place rotation scanning is refused (timed turns are never treated as angles);
   - autonomous edge-following is refused;
   - the navigator can only offer operator-assisted waypoint execution.
7. **Robot width.** The sim uses a placeholder of 0.20 m. Measure the real chassis, including the gripper.

## 2. Safety mechanisms (implemented)
- Output is zero at construction and on every stop. Speeding up is rate-limited; stopping is instant.
- Commands are bounded:
  - speed at most 0.30 (normalised);
  - each command lasts at most 1.0 s, and the navigator re-issues 0.15 s commands only after a fresh check;
  - there is no indefinite motion.
- The watchdog latches `COMMS_LOST` when there's no heartbeat for 0.25 s.
- A range reading older than 0.20 s latches `SENSOR_STALE`.
- These faults latch `DRIVER_FAULT`, `UNDERVOLTAGE`, `POWER_UNKNOWN` or `LOCALIZATION_LOST` respectively:
  - a driver exception;
  - undervoltage;
  - unknown power;
  - lost pose.
- On `UNKNOWN` or `BLOCKED`, forward motion stops at once.
- A latch revokes operator approval. Motion needs every one of these: e-stop reset, latch reset, a new approval, and `resume()`. **Nothing restarts by itself.**
- The e-stop is latched and independent of the supervisor. It works three ways:
  - every registered stop runs even if another raises;
  - an optional stop file lets any process trip it;
  - `POST /rover/estop` trips it from the dashboard.
  The physical stop (power switch, or lifting the robot) always comes first; see the runbook.
- `MOVE_BACKWARD` and `STRAFE_*` are refused unless an operator gives fresh evidence, because no sensor covers those directions. The detour "retreat" is a rotate-then-drive-forward, never blind reversing.
- `auto_approve` is refused when the driver is physical.

## 3. Navigation behaviour and its limits
- Routes come only from `planner.route.compute_route` (Dijkstra). A* with ALT landmarks is an optional benchmark. It is proven admissible, matches Dijkstra on all pairs under several block sets, and is not used for control.
- An edge is marked blocked only when all of these hold:
  - three consistent fresh readings (within 0.15 m of each other);
  - a trusted pose on that edge;
  - a heading aligned with the edge;
  - the obstacle lies strictly inside the edge.
- Otherwise the observation is `UNCONFIRMED` and the operator is asked.
- **Directional scanning uses wheel rotation, not a servo:**
  - left view at +45°, right view at −45°, back view at 180°;
  - every view rotates the whole robot under closed-loop heading control, in bounded segments of 90° or less;
  - each view sweeps centre and ±δ, so the corridor covers the robot's width;
  - each sample is a fresh reading, and the camera is asked for a frame.
- Side clearances are only recorded and compared. **A local side-step bypass is never attempted**, because one forward ranger can't measure how deep the obstacle is.
- A detour means going back to the previous node through a corridor the back view verified clear, then replanning with Dijkstra. Each new edge is checked again before the robot leaves the node.
- Ultrasonic limits:
  - the beam is narrow (about ±7.5° in the sim);
  - soft, thin or angled obstacles may give no echo;
  - range is about 3.5 m, so the full length of any edge is never verified in advance. It is re-verified continuously while moving.
- The sim world is topological and edge-local, so the real geometry beside trails is not modelled. `SIM_NODE_XY` exists only to give edges bearings.

## 4. Not done / out of scope
- No concrete hardware transport. `RecordingTransport` is a dry-run recorder only.
- No StickC bridge firmware, which the next step needs.
- No AprilTag localization, no 0.25 m coverage grid, and no occlusion modelling. These are optional research, and none of them is claimed.
- Not mounted into `dashboard/app.py`. That's the dashboard owner's call; see `contracts/ROVER_NAV_CONTRACT.md`.
