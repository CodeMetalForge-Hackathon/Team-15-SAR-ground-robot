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

## 2. Range input (Grove ultrasonic worker → navigator). AGREED with PR #7
**Interface:** PR #7's versioned `team15.rover_range_fields/1`, the dict from `ranging.rover_io.GroveRangeIO().read_fields()`. PR #8 imports it in `rover/pi_io.py` (`PiRobotIO`). The raw `latest` ping is **not** parsed by navigation. The old `from_grove_reading()` wall-clock adapter has been removed.

PR #8 validates every dict with `rover.sensors.from_rover_fields(fields, expected_clock)` before using it:

| Rule | Behaviour |
|---|---|
| `schema` must be `team15.rover_range_fields/1` | otherwise ERROR |
| `clock` must equal `time.monotonic@<this host>` | otherwise ERROR (clock-domain rejection) |
| `t` must be finite, on the Pi's `time.monotonic` | more than 50 ms in the future means a clock fault: UNKNOWN. Older than **0.20 s** means stale: UNKNOWN, and while moving that latches `SENSOR_STALE` |
| `forward_motion_allowed` | ANDed in `assess()`, **and independently in `SafetySupervisor`** (refuses and stops MOVE_FORWARD) |
| `obstacle_status == BLOCKED` | BLOCKED at any range |
| `status == NO_ECHO` (real hardware) | UNKNOWN under every policy. `CLEAR_TO_MAX` is refused for physical IO |
| `blocked_threshold_m` | the required clearance is `max(required, blocked_threshold_m)` |
| contradictions (allowed+non-OK, allowed+range<threshold, range on non-OK, OK+`measurement_status`≠VALID, OK+UNKNOWN, range > 1.05·max, NaN/inf) | ERROR |
| missing key, wrong type, non-dict, reader exception, missing service, import failure | ERROR |

Every ERROR reading gets `t = -inf`, so it is never fresh.

Scan sampling: after each in-place rotation, the navigator waits for `scan_settle_readings` fresh readings, because PR #7's decision range is `min(latest, rolling median)`. Use at least 3 on hardware.

Points still open with PR #7 (posted on PR #7):
1. When `latest.mono_ns` is missing on the same host, `snapshot_to_rover_fields` sets `t = now`. That makes the reading look fresh. Please return ERROR instead.
2. PR #7's freshness check accepts readings up to 1.0 s in the future (`age < -1.0`). PR #8 rejects anything more than 0.05 s ahead. The stricter limit wins, so there is no conflict. This is noted for the bench.
3. At a 0.1 s ping interval with our 0.20 s limit, one or two missed pings latch `SENSOR_STALE`. That needs an operator reset. Keep the interval at 0.1 s or less, and report the measured rate in `health`.

`rover.sensors.RangeReading` (internal):

| field | type | meaning |
|---|---|---|
| `t` | float s | **capture** time on the controller's monotonic clock. Never the time it was received or re-sent. |
| `status` | `OK` \| `NO_ECHO` \| `ERROR` | |
| `range_m` | float \| null | set only when `status == OK` |
| `max_range_m`, `source`, `seq` | | as in PR #7 |
| `forward_allowed`, `blocked_threshold_m`, `service_status`, `hardware`, `reason` | | from PR #7's fields (`hardware` is false only for `source_mode == "SIMULATED"`) |

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
