# LiDAR data contract

All schemas are **new and additive**. Nothing existing is renamed or removed. Grove's `team15.range_reading/1` stays as it is.

## 1. `team15.lidar_scan/1` (one revolution, SENSOR frame)

| Field | Meaning |
|---|---|
| `sensor_id`, `model` (`RPLIDAR C1`), `model_label` (`C1M1-R2`), `frame_id` (`lidar_c1_sensor`) | identity |
| `frame` | "SENSOR (angle clockwise from the sensor 0 mark; not robot, not world)" |
| `seq` | scan sequence, per driver instance |
| `capture_start_mono_ns` | host `time.monotonic_ns` at the first node: **the capture time used for every age check** |
| `capture_end_mono_ns`, `duration_s` | the revolution's end |
| `capture_start_wall`, `capture_timestamp` | epoch seconds and UTC ISO (for humans and across hosts) |
| `completion` | `COMPLETE` / `PARTIAL` (too few points, < 300° swept, > 5 % corrupt) / `INTERRUPTED` |
| `point_count`, `valid_count`, `valid_coverage` | the fraction of 1° bins with ≥ 1 valid return |
| `status_counts` | per sample status |
| `source_mode` | `SIMULATED` / `HARDWARE_UNVERIFIED` (`HARDWARE_VERIFIED` is reserved; nothing sets it) |
| `provenance` | driver, device, host, scenario/fixture, corrupt-node count |
| `samples[]` | `bearing_deg` (SENSOR), `range_m` (null unless valid), `raw_distance_m` (0 = no return), `quality` 0–63, `valid`, `status` |

Sample status: `VALID`, `NO_RETURN`, `BELOW_MIN_RANGE`, `BEYOND_MAX_RANGE`, `LOW_QUALITY`, `NON_FINITE`, `SELF_OCCLUDED`. Only `VALID` carries a `range_m`.

## 2. `team15.lidar_sectors/1` (assessment, ROBOT frame)

There are eight 45° sectors centred on 0/45/…/315 (robot frame, CCW+): `FRONT, FRONT_LEFT, LEFT, REAR_LEFT, REAR, REAR_RIGHT, RIGHT, FRONT_RIGHT`. Each sector carries `status`, `min_range_m` (valid returns only), `min_bearing_robot_deg`, `coverage` and `reason`.

| Rule (in order) | Result |
|---|---|
| valid return ≤ `blocked_m` (0.35 m, PLACEHOLDER) | BLOCKED |
| coverage < 60 % of the sector's bins | UNKNOWN ("no return is not clear space") |
| nearest ≤ `caution_m` (0.75 m, PLACEHOLDER) | CAUTION |
| otherwise | CLEAR |
| alignment unverified | every sector UNKNOWN; `any_return_within_blocked` raised orientation-free |
| scan not COMPLETE / connection not SCANNING / health not GOOD | CLEAR and CAUTION → UNKNOWN |
| older than 0.5 s, or timestamp > 50 ms in the future | every sector UNKNOWN, `closest` null |

`forward_motion_allowed` (an input to the rover safety layer; it authorizes nothing by itself) requires all of the following:

* age ≤ **0.20 s** from capture start;
* FRONT is CLEAR or CAUTION;
* FRONT_LEFT and FRONT_RIGHT are not BLOCKED or UNKNOWN;
* the scan rate is known and within 7–13 Hz;
* 2 consecutive confirming scans;
* aligned, COMPLETE, SCANNING;
* `source_mode == SIMULATED`. **A real device never allows motion in this PR.**

