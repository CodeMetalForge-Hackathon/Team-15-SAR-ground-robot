# CAM-03 — MacBook bench camera: person detection across poses (runs CAM-02 to CAM-08)

**Label:** REAL HARDWARE (MacBook Pro built-in camera, bench, indoors). **Status:** COMPLETE for CAM-06 and CAM-08, PARTIAL for CAM-07 (bystanders), INCONCLUSIVE for CAM-04/05 (wrong person in view). CAM-02/03 are smoke tests.

**In plain words.** A consenting teammate stood, then sat, in front of the MacBook camera in an open office. The original OpenCV full-body detector (HOG) missed them in more than a third of standing frames and in every frame when they sat with their back to the camera. The pretrained Faster R-CNN detector found them in every frame. The new de-duplication gate turned each run of hundreds of positive frames into exactly one sighting.

## 1. Objective and hypothesis

Check whether the existing full-body detector finds a consenting person standing full-body, seated, and seated facing away. If it does not, check whether a pretrained person detector does (task brief, session console log, 2026-11-07 18:51 UTC). Hypothesis: HOG misses non-upright poses, and Faster R-CNN does not.

## 2. Date, hardware, software, model

| | |
|---|---|
| Dates | 2026-11-07, 18:46–19:20 UTC (local machine clock about 13:46–14:20 EST) |
| Camera | MacBook Pro built-in camera, 1920×1080 frames (`frame_size` in the sightings) |
| Compute | Same Mac, MPS |
| Software | Branch `t1/camera-person`. CAM-02 at `c324983` (Haar-only detector). CAM-03–08 ran on the working tree between `44b7031` (committed 18:56:30 UTC) and `65684e3` (19:45:51 UTC). CAM-08 already had the per-box frame log; CAM-03–07 did not. |
| Model | `torchvision_frcnn_r50_fpn_v2_coco` (COCO_V1), score ≥ 0.6, plus OpenCV HOG/Haar |
| Trigger / gate | `--trigger person`, 3 confirm frames, 60 s re-arm. **Unverified:** whether `--min-box-frac` was active (the summaries of these runs have no `min_box_frac` field; the filter was committed in `65684e3`, after them). |

## 3. Runs (each its own ID)

| ID | Run ID | UTC | Label | Frames | fps | PERSON_DETECTOR | FULL_BODY_HOG | UPPER_BODY_HAAR | FACE_ONLY | Sightings (attached frames) |
|---|---|---|---|---|---|---|---|---|---|---|
| CAM-02 | `D1-b1-000001` (single observation) | 18:46:27 | first Haar face sighting | — | — | — | — | — | 1 hit, `haar_level_weight` 6.74 | 1 |
| CAM-03 | `D1-b1794077758-smoke` | 18:55:58 | smoke | 35 | 4.33 | 35/35 | 0 | 34 | 1 | 1 (32) |
| CAM-04 | `D1-b1794077889-standing` | 18:58:09 | standing (attempt 1) | 122 | 4.84 | 122/122 | 10 | 73 | 7 | 1 (119) |
| CAM-05 | `D1-b1794077937-standing2` | 18:58:57 | standing (attempt 2) | 58 | 4.80 | 58/58 | 1 | 0 | 1 | 1 (55) |
| CAM-06 | `D1-b1794078678-standing3` | 19:11:18 | **standing, full body, facing camera** | 97 | 4.83 | **97/97** | **61/97** | 97 | 80 | 1 (94) |
| CAM-07 | `D1-b1794078887-seated_away` | 19:14:47 | seated, profile (unplanned pose) | 98 | 4.87 | 98/98 | 20 | 29 | 11 | 1 (95) |
| CAM-08 | `D1-b1794079189-seated_back` | 19:19:49 | **seated, back to camera** | 98 | 4.89 | **98/98** | **0/98** | 98 | 0 | 1 (95) |

Frame counts are frames where *any* box of that family appeared, from `frames_with` in each summary. They are not counts of correct boxes on the teammate.

## 4. Procedure

