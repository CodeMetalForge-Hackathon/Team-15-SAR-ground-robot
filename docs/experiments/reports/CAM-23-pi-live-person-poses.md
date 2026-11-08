# CAM-23 — Robot-mounted Pi camera: live person detection in standing, seated and lying poses (runs CAM-23, CAM-27, CAM-28, CAM-29)

**Label:** REAL HARDWARE (Pi 5 + IMX708 on the wheeled robot, stationary; Mac MPS; bench, indoors). **Status:** COMPLETE. Four runs, each about 20 s, each with one consenting person. 94/94–96/96 frames had a person box. Exactly one sighting per run, delivered UNCONFIRMED.

**In plain words.** With the camera on the robot, one consenting person stood, sat, lay with their feet towards the camera, and lay sideways in front of it, for about 20 s each. The Faster R-CNN detector found a person in every frame of every pose. The classical HOG detector found the standing person but missed the seated and lying ones completely. Each run raised exactly one alert. The alert reached the dashboard about half a second after the photo was taken, marked UNCONFIRMED for a human to review.

## 1. Objective and hypothesis

Measure whether the existing person pipeline, unchanged in thresholds and weights, detects a consenting person in rescue-relevant poses from the robot camera. Also measure the live latency to the dashboard. Hypothesis: Faster R-CNN detects all poses at ≥ 0.6, and the lying pose still clears the 108 px trigger height at ~1.5–2 m.

## 2. Date, hardware, software, model

| | |
|---|---|
| Date | 2026-11-08, 07:08–08:07 UTC (02:08–03:07 EST) |
| Hardware | Raspberry Pi 5 (16 GB) + IMX708 on the RoverC-Pro chassis. The rover did not move, and motors, gripper, LiDAR and Qwen were off. The Pi ran on a portable power supply. |
| Stream | 1280×720, 5 fps, JPEG q80, receiver rotation 180, sensor clock |
| Model | `torchvision_frcnn_r50_fpn_v2_coco`, threshold 0.6, `--min-box-frac 0.15` (108 px), 3-frame gate, 60 s re-arm, `--trigger person`; HOG/Haar logged |
| Software | `perception/` as merged on `main` (`06a69b9`), plus the unmerged local branch `test/camera-live-countdown`. That branch adds the consent-gated countdown runner (*perception/live_test.py*, not on `main`) and a timing-only change to `perception/live_camera.py` (per-detector `detect_s` in the frame log, commit `4035df1`, used by CAM-27–29). Commits at run time: CAM-23 `0ffcd3a`; CAM-27 `38dfa65`; CAM-28 `b7de5f9`; CAM-29 `417f45b`. |
| Dashboard | A local test dashboard on a separate port, fed live by `core.camera_bridge` for CAM-27–29. CAM-23's sighting was imported after the run (by the unmerged *core/evidence_import.py*), so it has no live latency. |

## 3. Runs

| ID | Run ID | UTC | Scene declared by the operator | Consent record |
|---|---|---|---|---|
| CAM-23 | `D1-b1794121685-empty` | 07:08:00 | Requested **"empty"**; a person was standing ~1–2 m away for the whole run. Reclassified `LIVE_HARDWARE_PERSON_PRESENT`; does **not** count as an empty-scene result. | Consent stated afterwards by the operator (`run_annotation.json`: CONSENTED for capture, dashboard display and storage; `public_sharing: false`) |
| CAM-27 | `D1-b1794124127-person` | 07:48:43 | Seated upright on a chair, facing the camera, ~1.5–2 m | Typed "yes" at capture, 02:48:33 EST |
| CAM-28 | `D1-b1794124793-person` | 07:59:48 | Lying on the floor, **feet towards the camera**, camera at floor level (torso and head largely hidden behind the legs) | Typed at 02:59:38 EST |
| CAM-29 | `D1-b1794125227-person` | 08:07:02 | Lying on the back, **seen side-on**, whole body across the frame, ~1.5–2 m | Typed at 03:06:52 EST |

## 4. Procedure

The runner checked Pi health (temperature, `get_throttled`, EXT5V, memory) and that no other camera process was running. For the person scenes it required typed consent. Then a 10 s countdown with the camera **off**, then about 20 s of the unchanged `live_camera --source pi` pipeline. CAM-27–29 piped into `core.camera_bridge`. Pi health was sampled every 2 s, with an automatic stop on throttling, ≥ 80 °C or lost SSH; it never triggered.

## 5. Ground truth

