# Camera distance calibration: teammate procedure (about 25 min)

Nothing here moves the robot. The rover stays stationary and powered as it is now. Run all commands on the Mac from the repo root. The Pi only streams camera frames.

## You need

- A tape measure, masking tape, and a phone inclinometer app (or a level).
- One chair, plus a person for one optional extra set.
- A clear floor at least 2.5 m long in front of the robot.

## 0. Prerequisites

```bash
cd ~/Documents/Team-15-wt/camera-mapping      # or your checkout of feature/camera-mapping
ssh team15-pi true                            # must succeed without a password
ssh team15-pi 'pgrep -af "picamera|rpicam"'   # must print nothing: no one else is using the camera
```

## 1. Measure the mount (2 numbers + robot width)

1. **Lens height** `h`: from the floor to the centre of the camera lens, in metres, ±5 mm.
2. **Pitch**: lay the phone flat on the camera board's back (or on the lens face, and subtract 90°). The value is positive when the camera looks **down**.
3. **Robot width**: the widest point of the chassis, including the wheels.

```bash
python3 -B -m camera_mapping.calibrate set-mount --height-m 0.135 --pitch-deg 4.0 \
    --robot-width-m 0.20 --by "<your name>"
```

Replace the example numbers with your measurements. This writes `camera_mapping/configs/imx708_robot.json`.

## 2. Mark the floor

Ground truth is the forward distance along the robot's centreline, measured from the floor point directly below the lens.

1. Hang a weight on a string to find that floor point, or measure the lens setback from the robot front.
2. Put tape marks at **0.50, 1.00, 1.50, 2.00 m**. Extras such as 0.75 and 2.50 m are welcome.

## 3. Capture samples

For each mark:

1. Place the chair with its **front legs on the mark**, centred, facing the camera.
2. Step **out of view**.
3. Run the command below.

```bash
S=~/Team15_evidence/calibration/samples.jsonl
for D in 0.50 1.00 1.50 2.00; do
  read "?Place the chair front legs at $D m, step away, press Enter "
  python3 -B -m camera_mapping.calibrate capture --source pi --pi-host team15-pi \
      --distance-m $D --object chair --role eval --frames 10 --depth --by "<your name>" --samples $S
done
```

- **Optional pitch-fit set.** Repeat at **0.75 m and 1.25 m** with `--role fit`. Use these only if the inclinometer is unreliable; the report evaluates on `eval` samples only.
- **Optional person set.** Use `--object person` with the person's toes on the mark. Use a consenting teammate. Frames are saved under `~/Team15_evidence/calibration/frames`, never in Git.

## 4. (Optional) Fit pitch from the FIT samples

```bash
python3 -B -m camera_mapping.calibrate fit-pitch --samples ~/Team15_evidence/calibration/samples.jsonl --apply
```

## 5. Report and gate

```bash
python3 -B -m camera_mapping.calibrate report --samples ~/Team15_evidence/calibration/samples.jsonl \
    --out ~/Team15_evidence/calibration/report --apply
```

The report prints and saves `calibration_report.md` and `.json`. They contain, per method (FUSED / GROUND_PLANE / KNOWN_HEIGHT / MONO_DEPTH):

- sample count and failure rate;
- median and P90 absolute error (m);
- median and P90 relative error;
- bias;
- median latency.

They also include a per-distance table.

**Gate for `CALIBRATED`:**

- at least 4 distinct distances;
- median relative error ≤ 10 %;
- P90 relative error ≤ 20 %;
- failure rate ≤ 20 % on `eval` samples.

`--apply` writes `CALIBRATED` or `CALIBRATION_FAILED` to the config. It sets `depth_model_validated` only if MONO_DEPTH passes the same gate. Until then, every distance on the dashboard reads `UNCALIBRATED_ESTIMATE`. No distance is ever labelled `VERIFIED_DISTANCE`.

Send `~/Team15_evidence/calibration/report/calibration_report.md` to the team and commit only the updated `configs/imx708_robot.json`.