Other fields: `scan_seq`, `scan_capture_start_wall`, `scan_capture_start_mono_ns` (the source scan's capture time), `mount` (`sensor_rotation`, `sign`, `forward_offset_deg`, `alignment_verified`), `connection` (`GATE_LOCKED | DISCONNECTED | CONNECTING | SCANNING | TIMEOUT | HEALTH_ERROR`), `stale_for_motion`, `stale_for_display`, `closest` (`range_m`, `sensor_bearing_deg`, `robot_bearing_deg`/`robot_sector` only if aligned, `is_person: null`), `last_valid_scan_wall`, `thresholds`, `range_semantics`, `person_distance_m: null`, `motion_authority: "NONE …"`.

## 3. Timing (0.20 s motion / 0.5 s display)

| Term | Value | Basis |
|---|---|---|
| One revolution | ≈ 100 ms at 10 Hz (125 ms at 8 Hz) | datasheet typical; **not measured** |
| Serial transfer | streamed during the revolution (≈ 2.5 kB/rev at 460800 baud ≈ 46 kB/s) | calculation |
| Processing (build + assess, 500 pts) | p50 0.58 ms, p95 0.61 ms on the bench Mac (`python -m lidar bench`) | **measured, SIMULATED input, Mac**; the Pi 5 is expected to be slower and must be measured |
| Age at assessment | ≈ 0.10–0.13 s from capture start | derived |
| Budget left for the 0.20 s motion limit | ≈ 70–100 ms for transport into the rover loop | derived |

A scan rate below 5 Hz can never satisfy the 0.20 s limit, so it fails closed (UNKNOWN), and the 7 Hz window floor rejects it anyway. Capture-to-processing latency on the real Pi is **unmeasured**; `scan-once` reports it at Stage C.

## 4. `team15.range_snapshot/1` compatibility snapshot (display only)

`adapters.to_range_snapshot` maps the **FRONT** sector into the existing ranging snapshot shape, for the dashboard card. It sets `sensor_type: RPLIDAR_C1`, `measurement_type: FORWARD_SECTOR_MIN_RANGE`, `provenance.driver: rplidar-c1`, and **always** `forward_motion_allowed: false`. Consequences with today's `core/range_view.py`:

* the badge is always SIMULATED, because `hardware_verified` requires `driver == "gpiod"`;
* LiDAR BLOCKED shows BLOCKED. LiDAR CLEAR/CAUTION shows **UNKNOWN** ("forward motion not allowed by ranging"). That is safe, but less informative; interface request D1 in GROVE_TO_LIDAR_MIGRATION.md covers it;
* `write_range_snapshot` refuses Grove's `/dev/shm/team15_range.json`.

## 5. `team15.rover_range_fields/1` (rover adapter)

`adapters.to_rover_fields` fills the existing interface honestly, with `source: "rplidar-c1"`. `rover/sensors.py:from_rover_fields` accepts only `grove-ultrasonic`, so **today it returns ERROR (t = −inf), which `assess` turns into UNKNOWN: no motion.** A test pins this. With the source allowlisted (Stage D, rover owner, after Issue #9), the fields are internally consistent (tested). Mapping: FRONT CLEAR/CAUTION/BLOCKED with a range → `OK`; FRONT UNKNOWN with no returns → `NO_ECHO`; stale, disconnected or other → `ERROR`.

## 6. `team15.lidar_advisory_context/1` (optional Qwen field)

This is an optional `context.lidar` in the advisory request. It is per-sector: `facing`, `status` (UNKNOWN when stale or disconnected), `min_range_cm` and `coverage`. It also has `closest_cm`, `source_mode`, `obs_time`, `stale`, `alignment_verified`, and these fixed fields:

* `association: "NOT_ESTABLISHED"`
* `person_distance_cm: null`
* `localization: "NONE"`
* `may_authorize_motion: false`
* `may_authorize_release: false`

Qwen may explain these values. It may not turn them into a clear path, a person distance, a world position, an injury inference, or a motion or release authorization.

## 7. Other schemas

`team15.lidar_panel/1` (dashboard display, see `lidar/panel.py`) and `team15.lidar_tracks/1` (VISUALIZATION ONLY; `is_person: null`; not a safety input).
