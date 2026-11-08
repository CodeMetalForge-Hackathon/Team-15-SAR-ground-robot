# Camera detection evidence: person, chair, empty room

All results here are **LIVE HARDWARE**: Raspberry Pi 5 with an IMX708 camera, frames sent over SSH (Tailscale) to the Mac, and torchvision Faster R-CNN ResNet-50 FPN v2 (COCO) running on MPS. Evidence lives outside Git under `~/Team15_evidence/camera_live_test/`. This file holds paths and checksums only. It holds no images.

Detector scores are raw `frcnn_class_score` values, not calibrated probabilities. No identity, injury, medical condition or distance is inferred from any image. Sector G is OPERATOR-ASSIGNED on the SYNTHETIC trail map; it is not a measured location.

## Comparison

| | Person present | Chair (object) | Genuinely empty |
|---|---|---|---|
| Run | `D1-b1794121685-empty` | object-20261108T022506 | `D1-b1794122894-empty` |
| Captured (UTC) | 2026-11-08 07:08:05–07:08:25 | 07:25:11–07:25:31 | 07:28:14–07:28:34 |
| Pipeline | person pipeline: FRCNN + HOG + Haar, 3-frame gate | same FRCNN weights, all COCO labels | person pipeline: FRCNN + HOG + Haar; 3-frame gate replayed from the frame log |
| Frames processed | 96 | 101 | 96 |
| FRCNN `person` frames | **96 / 96** (score 0.9995–0.9998) | **0 / 101** (no person box ≥ 0.5) | **0 / 96** |
| HOG full-body frames | 96 / 96 | not run | **0 / 96** |
| Upper-body / face frames | 0 / 0 | not run | 0 / 0 |
| Sightings (alerts) | **1** (93 later frames attached to it, not re-alerted) | n/a (objects do not alert) | **0** (replay: 0 would be raised) |
| `chair` frames | not evaluated | **101 / 101** (score 0.9915–0.9965) | not evaluated |
| Images stored | 2 (consented; see below) | 2 (reference frame, no person present) | **0** (no-people safeguard) |
| Verdict | correct detection | correct chair, correctly not a person | no false alerts |

## Person present: `D1-b1794121685-000001`

- **Status on dashboard 8792:** **UNCONFIRMED** (operator review pending). Run label **LIVE HARDWARE — PERSON PRESENT**; it does not count as an empty-scene result.
- **Consent:** stated by the operator on 2026-11-08, covering capture, storage and local test dashboard display. Not for public sharing. Recorded in `run_annotation.json`.
- **Detection:** class `person` (COCO), detector score **0.9996**. Bounding box **[x 500, y 1, w 345, h 714]** in a 1280×720 frame. One box in the frame.
- **Capture time:** `obs_time` 1794121685.932 (2026-11-08T07:08:05.931Z), from the Pi sensor clock. Pi frame #6, capture to Mac 194 ms.
- **Camera:** pi5-imx708, rotation 180 applied by the receiver, `pi_transform` identity.
- **Files** (folder `empty-20261108T020800/`):

  | File | SHA-256 |
  |---|---|
  | `D1-b1794121685-000001.png` | `6e90aef3bc18ea6984eef05a5263b31bcd0a05d36a51cf8ed35ed677c28e09e6` (equals the sighting `frame_sha256`) |
  | `D1-b1794121685-000001_annotated.jpg` | `93aa652fae407c4d7a06a65390a64100c9109e694afe323964cc763599cbcaa1` (recorded at import) |
  | `D1-b1794121685-empty_frames.jsonl` | `b2fd7daf84e0242f3bcf5c0f2a19021b543475b333543c9ad885deb17602cacd` |
  | `D1-b1794121685-empty_summary.json` | `fae740909c4b063e3c0d72b2a6ae0feb2bc6d299fa9bc94aa0266b3bc97b7b80` |

