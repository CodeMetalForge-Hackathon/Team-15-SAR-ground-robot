# CAM-15 — Pi 5 IMX708 → Mac transport, first end-to-end runs, and the warm-up fix (runs CAM-15 to CAM-19)

**Label:** REAL HARDWARE (Raspberry Pi 5 + IMX708, Tailscale relay, Mac MPS). **Status:** COMPLETE for transport (CAM-15, 16, 18). CAM-17 is PARTIAL: a person was detected, but the image is upside down and only 3 frames were processed. CAM-19 is COMPLETE (warm-up fix verified, orientation not verified at that point).

**In plain words.** We sent the Pi camera's frames to the Mac over SSH and measured how fast and how late they arrived: about 5 frames per second, roughly a quarter of a second after capture. The first live test with a consenting person produced a correct sighting on the dashboard, but the saved photo was upside down, and the detector ran at only 0.7 frames per second. That turned out to be a one-off 3.7 s start-up cost on the Mac's GPU. Warming the model up first fixed it (4.36 frames per second). A 90 s run with the camera pointed at a nearby object streamed 448 frames with no errors and no false person alerts.

## 1. Objective and hypotheses

1. JPEG-over-SSH through Tailscale delivers frames at ≥ 4.5 fps with sub-second delay and the Pi's true capture time.
2. `live_camera --source pi` produces valid sightings that the dashboard accepts, with `obs_time` equal to the Pi capture time.
3. The live frame rate matches the detector's benchmark (~5 fps).

## 2. Date, hardware, software

| ID | UTC (2026-11-07) | What | Code |
|---|---|---|---|
| CAM-15 | ~22:15 | Transport prototype: 40 frames, 1280×720, rotated on the Pi | Prototype script in the dashboard-integration session scratchpad (**not in repo**) |
| CAM-16 | ~22:40 | Stream-only check before the live test | `4d3093d` (`perception/pi_source.py`) |
| CAM-17 | 22:42:03–22:42:08 | Live test, one consenting person, no bystanders: `D1-b1794091323-pi-validation` | `4d3093d`, `--source pi`, rotation 180 |
| CAM-18 | 22:28:09–22:29:39 | 90 s end-to-end run through `core.camera_bridge` into a dashboard copy: `D1-b1794090489-pi-e2e` | `4d3093d` merged into the dashboard branch (`901c7e2`) |
| CAM-19 | ~22:47 | Stage timing, then a 20 s run after the warm-up fix | `ae8b088` |

Hardware: Raspberry Pi 5 Model B Rev 1.1 (16 GB), sensor `imx708`, Debian 13. Mac with MPS. The network was the venue Wi-Fi with client isolation, so Tailscale ran through a DERP relay (78–177 ms RTT, ≈7 Mbit/s; session console log). Model: Faster R-CNN R50 FPN v2 COCO, threshold 0.6, min box 15%, 3-frame gate.

## 3. Procedure

- CAM-15: an SSH-fed script captured 40 frames and sent each JPEG with its sensor capture time. The Mac recorded the arrival times.
- CAM-17: `python3 -B -m perception.live_camera --source pi --sector G --operator bench-validation --label pi-validation --out-dir $TEAM15_EVIDENCE/camera_pi_validation`. The sighting was posted to a dashboard copy at `901c7e2` on a separate port.
- CAM-18: `python3 -B -m perception.live_camera --source pi --sector G --duration-s 90 --label pi-e2e | python3 -B -m core.camera_bridge --post http://localhost:8001/observations`.
- CAM-19: per-stage timers on the live stream, then the warm-up commit and a 20 s run.

## 4. Ground truth

- CAM-17: the operator stated one consenting person in view, no bystanders. The session assistant checked a downscaled copy of the frame (upside down) and confirmed the person and the inversion.
- CAM-18: the camera was pointed at a close object (session console log), so no person was expected. No image was saved.

## 5. Metrics and why

Frames received, delivered and dropped; malformed frames; reconnects; processed fps; `capture_to_rx_s`. Also, whether ingest accepts the sighting and preserves `obs_time`. These are the properties the contract promises ([PI_CAMERA_CONTRACT.md](../../../contracts/PI_CAMERA_CONTRACT.md)).

## 6. Results

