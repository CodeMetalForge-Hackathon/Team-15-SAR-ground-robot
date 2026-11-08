# MAP-09: Tape-measured camera distance calibration: NOT RUN

**Label:** none: no data exists. **Status:** NOT RUN.

**In plain words.** To know how accurate the camera's distances are, someone has to put a chair at measured spots (0.5, 1, 1.5 and 2 m) with a tape measure, and compare those with what the camera says. That has not happened. The camera's height above the floor and its tilt were not measured either. So every distance the system has ever shown is an *uncalibrated estimate*, and we can't say how far off it might be. The tools to do the calibration exist and are tested. The measurements are what is missing.

## 1. Objective (planned)

Measure the camera's distance error against tape ground truth, per method (`FUSED`, `GROUND_PLANE`, `KNOWN_HEIGHT`, `MONO_DEPTH`), and set `calibration_status` to `CALIBRATED` only if the gate passes.

## 2. What is missing

From [CALIBRATION.md](../../camera_mapping/CALIBRATION.md), all still **MISSING** at `d1b607a`:

1. Lens height above the floor (tape, ±5 mm).
2. Camera pitch (phone inclinometer; + = down).
3. Lens setback to the robot's front edge.
4. Robot width (0.20 m is a placeholder).
5. Chair front legs at 0.50, 1.00, 1.50 and 2.00 m, 10 frames each.
6. The camera aimed along the corridor floor. It faced a wall at 06:23 ET on 2026-11-08.

The shipped `camera_mapping/configs/imx708_robot.json` confirms the state: `mount.measured: false`, `height_m: null`, `pitch_deg: null`, `calibration_status: "UNCALIBRATED"`, `calibration_ref: null` and `depth_model_validated: false`. No `samples.jsonl` or calibration report exists in `$TEAM15_EVIDENCE` (checked during this audit: there is no `calibration/` folder).

## 3. Planned procedure, metrics and gate

`python3 -B -m camera_mapping.calibrate` provides `set-mount`, `capture` (records `gt_m`, `--by`, role, detection, latency, optional mono-depth), `fit-pitch` (uses FIT samples only; height is never fitted) and `report --apply`.

- **Metrics:** n, failure rate (a missed detection counts as a failure), median and P90 absolute error, median and P90 relative error, mean signed error (bias) and median latency, per method and per distance.
- **Why these:** the relative error is comparable across distances; the P90 catches the tail; the bias shows a pitch offset; the failure rate stops a method from looking accurate just by refusing hard cases.
- **Gate (`GATE`):** ≥ 4 distinct distances, median relative error ≤ 10 %, P90 relative error ≤ 20 %, failure rate ≤ 20 %. If it fails, the status is `CALIBRATION_FAILED`. Nothing is ever labelled VERIFIED.

## 4. What exists instead

- SYNTHETIC tests of the arithmetic: `test_metrics_and_percentiles`, `test_gate_requires_four_distances_and_low_error`, `test_evaluate_and_fit_pitch_on_synthetic_samples`, `test_report_refuses_missing_samples` and `test_missed_detection_counts_as_failure`. All passed at `d1b607a` (this audit). They show that the code computes the metrics correctly, **not** that the camera is accurate.
- The expected error magnitude, from geometry alone (illustrative, SYNTHETIC; see [05](../../05_DEPTH_AND_DISTANCE_ESTIMATION.md) §4.4): for a hypothetical 0.135 m / 4° mount, a 1° pitch error moves a 2 m reading to 1.59 m (−21 %). That alone would fail the 10 % median gate unless the pitch is fitted.

## 5. Claimed but no evidence

No record of any tape measurement, mount measurement or calibration capture was found in the repo, the evidence store, the Robot workspace or the session console logs.

## 6. Consequences

- Ground-plane ranging has never run on real data. There is no FREE space, the corridor is never CLEAR, and no route is suggested.
- Every displayed distance carries `UNCALIBRATED_ESTIMATE`.
- The judge-demo steps that depend on a measured mount (BLOCKED, alternate route) cannot be shown with the shipped config.

## 7. Next time

Follow [CALIBRATION.md](../../camera_mapping/CALIBRATION.md) Steps 0–5 (about 25 minutes, robot stationary). Commit only the updated config. Keep the frames in `$TEAM15_EVIDENCE/calibration/frames`.