- **False positive?** No. A person was in view, and the box is stable across all 96 frames (x 494–510, w 342–352). The operator confirmed a consenting person. Scene D (person moving) was **NOT TESTED**: this person stood still.

## Chair: object-20261108T022506

- **Chair:** detected in **101 of 101 frames**, one chair per frame, score **0.9915–0.9965** (median 0.9949). Reference frame box **[x 600, y 138, w 375, h 581]**, stable across frames (x 596–604, h 558–592).
- **Chair vs person:** the chair was never labelled `person`. There were 0 person boxes at ≥ 0.5 in any frame. The glass behind the chair produced no person box either.
- **False object labels** (confirmed on the reference image; none of these objects was present):

  | Label | Score | Frames | What it actually was |
  |---|---|---|---|
  | `surfboard` | 0.69–0.99 | 2 per frame, all 101 frames | a white paper mat on the floor; a round white object at the bottom-right edge |
  | `tv` | 0.50–0.83 | 78 frames | the chair's mesh back (box overlaps the chair) |
  | `bench` | 0.50–0.72 | 78 frames | background furniture |
  | `dining table` | 0.50–0.63 | 66 frames | background furniture |
  | `couch` | 0.51–0.77 | 20 frames | background furniture |

  Only `person` drives alerts, so these do not affect the person pipeline.
- **Reference frame:** capture 1794122714.019 (07:25:14.019Z), Pi frame #16. Mean luma 111.8, Laplacian variance 207.8, exposure OK.

  | File | SHA-256 |
  |---|---|
  | `object_reference.png` | `195d6b644f6ac4067b20dc44d4b3b97064ef5204cc3bb80c185017c1ee0c6cf0` |
  | `object_reference_annotated.jpg` | `d54567ca76f25b58a3cf4be3e8ecab23ee81cda21720fd9d7365d384595ec8ac` |
  | `object_frames.jsonl` | every detection in all 101 frames |

## Genuinely empty: `D1-b1794122894-empty` (empty-20261108T022809)

- **Detections:** PERSON_DETECTOR, FULL_BODY_HOG, UPPER_BODY_HAAR and FACE_ONLY each produced **0 boxes in 96 frames**.
- **Alerts:** replaying the live trigger rule over the frame log raises **0 sightings**. The rule is a person box at least 15% of the frame height, held for 3 consecutive frames, with a 60 s re-arm.
- **Statistical limit:** 0 of 96 frames gives a 95% upper bound of about 3.1% per frame (rule of three). This covers one room and one viewpoint only.
- **No-people safeguard:** the pipeline ran with `--min-box-frac 1.01`, so it could store no image. It stored 0, which the runner checked after the run. Because there is no image, the scene's emptiness rests on the operator's statement that the chair was removed and nobody was in view.
- **Files:** `D1-b1794122894-empty_frames.jsonl`, `D1-b1794122894-empty_summary.json`, `pi_health.jsonl`, `run_report.json`.

## Person poses: standing vs seated vs lying (Tests 1, 5, 6)

All three runs are LIVE HARDWARE, one consenting person, about 20 s each. Every sighting is **UNCONFIRMED** on test dashboard 8792. The newest sighting (lying) is the primary record; seated and standing are in the history of track T1. Sector G is OPERATOR-ASSIGNED / SYNTHETIC.

