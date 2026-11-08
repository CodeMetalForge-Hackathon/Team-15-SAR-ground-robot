# Grove → LiDAR migration plan

Grove (`ranging/`, `rover/` Grove adapter and their tests) is **untouched** by this PR. No Grove file is removed, and no motor-control behaviour changes.

| Stage | Description | Exit criteria | Status |
|---|---|---|---|
| **A** | Both drivers exist; Grove remains the default | the LiDAR package is merged with no change to `ranging/`, `rover/`, `dashboard/` or `core/` | this PR (draft) |
| **B** | LiDAR is an opt-in SIMULATED source (replay server, fixtures, dashboard card via `--range-fixture`) | the dashboard owner accepts D1/D2; Qwen consumes the `lidar` field in simulation | this PR provides it; owners pending |
| **C** | Real stationary hardware calibration and range checks | hardware checklist complete; explicit approval; `scan-once` passes; driver items §5; range accuracy at 0.3/0.5/1/2/3 m (±3 cm); measured forward offset recorded by name; quality and coverage thresholds calibrated; Pi latency measured; `get_throttled` 0x0 | **blocked**: no checklist answers, no approval |
| **D** | Dashboard and rover consume verified LiDAR snapshots | Issue #9 merged; rover owner allowlists `rplidar-c1` in a reviewed change (R1); dashboard owner adds a LiDAR provenance rule (D2) | blocked on C and #9 |
| **E** | LiDAR is the preferred default | a reviewed, user-approved change; stationary, then supervised wheels-off bench tests | blocked |
| **F** | Grove deprecated, or kept as a fallback | **explicit user decision** | not started |

## Interface requests (sent to owners; none implemented by this PR)

### Rover navigation owner (dashboard-integration-26)
* **R1 (Stage D, after Issue #9):** allowlist `source == "rplidar-c1"` in `rover/sensors.py:from_rover_fields`, alongside `grove-ultrasonic`, keeping every existing contradiction check. Require `forward_motion_allowed is True`, the Issue #9 hardening, for every hardware source.
* **R2:** if both sources run, combine them worst-case (`rover.sensors.combine`), never "any source clear".
* **R3:** `MotionLimits.sensor_max_age_s` stays 0.20 s. LiDAR age is measured from **capture start**.

### Dashboard owner (dashboard-integration-60)
* **D1 (revised with the dashboard owner, 2026-11-08):** the card status stays UNKNOWN, following the user's rule that `forward_motion_allowed=false` must never read CLEAR. A separate greyed advisory line may show "LiDAR sector: clear (advisory, motion not authorised)".
* **D2:** a LiDAR provenance rule for a future HARDWARE badge. It is exact, type-strict and live-only, and it requires:
  * `sensor_type == "RPLIDAR_C1"`;
  * `provenance.source_mode == "HARDWARE_VERIFIED"`;
  * `provenance.driver == "rplidar-c1"`;
  * `provenance.calibration_verified_by`, a non-blank str;
  * `provenance.calibration_verified_at`, an ISO-8601 str with timezone.

  These fields are emitted only after a Stage C sign-off. Until then the badge is always SIMULATED, and fixtures stay SIMULATED whatever they claim.
* **D3:** an optional second card fed by `GET /api/lidar` (`team15.lidar_panel/1`), or embedding `lidar/static/lidar_panel.html`. It must not displace the camera evidence, UNCONFIRMED state, operator approve/reject or the A→G route.

### Qwen advisory owner (team-15-qwen)
* **Q1:** consume `context.lidar` (`team15.lidar_advisory_context/1`) as optional and keep the existing range-event handling. The contract was sent 2026-11-07.