`python3 -B -m perception.live_camera --declare-drone D1 --sector G --duration-s <20–25> --label <label>`, with the operator stepping away and the teammate positioned. CAM-04/05 had no start delay and caught the operator near the laptop instead of the teammate (PR #3). That is why `--start-delay-s` was added afterwards.

## 5. Ground truth

**Operator-declared scene** (pose and who was in view), stated in the session prompts and summarised in PR #3. There are no annotated boxes. PR #3 reports the PERSON_DETECTOR hits *on the teammate* as 96–97/97 standing, while the summary counts 97 frames with any person box. In CAM-06 the evidence frame also has a seated bystander and a window reflection (documented in [SIGHTING_FORMAT.md](../../../perception/SIGHTING_FORMAT.md)). For CAM-07 the exact count on the teammate is **unclear: 5–7 bystanders were in frame** (PR #3).

## 6. Metrics and why

Per-family frame hit rate (does a family see a person in a frame?). The number of sightings emitted, to test de-duplication. Time to first hit. Frame hit rate is the simplest metric that needs no box annotation. It cannot separate the target from bystanders.

## 7. Results

| Pose | Faster R-CNN on teammate | HOG on teammate | Face cascade on teammate | Sightings |
|---|---|---|---|---|
| Standing, full body (CAM-06) | 96–97/97 | 61/97 (63%) | 0 (face too small at that distance; its 80 hits were on a blank wall) | 1 |
| Seated, profile (CAM-07) | detected, 0.998 (exact count unclear) | 1/98 (PR #3) | 0 | 1 |
| Seated, back to camera (CAM-08) | **98/98** (scores 0.617–0.993, all boxes) | **0/98** | 0 | 1 |

Each run produced **exactly one sighting**, with 32–119 later positive frames attached rather than re-emitted.

## 8. Failures and false alerts observed

- The face cascade fired on a blank wall (80/97 frames, CAM-06). The upper-body cascade fired on ceiling ductwork. Neither can trigger by default.
- Faster R-CNN boxed people **reflected in or seen through windows** with scores up to 0.99. That motivated the 15% box-height filter (see [CAM-09](CAM-09-mac-empty-scene-60s.md)).
- CAM-04/05 detected the wrong person (the operator), a procedure failure.

## 9. Evidence files (private, `$TEAM15_EVIDENCE/camera/`)

| File | SHA-256 |
|---|---|
| `$TEAM15_EVIDENCE/camera/D1-b1794077758-smoke_summary.json` | `bef4ba7052b33d03d39dba717cddf64073f11a29eab47a6154b8103b99354980` |
| `$TEAM15_EVIDENCE/camera/D1-b1794077889-standing_summary.json` | `968967063c74150d4599f4fc72f5b399639815cfc3fb1d3caec2083a9780d9b6` |
| `$TEAM15_EVIDENCE/camera/D1-b1794077937-standing2_summary.json` | `d05185384787803f8b74f6e045877b8d2f3c6f7f5228feb10708ba18fd3bdee5` |
| `$TEAM15_EVIDENCE/camera/D1-b1794078678-standing3_summary.json` | `829a8da0d79283e7429f0222c721630bf130071f8fbdb7b1e2f88a9d7e2c293a` |
| `D1-b1794078887-seated_away_summary.json` | `8d9215f9b0c18ebbc9c96eaa97438e28c77a2c36638c6a1a23100b434c080c77` |
| `D1-b1794079189-seated_back_summary.json` | `45abb21a1fff69617e742db60881195607ee453cedc939df3d34d85f14d632cf` |
| `$TEAM15_EVIDENCE/camera/sightings.jsonl` (all 13 Mac-bench sightings) | `f12f72bb789325605e275ba6653c1f51f332cd45bf24dfdb0457c2a2a9ddead2` |
| CAM-02: `D1-b1-000001.json` in the earlier private folder `~/Documents/Team-15-evidence/camera/` | `5c0da9d41b12f5404adc427afa7da5d015c272b3e1f025643bbf451972d323d8` |

Each run also has a `_frames.jsonl` and evidence PNG/JPEG files. The images are not reproduced, and some include non-consenting bystanders.

## 10. Limitations and confounders

One teammate. Open office with bystanders and windows. One camera height and angle. About 20 s per pose. Pose and distance were not measured. Bystander boxes inflate the "any person box" counts. Two runs targeted the wrong person. The runs used uncommitted code (between `44b7031` and `65684e3`), so the exact code state is reconstructed from commit times.

## 11. Reproducibility

```bash
python3 -B -m perception.live_camera --declare-drone D1 --sector G --start-delay-s 8 --duration-s 20 --label standing
```

Use a consenting person, away from glass and bystanders. Compare `frames_with` per family in the summary.

## 12. What this proves / does not prove

- **Proves:** on this bench, HOG is unreliable for non-upright people and Faster R-CNN is far more robust. The gate gives one sighting per continuous presence.
- **Does not prove:** per-box accuracy, behaviour with several people, detection range, or performance on the robot's camera. Those were tested later on the Pi ([CAM-23](CAM-23-pi-live-person-poses.md)).

## 13. Next time

Clear the background first. Record distance and camera height. Annotate the target box in a few frames so hits on the target can be separated from bystanders. Commit the code before each run.
