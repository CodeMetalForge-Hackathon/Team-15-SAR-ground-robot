# Camera calibration: simple step-by-step (about 25 minutes, robot stays still)

Nothing here moves the robot, changes wiring, or touches the StickC or firmware. The Pi only streams camera frames, and every command runs on the Mac.

## What we still need from the hardware teammate

| # | Input | How to measure | Unit / sign | Status |
|---|---|---|---|---|
| 1 | **Lens height** | Tape from the floor to the **centre of the camera lens**. | metres, ±5 mm | **MISSING** |
| 2 | **Camera pitch** | Phone inclinometer on the flat back of the camera board. Read the tilt from vertical; looking down = positive. | degrees, + = down | **MISSING** |
| 3 | **Lens setback** | Horizontal distance from the lens to the robot's front edge. | metres | **MISSING** |
| 4 | **Robot width** | Widest point of the chassis, including the wheels. | metres | **MISSING** (0.20 m placeholder) |
| 5 | **Tape distances** | Chair front legs at 0.50 / 1.00 / 1.50 / 2.00 m from the floor point under the lens; 10 frames each. | metres | **MISSING** |
| 6 | **Camera aim** | Must look along the floor of the demo corridor. Mount it so the floor at about 0.4 m is in view (it faced a wall at 06:23). | — | **CHECK** |

Without items 1 and 2:

- there are no ground-plane distances (UNKNOWN);
- there is no free space;
- the corridor is never CLEAR;
- no route is suggested.

Without item 5, every distance stays **UNCALIBRATED_ESTIMATE**.

## Step 0: open a terminal on the Mac (copy-paste)

```bash
cd ~/Documents/Team-15-wt/camera-mapping
git pull
ssh team15-pi true && echo PI_OK
ssh team15-pi "ps -eo pid,args | grep -E '[p]icamera2|[r]picam-|[p]ython3 -u -'" || echo CAMERA_FREE
```

You need to see `PI_OK` and `CAMERA_FREE`. If anything else holds the camera (for example the demo script), stop it first.

## Step 1: record the mount

Replace the four numbers with what you measured:

```bash
python3 -B -m camera_mapping.calibrate set-mount \
    --height-m 0.135 --pitch-deg 4.0 --setback-m 0.03 --robot-width-m 0.20 --by "YOUR NAME"
```

Quick check: the blind zone is the floor the camera cannot see. It should be well under 1 m.

```bash
python3 -B -c "from camera_mapping.config import load_config; from camera_mapping import geometry as G; c=load_config('camera_mapping/configs/imx708_robot.json'); print('blind zone m', round(G.nearest_visible_floor(c.camera,c.mount.height_m,c.mount.pitch_deg),2))"
```

## Step 2: mark the floor

1. Find the floor point directly under the lens, using a string with a weight or by measuring the setback.
2. Put masking tape at **0.50, 1.00, 1.50, 2.00 m** straight ahead along the robot's centreline.

## Step 3: capture (one chair, about 1 minute per mark)

```bash
S=~/Team15_evidence/calibration/samples.jsonl
for D in 0.50 1.00 1.50 2.00; do
  read "?Chair FRONT LEGS on the $D m mark, facing the camera, everyone out of view. Press Enter "
  python3 -B -m camera_mapping.calibrate capture --source pi --pi-host team15-pi \
      --distance-m $D --object chair --role eval --frames 10 --depth --by "YOUR NAME" --samples $S
done
```

Every line should say `detected`. If a mark says `NOT DETECTED`, turn the chair slightly and re-run that one distance.

**Optional person set.** A consenting teammate stands with their toes on each mark; use `--object person`. Frames are saved under `~/Team15_evidence/calibration/frames`, never in Git.

## Step 4: report and apply

```bash
python3 -B -m camera_mapping.calibrate report --samples ~/Team15_evidence/calibration/samples.jsonl \
    --out ~/Team15_evidence/calibration/report --apply
```

The report shows, per method:

- failure rate;
- median and P90 absolute error (m);
- median and P90 relative error;
- bias;
- latency.

It also has a per-distance table.

**`CALIBRATED` only if all of these hold:**

- at least 4 distances;
- median relative error ≤ 10 %;
- P90 relative error ≤ 20 %;
- failures ≤ 20 %.

Otherwise the status is `CALIBRATION_FAILED`, and the estimates stay labelled uncalibrated. The mono-depth model is validated only if it passes the same gate. Nothing is ever labelled VERIFIED.

**If the gate fails because of a constant bias**, the pitch reading is probably off by a degree or two:

1. Capture 0.75 m and 1.25 m with `--role fit`.
2. Run `python3 -B -m camera_mapping.calibrate fit-pitch --samples $S --apply`.
3. Re-run Step 4.

## Step 5: share

```bash
cat ~/Team15_evidence/calibration/report/calibration_report.md
git add camera_mapping/configs/imx708_robot.json
git commit -m "camera_mapping: measured mount + calibration report"
git push
```

Paste the report into the PR. Commit only the config, never the frames.