The **operator-declared** pose and the number of people (one). The session assistant also checked a downscaled copy of each evidence frame and deleted it afterwards. There are no annotated boxes, no IoU and no measured distance ("~1.5–2 m" is the operator's estimate).

## 6. Metrics and why

Person-frame rate and missed frames (recall proxy). Score range. Box size (whether it clears the 108 px trigger). HOG and face frames (the baseline). Sightings (de-duplication). Gate delay. Capture→Mac and capture→dashboard latency (operator-facing delay). Pi health (power safety).

## 7. Results

| | CAM-23 standing | CAM-27 seated | CAM-28 lying, feet first | CAM-29 lying, side view |
|---|---|---|---|---|
| Frames processed | 96 | 94 | 94 | 94 |
| PERSON_DETECTOR frames | **96/96** | **94/94** | **94/94** | **94/94** |
| Missed frames | 0 | 0 | 0 | 0 |
| Person score min / median / max | 0.9995 / 0.9997 / 0.9998 | 0.9997 / 0.9999 / 0.9999 | 0.9845 / 0.9914 / 0.9971 | 0.9913 / 0.9950 / 0.9978 |
| Sighting box `[x, y, w, h]` (1280×720) | [500, 1, 345, 714] | [364, 71, 555, 644] | [76, 290, 1076, 195] | [110, 288, 974, 188] |
| Box height range over the run | — | 632–648 px | 180–201 px | 178–203 px (all ≥ 108) |
| FULL_BODY_HOG frames | 96/96 | **0/94** | **0/94** | **0/94** |
| FACE_ONLY frames | 0 | 94/94 | 0 | 0 |
| Extra person boxes on the same person | — | none (max 1 box) | 36 frames with a second weaker box (0.60–0.77) on the upper body | every frame: 2–3 boxes (whole body, upper body, sometimes legs) |
| `count_in_frame` on the sighting | 1 | 1 | **2** (one person) | **2** (one person) |
| Sightings emitted | 1 | 1 | 1 | 1 |
| First person frame → sighting | — | 0.6 s | 0.4 s | 0.6 s |
| Processed fps | 4.75 | 4.68 | 4.69 | 4.66 |
| Pi frames received / delivered / stale | 105 / 97 / 7 | 103 / 95 / 7 | 104 / 95 / 8 | 105 / 95 / 9 |
| Capture → Mac, median / max | 290 / 386 ms | 296 / 435 ms | 293 / 387 ms | 264 / 410 ms |
| Faster R-CNN per frame, median / max | not instrumented | 196 / 239 ms | 195 / 241 ms | 200 / 223 ms |
| **Live capture → dashboard** | n/a (imported) | **499 ms** | **593 ms** | **508 ms** |
| Pi temperature | 47.7–50.5 °C | 47.2–49.9 °C | 46.6–49.4 °C | 46.1–49.9 °C |
| EXT5V | 5.241–5.272 V | 5.245–5.285 V | 5.187–5.268 V | 5.255–5.280 V |
| `get_throttled` (11 samples each) | 0x0 | 0x0 | 0x0 | 0x0 |
| Dashboard status | UNCONFIRMED | UNCONFIRMED | UNCONFIRMED | UNCONFIRMED |

Served images were byte-identical to the evidence files, and each PNG SHA-256 matched its sighting's `frame_sha256` (`run_annotation.json`: `frame_sha256_matches_sighting: true`).

## 8. Failures and issues found

- **Consent gap (CAM-23):** the "empty" scene ran the full pipeline, so it saved a person photo. The runner was fixed (on the unmerged branch) so that empty scenes cannot store images (`--min-box-frac 1.01`, alerts replayed from the log), and object scenes withhold the frame if any person box appears. Consent for CAM-23 was confirmed by the operator afterwards.
- **The first CAM-27 attempt was cancelled at the consent prompt** (Enter alone is not consent). The prompt was changed to accept "yes" in any letter case. The camera stayed off.
- **`count_in_frame` is a box count.** A lying person produced 2–3 overlapping boxes. An analysis-only grouping (boxes overlapping by ≥ 50% of the smaller box, chained through overlaps; commits `417f45b`, `4fe0508`) gives at most one person per frame across all three person runs. The CAM-29 `run_report.json` still holds the pre-fix figure ("2 frames with separate person boxes"), because run outputs are not edited.
- The CAM-28 pose was **narrower than planned**: feet-first at floor level rather than a fully visible body.

## 9. Evidence files (private, `$TEAM15_EVIDENCE/camera_live_test/`)

| File | SHA-256 |
|---|---|
| `$TEAM15_EVIDENCE/camera_live_test/empty-20261108T020800/D1-b1794121685-empty_summary.json` | `fae740909c4b063e3c0d72b2a6ae0feb2bc6d299fa9bc94aa0266b3bc97b7b80` |
| `$TEAM15_EVIDENCE/camera_live_test/empty-20261108T020800/run_report.json` | `e0353a87c34710c76c230fccbfd3571d6f5054b9a7e65def943256107be9c435` |
| `$TEAM15_EVIDENCE/camera_live_test/empty-20261108T020800/run_annotation.json` | `2af6144463a5a751bb210e20cf525eabd528a63047a5259dcf23b03c4a9f1f04` |
| `$TEAM15_EVIDENCE/camera_live_test/person-20261108T024843/D1-b1794124127-person_summary.json` | `109861440fdfbb18b0d4b8bb31d88c7efddf8db5aa055c2386b4c56006db8e03` |
| `$TEAM15_EVIDENCE/camera_live_test/person-20261108T024843/run_report.json` | `f5d98e08e5c95983b7e57c2731bc9f70864c060e2a0cea7f6d00b2f7435d1ac8` |
| `$TEAM15_EVIDENCE/camera_live_test/person-20261108T024843/run_annotation.json` | `a63f8a4418a5742ec58f8ba244f5a9dad4dc3dda6a427993b22bec4767b9cb6d` |
| `$TEAM15_EVIDENCE/camera_live_test/person-20261108T025948/D1-b1794124793-person_summary.json` | `98c8c024673c41948497410d96af02281f43c36570708e3b4438ff833075850f` |
| `$TEAM15_EVIDENCE/camera_live_test/person-20261108T025948/run_report.json` | `4a4505d60a77aa7fa3fb05a1fd3c02f20eb17c3ad090b45d8a5cf942f486df6d` |
| `$TEAM15_EVIDENCE/camera_live_test/person-20261108T025948/run_annotation.json` | `90dbb72ddca914efc3caee6e0ed6c911123b2a516c91ad462334359386fc9680` |
| `$TEAM15_EVIDENCE/camera_live_test/person-20261108T030702/D1-b1794125227-person_summary.json` | `bc560afb5de0ee44a779cae6519d2b8244a21d48f2a3ee3b911dae93c01a07a5` |
| `$TEAM15_EVIDENCE/camera_live_test/person-20261108T030702/run_report.json` | `91d61f4c1f0f5be8a4be4ccde808ac40ecd62af834fd799b64fc3f7477e7ce01` |
| `$TEAM15_EVIDENCE/camera_live_test/person-20261108T030702/run_annotation.json` | `d8a80d13e09039b2271f94e3e55be2b65968c02c1754767092084411b9a2e1a1` |

The SHA-256 values of the summary files above match the `derived_from` hashes recorded inside each `run_annotation.json`. Each folder also has `_frames.jsonl`, `pi_health.jsonl`, `sightings.jsonl` and the consented evidence PNG/JPEG, which are private and never published.

## 10. Limitations and confounders

One participant, one room, one camera position, daylight indoors, about 20 s per pose, a stationary robot. Distance was estimated, not measured. No occlusion, no multiple people, no motion. The lying runs were at ~1.5–2 m; at larger distances the 108 px trigger floor may suppress alerts (NOT TESTED). The 499–593 ms latency is for a dashboard on the same Mac. The countdown runner and timing instrumentation are not merged to `main`.

## 11. Reproducibility

The consent-gated runner is not on `main`. The equivalent with merged code, with a consenting person only:

```bash
export TEAM15_PI_HOST="$PI_HOST"
python3 -B -m perception.live_camera --source pi --sector G --operator bench-validation \
  --start-delay-s 10 --duration-s 20 --label person --out-dir "$TEAM15_EVIDENCE/camera_live_test/<run>" \
  | python3 -B -m core.camera_bridge --post http://127.0.0.1:8000/observations
```

## 12. What this proves / does not prove

- **Proves:** with this camera, mount and room, Faster R-CNN detects one consenting person in all four tested poses in every frame, HOG does not, and the full chain delivers one UNCONFIRMED sighting with verified evidence in about 0.5–0.6 s.
- **Does not prove:** recall in the field, in other lighting, at distance, with occlusion or for face-down people. It says nothing about the person's condition, which the system never infers.

## 13. Next time

Measure the distance with tape. Repeat the lying test at 2, 4 and 6 m. Add a second consenting person to test counting. Annotate boxes for IoU. Merge the consent runner after review, so the procedure is reproducible from `main`.
