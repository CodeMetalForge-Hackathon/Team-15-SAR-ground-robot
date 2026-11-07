# RoverC-Pro navigation: integration contract (draft, for review)

Owner: rover navigation (`feature/rover-navigation`).
Consumers:
- Dashboard owner: section 3.
- Grove ultrasonic worker: section 2.
- Camera worker: section 4.

Nothing in `dashboard/`, `perception/` or `core/` is modified by this branch.

## 1. Units, labels and honesty rules
- **Distances are SYNTHETIC graph metres** from `fixtures/trail_graph_synthetic.json`. They are not measured RoverC travel. Every status carries `distances_label`.
- `traveled.kind` is either `SIMULATED_GROUND_TRUTH` (simulator) or `UNKNOWN` (hardware, because there is no odometry). No other value is valid until Gate 7.
- `pose.source` is one of:
  - `SIM_TRUTH`: simulation only.
  - `OPERATOR_CONFIRMED`: stationary at a node, and never trusted for autonomous motion.
  - `UNKNOWN`.
- `claims.autonomous_navigation_operational` stays `false` until Gates 5–7 pass on hardware.

## 2. Range input (Grove ultrasonic worker → navigator)
`rover.sensors.RangeReading`:

| field | type | meaning |
|---|---|---|
| `t` | float s | **capture** time on the controller clock. Never the time it was received or re-sent. |
| `status` | `OK` \| `NO_ECHO` \| `ERROR` | `NO_ECHO` means nothing came back within range |
| `range_m` | float \| null | set only when `status == OK` |
| `max_range_m` | float | the sensor's working maximum, from bench calibration |
| `source` | str | `grove-ultrasonic` on hardware |
| `seq` | int | increases by one per reading. The navigator needs a newer `seq`/`t` before each scan sample. |

How the navigator uses readings:
- A reading older than 0.20 s is **stale**. Stale while moving latches `SENSOR_STALE`.
- A timestamp more than 50 ms in the future is treated as a clock fault and gives `UNKNOWN`.
- `NO_ECHO` counts as **UNKNOWN** unless a bench calibration justifies `CLEAR_TO_MAX`. The simulator uses `CLEAR_TO_MAX` and says so.
- Open questions for the Grove worker:
  - Which bus or pin is it on (Pi GPIO or StickC)?
  - What update rate does it achieve? The navigator needs at least 10 Hz.
  - What is the measured minimum and maximum range against our test targets?

## 3. Status output (navigator → dashboard)
- `GET /rover/status` is served by the optional router `rover.status_api.rover_router`, or you can call `Navigator.status()` directly.
- Schema `team15.rover_nav_status/1`. Required keys are listed in `rover/status_api.py::REQUIRED_STATUS_KEYS`.

| dashboard item | field |
|---|---|
| Current route | `route.path`, `route.edges`, `route.length_m` |
| Remaining planned distance | `remaining_planned_m` (synthetic) |
| Blocked edges | `blocked_edges`, and the evidence for each in `blockers[]` |
| Reason for rerouting | `last_reroute_reason`; the history is in `reroutes[]` |
| New route after rerouting | `reroutes[-1].new_route`, `new_length_m`, `retreat_m`, `new_remaining_m` |
| Latest obstacle reading | `latest_range` |
| Sensor validity | `sensor.valid`, `sensor.forward_assessment`, `sensor.age_s`, `sensor.reason` |
| Robot motion state | `state`, `state_detail`, `motion.active_command`, `motion.output` |
| Emergency-stop state | `motion.estop`, `motion.safety_latch` |
| Last verified pose | `pose` (`{"source":"UNKNOWN"}` when it is not verified) |
| Heading | `heading.deg`, `heading.source` (`UNKNOWN` when there is no measurement) |
| Directional scan | `last_scan.views.{left,right,back}` (status, min range, sweep samples) |
| Operator actions needed | `operator_requests[]` (PENDING only) |
| Camera requests | `camera_requests[]`; `suggested_viewpoints[]` (graph nodes only, never coordinates) |

`POST /rover/estop` trips the latched e-stop. On purpose, there is **no** HTTP endpoint that resets the e-stop, approves motion or starts a mission.

## 4. Camera (camera worker ↔ navigator)
- The navigator raises `camera_requests` after each scan view and on arrival at each node.
- Person detections become `camera_person` observations with status `UNCONFIRMED`, `dynamic: true` and `coordinates: "NONE (no localization)"`. They never block routing until a human confirms them through `ObservationLog.review`. A confirmed person blocks the edge for 30 s, then shows as `STALE`, never as clear.
- Proposed mapping to the existing sighting format: keep `how=SECTOR_ONLY`, put no coordinates in the sighting, and carry the edge context in a note. This needs agreement with T1/T2 before it is wired in.

## 5. Clearing a blocked edge
`ObservationLog.clear_edge(edge, source, operator, evidence)` needs:
- a source different from every blocking observation (for example a camera frame reviewed by an operator, after an ultrasonic block);
- a named operator;
- an evidence string.

Dijkstra then automatically gets the shorter route back (scenario F).