| | Standing | Seated | Lying on back, feet towards the camera |
|---|---|---|---|
| Run / observation | `D1-b1794121685-empty` / `…-000001` | `D1-b1794124127-person` / `D1-b1794124127-000001` | `D1-b1794124793-person` / `D1-b1794124793-000001` |
| Sighting captured (UTC) | 07:08:05.931 | 07:48:48.079 | 07:59:53.715 |
| Consent | stated by operator after the run | typed `yes` at capture, 02:48:33 ET | typed `yes` at capture, 02:59:38 ET |
| Faster R-CNN person frames | **96 / 96** | **94 / 94** | **94 / 94** |
| Missed frames | 0 | 0 | 0 |
| Score min / median / max (run) | 0.9995 / – / 0.9998 | 0.9997 / 0.9999 / 0.9999 | 0.9845 / 0.9914 / 0.9971 |
| Score, sighting frame | 0.9996 | 0.9999 | 0.9951 |
| Sighting box [x, y, w, h] | [500, 1, 345, 714] | [364, 71, 555, 644] | [76, 290, 1076, 195] |
| Box range in the run | x 494–510, w 342–352 | x 362–380, w 527–555, h 632–648 | x 76–349, w 753–1076, h 180–201 |
| Box shape | tall | tall | **wide and short** (≈5:1) |
| Extra person boxes | none | none | 36 frames: a second box 0.60–0.77 on the same person |
| HOG full body | 96 / 96 | **0 / 94** | **0 / 94** |
| Face cascade | 0 / 96 | 94 / 94 | **0 / 94** |
| First person frame → alert | 0.4 s | 0.6 s | 0.4 s |
| Alerts | 1 | 1 | 1 |
| Live capture → dashboard | not live (imported later) | **499 ms** | **593 ms** |

**What these runs show:**

- **Faster R-CNN** detected the person in every frame in all three poses. The lying pose scored a little lower but stayed well above the 0.6 threshold.
- **HOG and the face cascade** depend on pose, so they are not useful as backups for seated or lying people.
- **The lying test** used a floor-level camera with the person **feet towards it**, so legs and shoe soles dominate the image and the torso and head are mostly hidden. A lying person side-on to the camera, or seen from a raised viewpoint, was **NOT TESTED**.
- **The alert fired** because the wide, short lying box (180–201 px tall) is above the 108 px minimum height.

**Evidence files** (stored outside Git; SHA-256 verified against the sighting and the served bytes):

| File | SHA-256 |
|---|---|
| `person-20261108T024843/D1-b1794124127-000001.png` | `54fc657fd5cbbb473ccc8fdc8dcf99e47319d02d590c2e646753dc7a45f681e7` |
| `person-20261108T024843/D1-b1794124127-000001_annotated.jpg` | `ebc6e387ba27735940b4f794de4b7106e1189d67e5eff7d19a6f3bda878126a6` |
| `person-20261108T025948/D1-b1794124793-000001.png` | `1c7d81120ade39edb131d0cd69a7175eeb4bdd24aa5cd0d33c138ef96378e8e3` |
| `person-20261108T025948/D1-b1794124793-000001_annotated.jpg` | `3920e388419329484bc6ae3a6f064558cf0f18a7d69eb64137d1ab92bd4bae5f` |

## Drone: object-20261108T024058 (Test 4)

- **Ground truth from the operator:** small quadcopter, powered off, battery disconnected.
- **Model classes:** none of the 80 COCO classes names it; no drone, quadcopter, UAV or aircraft. On the object-test page it shows as **UNKNOWN / UNRECOGNIZED**, and "prediction matches ground truth" is **NO**.
- **Predicted classes:** `person`, `surfboard` and `couch` appeared in 100% of frames. `cup` and `dining table` appeared in 18%; `bottle` and `book` in 3%. Nothing was relabelled, and there was no `airplane`, `bird` or `kite`.
- **Image:** withheld. The no-people safeguard blocked it because a person box appeared in 100/100 frames, so whether the drone is visible was **not verified**.
- **Possible drone box:** a small `cup`/`bottle` box at about (625–650, 342–392). It is unconfirmed.
- **Correct drone recognition rate:** 0%. This model cannot do better.

## Not counted

- **Run `D1-b1794121685-empty`** was requested as an empty scene, but a person was present. It is excluded from every empty-scene figure.
- **Orientation check images** `orient-1794095449791_*` (2026-11-07) show part of a person whose consent was not recorded. They are marked DO-NOT-TRAIN and DO-NOT-DISTRIBUTE, and they are not used here.
- **Historical bench evidence** `~/Team15_evidence/camera_pi_validation/` (5 files) is unchanged and its checksums still match.
