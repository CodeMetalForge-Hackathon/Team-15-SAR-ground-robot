# Camera live test report: Raspberry Pi IMX708 → Mac Faster R-CNN → dashboard

**Date:** 2026-11-08 (US Eastern; times in the evidence are UTC). Updated after Test 4 (drone), Test 5 (seated person) and Test 6 (lying person).
**Branch:** `test/camera-live-countdown` (built on `main` 06a69b9).
**Companion reports:** [CAMERA_DETECTION_EVIDENCE.md](CAMERA_DETECTION_EVIDENCE.md), [CAMERA_PERFORMANCE_RESULTS.md](CAMERA_PERFORMANCE_RESULTS.md).

Result labels used in all three reports:

- **LIVE HARDWARE**: measured on the real Pi camera and the real Mac detector.
- **SIMULATED**: synthetic data or fixtures, no camera.
- **NOT TESTED**: not exercised. No claim is made.

## Summary

| # | Question | Answer | Basis |
|---|---|---|---|
| 1 | Pi camera detected | **YES** | LIVE HARDWARE: `rpicam-hello --list-cameras` reports `imx708 [4608x2592 10-bit RGGB]` before every run. |
| 2 | Real frame captured | **YES** | LIVE HARDWARE: 3 runs, 96 + 101 + 96 frames, 1280×720. |
| 3 | Camera orientation correct | **YES** | LIVE HARDWARE: rotation 180 on the robot mount (orientation check 2026-11-07). The person and chair reference frames are both upright. |
| 4 | Person detection successful | **YES**: standing, seated, and lying feet-first (floor-level view) | LIVE HARDWARE, one consenting person in each run, no frame missed in any of the three. **Standing:** 96/96 frames, score ≥ 0.9995. **Seated:** 94/94, median 0.9999. **Lying:** 94/94, median 0.9914. |
| 5 | Supported object detection successful | **YES**, chair | LIVE HARDWARE: `chair` in 101 of 101 frames, score 0.9915–0.9965. The chair was never labelled person. |
| 6 | Empty-scene false detections | **0** | LIVE HARDWARE: 0 boxes from all 4 detector families in 96 frames. Replaying the 3-frame trigger gives 0 alerts. |
| 7 | Faster R-CNN inference latency | **190–196 ms median** (max 239–243) | LIVE HARDWARE on MPS. Chair run: 190 ms. Inside the person pipeline: 196 ms seated, 195 ms lying. All detectors together: 207–209 ms median. |
| 8 | End-to-end observation latency | Live capture → dashboard **499 ms** (seated) and **593 ms** (lying). First person frame → alert **0.4–0.6 s** (3-frame rule). | LIVE HARDWARE: measured from the dashboard's own receive time of the live `core.camera_bridge` delivery. |
| 9 | Dashboard integration | **PASS**, live | LIVE HARDWARE: the seated and lying sightings were pushed live during their runs. The standing sighting was imported afterwards through the same bridge. |
| 10 | Pi temperature and power | **Healthy** | LIVE HARDWARE, 6 runs: 46.6–50.5 °C, EXT5V 5.187–5.285 V, `throttled=0x0` in all 65 samples, no health stops. |
| 11 | Remaining blockers | See [Remaining problems](#remaining-problems) | |

## Setup

- **Pi:** Raspberry Pi 5 Model B Rev 1.1, 16 GB, portable power supply. rpicam-apps v1.14.0, libcamera 0.7.2, python3-picamera2 0.3.38, OpenCV 4.10.0. `camera_auto_detect=1`; there is no rotation overlay.
- **Camera:** Sony IMX708. Stream is 1280×720 at 5 fps, JPEG quality 80, sent over SSH. Receiver rotation is 180. The Pi reports `sensor_mount_rotation` 180 and `pi_transform` identity.
- **Network:** venue guest Wi-Fi plus Tailscale. The Mac reaches the Pi's Tailscale address (redacted) through the Tailscale DERP relay "nyc", not a direct connection.
- **Mac:** torch 2.12.0, torchvision 0.27.0, MPS available. Faster R-CNN ResNet-50 FPN v2 (COCO) weights are cached in `~/.cache/torch`.
- **Inactive throughout:** rover motors, gripper, LiDAR (RPLIDAR C1 is mounted but not validated), Qwen, and Hailo-8 inference. `hailort_service` was idle on the Pi.
- **Not touched:** GPIO, networking, PR #11, and the production dashboard on port 8791.

## Procedure and safeguards

Every capture went through `perception.live_test`, in this order:

1. **Consent check.** The person scene needs `--consent all-consented`.
2. **Manual Start.** The operator presses Enter in a Terminal window.
3. **Countdown.** A 10-second countdown runs with the camera off. Ctrl-C cancels, and nothing is captured. Both cancel paths were verified in a real terminal.
4. **Capture.** One bounded scene of about 20 s.
5. **Health monitoring.** Pi health is sampled every 2 s. Throttling, a temperature of 80 °C or more, or lost SSH stops the scene.

Image safeguards in no-people mode:

- **Empty scene:** runs with `--min-box-frac 1.01`. The pipeline cannot raise a sighting or store an image. Detections are logged per frame without pixels.
- **Object scene:** withholds its reference frame if the model returns any person box.

## Runs

| Run | Scene / consent | Status | Frames | Persons | Notes |
|---|---|---|---|---|---|
| `D1-b1794121685-empty` (empty-20261108T020800) | requested **empty**, no-people | **LIVE HARDWARE — PERSON PRESENT** | 96 | 96/96 frames | A consenting person was standing in view. **Not an empty-scene result.** It is excluded from the false-positive rate. Consent to capture, storage and dashboard display was stated by the operator on 2026-11-08. |
| object-20261108T022506 | object (chair), no-people | LIVE HARDWARE — chair | 101 | 0 | Reference frame saved: no person box was present. |
| `D1-b1794122894-empty` (empty-20261108T022809) | **empty**, no-people | LIVE HARDWARE — genuinely empty | 96 | 0 | No images stored, by design. The operator states the chair was removed and nobody was in view. |

The first run's evidence photo was stored in no-people mode before that safeguard existed. The safeguard was then added and is covered by regression tests (commit a7d9628). That photo is kept only because the person consented.

## Phase 4: dashboard integration (LIVE HARDWARE evidence)

Test dashboard: `http://127.0.0.1:8792/`. It is bound to localhost only. The production dashboard on 8791 was not touched.

| Check | Result |
|---|---|
| Real camera timestamps | **PASS.** `obs_time` equals the Pi sensor capture time (1794121685.932, 2026-11-08T07:08:05.931Z). Ingest enforces this to within 2 ms. |
| Unique observation IDs | **PASS.** `D1-b1794121685-000001`. `boot_id` is unique per run. |
| Image checksum / provenance | **PASS.** The PNG SHA-256 `6e90aef3…09e6` equals the sighting's `frame_sha256`. The served bytes are identical to the files on disk. Camera, transport, clock and rotation are all shown. |
| Bounding-box display | **PASS.** `x 500, y 1, w 345, h 714` in 1280×720, drawn on the annotated image. |
| Confidence display | **PASS.** Shows detector score 0.9996 (`frcnn_class_score`), labelled "not a probability". `confidence` is null. |
| Candidate review / UNCONFIRMED | **PASS.** Starts UNCONFIRMED. Confirm and Reject need an operator name (covered by regression tests). |
| Correct evidence image retrieval | **PASS.** `/evidence/{id}` returns the annotated JPEG and `/evidence/{id}/frame` returns the PNG. A headless browser render shows the upright image with its box. |
| No confusion of simulated and real data | **PASS.** The badge reads `LIVE-HW (bench)` and the run label reads **LIVE HARDWARE — PERSON PRESENT**. Sector G is labelled **OPERATOR-ASSIGNED / SYNTHETIC**. The map is labelled SYNTHETIC. The range card is labelled SIMULATED/DISCONNECTED. |
| Duplicates | **PASS.** A re-import is reported as `duplicate: true`. The dashboard still has 1 track and 1 alert. |
| No inferred identity, injury or distance | **PASS.** Nothing of the kind is inferred, and the page says so. |
| Live streaming push (camera → bridge → dashboard during a run) | **PASS** (Tests 5 and 6). Each run delivered 1 sighting and 0 duplicates. Live capture → dashboard was 499 ms and 593 ms. Each latency was recorded in the run's `run_annotation.json` before any dashboard reload. |

## Remaining problems

1. **Person coverage is still narrow.** Tested: one consenting person, indoors, in office lighting, standing, seated, and lying on their back. In the lying run the person lay **feet towards the camera**, which was at floor level, so the legs hid most of the torso and head. The following are all **NOT TESTED**:
   - lying side-on to the camera, or face-down,
   - partly covered,
   - person moving (scene D),
   - multiple people,
   - low light,
   - outdoors,
   - longer range.

   The secondary detectors depend on pose. HOG full-body found 96/96 standing frames, 0/94 seated and 0/94 lying. The face cascade found 94/94 seated frames and 0/94 lying. Only Faster R-CNN held up across all three poses.
2. **The empty-scene sample is small.** It is one room, one viewpoint and 96 frames. With 0 of 96 frames positive, the 95% upper bound on the per-frame false-detection rate is about 3.1% (rule of three). Window and glass reflections produced false person sightings on 2026-11-07 at the bench. They did not do so here, but no test has ruled them out.
3. **Other COCO labels are unreliable in this room.** The model reported these with no such object present:
   - `surfboard` (0.69–0.99) for a white floor mat and a round white object,
   - `tv` (0.50–0.83) for the chair's mesh back,
   - `bench`, `dining table` and `couch` for background furniture.

   Only `person` drives alerts, so this does not affect the person pipeline. Do not use other classes without validation.
4. **Live latency, measured once per pose.** It was 499 ms seated and 593 ms lying, plus 0.4–0.6 s for the 3-frame rule. That makes about 1.0–1.2 s from a person appearing to the alert. This is two runs, not a distribution.
5. **Per-frame detector time is now logged** (`detect_s` in the frame log, since commit 4035df1). Faster R-CNN took a median of 195–196 ms. Each frame takes about as long as the 200 ms gap between frames, so the pipeline runs at 4.68–4.69 fps and drops 7–8 stale frames per 20 s.
6. **Transport goes through a Tailscale relay** (DERP "nyc"). Capture to Mac took 0.19–0.31 s median and up to 0.42 s. A direct path was not established.
7. **Power and thermal results cover 20-second runs only.** Endurance on the portable supply is **NOT TESTED**.
8. **Hailo-8 is unused.** Detection runs on the Mac. On-robot inference is **NOT TESTED**.
9. **Empty-scene image safeguard limit.** It blocks only what the detector sees. A person the detector misses entirely could still appear in an object-scene reference frame, so the operator must keep the area clear.
10. **The drone cannot be recognised by this model** (Test 4). COCO has no drone, quadcopter, UAV or aircraft class. The drone run was **inconclusive**. Person boxes appeared in 100/100 frames, so the image was withheld. Upright boxes moving across the background point to people walking past. A static wide box at about [430, 325, 845, 225] in every frame has the same shape as the lying-person box in Test 6. Someone lying on the floor is a plausible explanation, but it is **not verified**. Any drone recognition needs a separate detector, kept apart from the person pipeline.
11. **The alert rule may miss distant lying people.** A sighting needs a person box at least 15% of the frame height (108 px). The feet-first lying box was 180–201 px tall at the tested distance (described by the operator as about 1.5–2 m). Further away, a lying person's box may fall below 108 px: the detector would see them, but no alert would be raised. This is **NOT TESTED**.
12. **Extra boxes on the same person.** In the lying run, 36 of 94 frames had a second weaker person box (0.60–0.77), usually a strip about 180×43 px over the upper body behind the legs. It was the same person and still produced one alert. `count_in_frame` (2 on the lying sighting) is therefore not a head count.