| ID | Frames | Processed fps | Capture→Mac | Stream stats | Detection | Outcome |
|---|---|---|---|---|---|---|
| CAM-15 | 40/40 received | 4.86 (transport only) | mean 256 ms, max 460 ms | 1.4 Mbit/s | Detector on one Pi still: **0 people unrotated, 4 after 180° rotation** (scores 0.60–0.996) | Transport chosen. Rotation shown to matter. |
| CAM-16 | — | 5.17 (stream only) | median 201 ms, max 411 ms | — | — | OK |
| CAM-17 | 3 processed in 4.4 s | **0.68** | 196 ms for the sighting frame (log median 327 ms over 3 frames) | received 74, delivered 55, **stale 18**, malformed 0, reconnects 0 | Sighting `D1-b1794091323-000001`, score 0.8665, box [21, 1, 739, 627] in 1280×720, at +3.8 s | Dashboard (`901c7e2` copy): track T1, UNCONFIRMED, "Raspberry Pi 5 IMX708 camera". An older dashboard build rejected it with 422 "unknown camera source". **Evidence image upside down.** |
| CAM-18 | 448 in 90.2 s | **4.97** | median 218 ms, max 388 ms (from the frame log) | received 452, delivered 448, stale 3, malformed 0, reconnects 0 | 0 person boxes, 0 HOG, FACE_ONLY in 2 frames | Bridge: sent 0 (no sighting), exit code 2 as designed |
| CAM-19 | 88 in 20.2 s | **4.36** | median 192, p90 257, max 582 ms | — | — | Warm-up fix works. First MPS call 3.71 s. Faster R-CNN median 202 ms after warm-up. |

## 7. Failures and root causes

- **0.68 fps (CAM-17)**: the first Faster R-CNN call on MPS took 3.7 s (kernel compilation), inside a 4.4 s run. Fixed in `ae8b088` with `warm_up()`, which runs once on a discarded frame.
- **Upside-down evidence (CAM-17)**: rotation 180 was the default, but on the bench the camera was upright. Initially the session wrongly concluded the default should be 0. It was then verified at the robot mount that 180 is correct there ([CAM-20](CAM-20-pi-orientation-check.md)). The historical image is **kept unchanged**; its SHA-256 still matches the sighting.
- **Contract drift**: the dashboard owner published a draft contract (binary `T15F` records, `PiFrameSource`). Five minutes later the camera owner shipped a different design. The dashboard adapted, and the contract was rewritten to match what shipped ([PI_CAMERA_CONTRACT.md](../../../contracts/PI_CAMERA_CONTRACT.md) header note).
- **Nearly black frames** in an orientation attempt at ~22:47 (mean ≈16/255, exposure at its 66.7 ms cap), probably a covered or face-down lens, so orientation could not be judged then.

## 8. Evidence files (private, `$TEAM15_EVIDENCE`)

| File | SHA-256 |
|---|---|
| `$TEAM15_EVIDENCE/camera_pi_validation/D1-b1794091323-pi-validation_summary.json` | `34ef05326d2050e624238edb04b686d69ec52e50195d9dee0135064aaf2e5dae` |
| `$TEAM15_EVIDENCE/camera_pi_validation/D1-b1794091323-pi-validation_frames.jsonl` | `02ac5f446c7d29f7e543fd32d6f76a546bf78ae48793e6d6d1c037e07dee5c89` |
| `$TEAM15_EVIDENCE/camera_pi_validation/sightings.jsonl` | `ac7953c4fae95040b8fe4bb942525518da2bdcc61e7615f83f0e444dd3aeb443` |
| `$TEAM15_EVIDENCE/camera/D1-b1794090489-pi-e2e_summary.json` | `9abd707e08ebe31b2f18041336bb0175718bb152a76d6c7c8605c0be9347b2ff` |
| `$TEAM15_EVIDENCE/camera/D1-b1794090489-pi-e2e_frames.jsonl` | `75ac3d778207bccbc2a4b9bd5cd44d0e6ecca9008d4122e552ae5998e1e5da02` |

CAM-15, CAM-16 and CAM-19 exist only in session console logs (2026-11-07 22:15, ~22:40 and 22:48 UTC). Their raw files were not found.

## 9. Limitations and confounders

The relay path may vary from run to run. The Pi–Mac clock offset (≈0.19 s SSH RTT bound) is included in the delay figures. CAM-17 had a close-up framing, not a full body. CAM-18 shows absence of false alerts only for one static close object. Runs were 4–90 s long.

## 10. Reproducibility

```bash
export TEAM15_PI_HOST="$PI_HOST"
python3 -B -m perception.live_camera --source pi --sector G --duration-s 90 --label pi-e2e \
  --out-dir "$TEAM15_EVIDENCE/camera" | python3 -B -m core.camera_bridge --post http://localhost:8000/observations
```

## 11. What this proves / does not prove

- **Proves:** the Pi→Mac path delivers ≈5 fps with ≈0.2–0.3 s delay and zero malformed frames over these runs. The Pi's capture time survives into `obs_time` and the dashboard. Ingest enforces the provenance rules.
- **Does not prove:** long-run stability, robustness to Wi-Fi drops on real hardware (reconnects were exercised only with a fake sender), or detection quality on the robot mount (tested later in CAM-23).

## 12. Next time

Run the warm-up before any timed run (now the default). Verify orientation with a non-person frame *before* the first person test. Keep each run's raw timing output as a file, not only in a console log.
