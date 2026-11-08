# camera_mapping: camera-only obstacle mapping and rescue intelligence (advisory)

The Pi 5 IMX708 camera (the existing SSH JPEG stream) feeds a pipeline on the Mac. Each frame runs through:

1. The **existing COCO Faster R-CNN** (`frcnn_r50_fpn_v2`, the same cached weights as `perception/`). It keeps person, chair, couch, bench, table, suitcase, backpack and other COCO classes. **COCO has no "box" class**, so boxes are not claimed.
2. A **distance estimate** per object (`distance.py`). Each estimate has a method, a 1-σ uncertainty and a status. The status is `ESTIMATED` or `UNKNOWN`/`REJECTED`, never verified.
3. **Tracking** (`tracking.py`). IoU association means repeated frames never become new obstacles. A track is confirmed after 2 hits, coasts while unseen and expires after 2 s. Its distance is a median filter with jump rejection.
4. A **robot-relative local grid** (`local_map.py`): 0.1 m cells, 4 m forward and ±2 m lateral, with states OCCUPIED / FREE / UNKNOWN.
5. A **deterministic corridor assessment** (`assess.py`): CLEAR / CAUTION / BLOCKED / UNKNOWN, plus an **advisory A\* route**.
6. A **rescue advisory** (`advisory.py`). It always produces a deterministic summary. Optionally it adds Qwen explanation text through the existing `rescue_qwen` RAG + guard service.
7. The **dashboard** (`dashboard/perception_source.py` + panels A–D in `dashboard/static/index.html`).

Nothing in this package can move the robot. `motion_authority` is always `NONE`, and the dashboard refuses states that claim otherwise. `rover_adapter.py` only produces UNCONFIRMED observations and bearing-only `CameraDetection`s. It refuses to produce a `RangeReading`, so the Grove forward-motion gate is unchanged.

## How the distance is estimated

| Method | How | When it is refused (→ UNKNOWN) |
|---|---|---|
| `GROUND_PLANE` | The bottom-centre of the box is taken as the floor contact and intersected with the floor plane, using the **tape-measured** lens height and pitch: `t = h / (sin θ + b cos θ)`, `x = t (cos θ − b sin θ)`, where `b = (v − c_y)/f_y`. σ is propagated from σ_h = 1 cm, σ_pitch = 1.5° and ±4 px contact error. | Mount unmeasured; the class may not stand on the floor (tv, bottle…); the box is cut by the bottom edge (only an upper bound is given); the contact is at or above the horizon; another box hides the bottom strip (occlusion); σ > 50 % of range. |
| `KNOWN_HEIGHT` | Pinhole range `Z = f_y H / h_px` from a wide prior: standing adult 1.70 ± 0.12 m, chair 0.88 ± 0.12 m. | Box cut at top or bottom; not upright (person h/w < 1.8: seated, lying, partly hidden); no prior for the class; box < 24 px. |
| `MONO_DEPTH` (optional, `--depth metric`) | Depth-Anything-V2 **Metric-Indoor-Small** median depth in the lower-central part of the box. | Always shown as `METRIC_UNVALIDATED` and **not fused**, unless the calibration report passes its gate on our camera. The **relative** model is never turned into metres. |

When two methods agree within 2σ they are inverse-variance fused. When they disagree, the estimate is **REJECTED**. Labels: `UNCALIBRATED_ESTIMATE` before a passing tape calibration, `CALIBRATED_ESTIMATE` after one, `UNKNOWN` otherwise.

**Intrinsics are nominal.** They come from the IMX708 datasheet (f = 4.74 mm, 1.4 µm pixels) and the sensor crop measured on the Pi. At 1280×720, picamera2 uses the 1536×864 binned mode with ScalerCrop 3072×1728. That gives fx = fy = 1410.7 px, HFOV 48.8° and VFOV 28.6°. Distortion is assumed to be zero. A checkerboard calibration would replace these values.

## Map semantics

- **FREE** means "observed now, and no *detected* obstacle". The camera cannot see untrained objects, glass, drop-offs, cables or low clutter. FREE is never a range-sensor measurement.
- **UNKNOWN** covers:
  - cells outside the 48.8° FOV;
  - the near blind zone (below the bottom image row);
  - cells beyond 3 m;
  - cells behind an obstacle (its occlusion shadow);
  - the whole wedge of a detection with unknown range;
  - cells not observed for 1.5 s;
  - **everything, while the mount height/pitch is unmeasured**.
- **OCCUPIED** is the footprint of a confirmed track, inflated by ±2σ.
- The map is **robot-relative** (no SLAM, no pose). If the robot moves, the map is cleared rather than shifted into a guessed frame.

## Assessment and routes

- **BLOCKED**: a confirmed obstacle overlaps the corridor within the lookahead (1.5 m), or its 2σ near edge is inside the stop distance (0.6 m). A bottom-cut box in the corridor whose upper bound is within the lookahead also counts.
- **CAUTION**: an obstacle overlaps the corridor only within its uncertainty band.
- **UNKNOWN**: any corridor cell is not FREE, or a detection with unknown range lies on the corridor bearing, or the mount is unmeasured.
- **CLEAR**: every corridor cell from the blind zone to the lookahead is FREE, and nothing is detected there.
- **Routes** (A\* on the grid; all `advisory: true`, `validated_for_driving: false`):
  - `DIRECT_ROUTE_OBSERVED_FREE`;
  - `ALTERNATE_ROUTE_OBSERVED_FREE`: the robot's whole half-width stays on FREE cells;
  - `ROUTE_THROUGH_UNOBSERVED_SPACE`: dashed on the dashboard, meaning "observe before considering";
  - `NO_SUPPORTED_ROUTE`: always the case while the mount is unmeasured.
- Routes never cross OCCUPIED cells or the wedge of an unknown-range detection.

## Limitations (read before the demo)

- **Every metre here is an estimate.** No tape calibration has been run yet: the status is `UNCALIBRATED` (see `docs/camera_mapping/CALIBRATION.md`).
- **The mount is unmeasured.** Until `calibrate set-mount` is run:
  - the ground-plane method is off;
  - there is no free space;
  - the corridor is never CLEAR;
  - no route is suggested.
- **A low rover camera (≈10–15 cm) cuts off standing people's heads** within several metres. The known-height method then refuses, and the feet (ground plane) are the only distance cue for people.
- The 48.8° FOV sees little beside the robot near the front. Most detours therefore read "through unobserved space".
- The detector covers only COCO classes. Scores are not calibrated probabilities.
- Qwen is explanation text only. Its output never reaches the map, the assessment or the rover. Motor-command patterns are discarded.

## Files

`config.py` (intrinsics, mount, calibration status) · `geometry.py` · `distance.py` · `detector.py` · `depth.py` · `tracking.py` · `local_map.py` · `assess.py` · `pipeline.py` · `advisory.py` · `rover_adapter.py` · `live.py` (runner) · `calibrate.py` (procedure + report) · `qwen_launcher.py` · `configs/imx708_robot.json` · `tests/`
