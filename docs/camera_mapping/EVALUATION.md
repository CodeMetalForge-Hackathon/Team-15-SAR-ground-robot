# Camera mapping: quantitative evaluation (2026-11-08)

All numbers below were measured on 2026-11-08 between 06:08 and 06:30 ET.

- **Mac:** Apple M4 Pro, 24 GB, PyTorch 2.12 on MPS, Python 3.13.
- **Pi:** Raspberry Pi 5 with IMX708, 1280×720 at 5 fps JPEG over SSH (Tailscale), receiver rotation 180.

## 1. Distance accuracy: NOT YET MEASURED

No tape-measured samples exist yet. The mount height and pitch are unmeasured, so the status is **UNCALIBRATED**. No accuracy number is claimed: median error, P90 error and failure rate against ground truth are **pending** the procedure in `CALIBRATION.md`. The tooling that computes these numbers is `python -m camera_mapping.calibrate report`. Its arithmetic is unit-tested on SYNTHETIC samples only, which shows the code is correct, not that the camera is accurate.

## 2. Camera facts measured on the Pi

| Item | Value | How |
|---|---|---|
| Sensor | imx708 (standard lens), PixelArray 4608×2592, 1.4 µm cells | `Picamera2.camera_properties` |
| Mode for main=1280×720 | 1536×864 binned, **ScalerCrop (784, 456, 3072, 1728)** | picamera2 probe, 06:08 ET |
| Nominal intrinsics | fx = fy = 1410.7 px, cx = 639.5, cy = 359.5, HFOV 48.8°, VFOV 28.6° | datasheet focal length 4.74 mm × crop |
| Autofocus | LensPosition 1.0 dioptre, AfState idle | probe |
| Calibration files | none existed in the repo | search |

## 3. Live latency: real Pi stream, 117 frames, 24.8 s, 4.68 fps

The scene was empty: the camera faced a wall, so there were 0 detections. JSONL states were saved; no images were stored.

| Stage | median | P90 | max |
|---|---|---|---|
| Faster R-CNN R50-FPN-v2 (MPS) | 186.5 ms | 203.9 ms | 447.1 ms |
| Mapping (distance + tracking + grid + assessment + A\*) | 1.9 ms | 3.4 ms | 9.0 ms |
| Annotation | 1.3 ms | 2.1 ms | 5.2 ms |
| Pi capture → Mac receive | 274.4 ms | 347.7 ms | 379.1 ms |
| **Capture → state posted (end to end)** | **479.8 ms** | **563.3 ms** | 804.4 ms |

## 3b. Second live run via `scripts/camera_demo.sh` (06:52–06:53 ET, Pi camera re-aimed)

The Pi stream ran for 70.4 s: 266 LIVE frames at 3.76 fps, with a maximum gap of 0.8 s. The local map updated on every frame.

During this run a stray replay runner from an earlier test also fed the dashboard. That is how two bugs were found and fixed:

- the script's INT trap did not exit;
- the dashboard accepted two producers. It now returns 409 to the second one and Panel D shows the conflict.

Because of the shared GPU, this run's detector median of 246 ms is pessimistic.

| | Value |
|---|---|
| Frames with a detection | 24 / 266 (person ×10, chair ×14); real people and a chair near the robot |
| Distances | person boxes were cut by the frame top or bottom, giving UNKNOWN (`NO_METHOD_APPLICABLE`) |
| Side-cut chair | a 0.55–0.65-score chair cut by the left edge got a ~7.9 m known-height estimate. Known-height now refuses any edge-cut box (regression test added) |
| Corridor | UNKNOWN throughout (mount unmeasured), as designed |

After this run the Pi dropped off Tailscale again (06:55); a teammate was working on it.

## 4. Monocular depth evaluation (no fine-tuning)

Measured on the recorded Pi frame `D1-b1794091323-000001.png`. In that frame a person fills the view and the box top is cut.

| Model | Output | Latency (MPS, median of 5) | On the recorded frame |
|---|---|---|---|
| Depth-Anything-V2-**Metric-Indoor**-Small | metres (Hypersim-trained) | ≈117 ms | person ≈ 0.41 m; whole frame 0.31–1.95 m. Plausible, but **unvalidated** |
| Depth-Anything-V2-Small | **relative** inverse depth | ≈117 ms | value 2.16 (no unit). **Never converted to metres** |

**Decision:** the metric model runs as an optional cross-check (`--depth metric`, every 3rd frame) and is labelled `METRIC_UNVALIDATED`. It is excluded from the fused distance until the tape calibration shows it passes the gate. Geometry could not cross-check it on this frame: ground plane was refused because the mount is unmeasured, and known-height because the box is cut. No evidence justifies fine-tuning.

## 5. Recorded-frame regression

On `D1-b1794091323-000001.png`, Faster R-CNN detects `person` (score 0.87). With the shipped config the pipeline reports:

- distance **UNKNOWN** (`NO_METHOD_APPLICABLE`);
- corridor **UNKNOWN**;
- route `NO_SUPPORTED_ROUTE`.

This is the expected honest output. The automated test `test_recorded_pi_frame_person_detection_pipeline` covers it.

## 6. Qwen advisory: real calls

`rescue_qwen` service config C_QWEN_RAG with Ollama `qwen3.5:2b-q4_K_M`, called through `camera_mapping.qwen_launcher`:

- latency 4.0–5.9 s per advisory;
- status `QWEN_GUARDED`; guard passed, no fallback;
- `REQUEST_OPERATOR_REVIEW`, `person_evidence: UNCERTAIN`;
- cites RAG chunks, e.g. `team-ugv-guide#false-positives-at-ground-level-0`.

The advisory is asynchronous and never blocks the perception loop.

**Found:** `rescue_qwen.service` creates its SQLite index in the main thread, so every HTTP C_QWEN_RAG request fails with `sqlite3.ProgrammingError` (HTTP 500). The launcher works around it; the proper fix belongs to the Qwen workstream.

**LoRA adapter:** the mission adapter (`ckpt-0088`) is not served by `rescue_qwen.service`. That service only has Ollama/OpenAI backends, and the adapter needs the HF/PEFT backend. The Qwen workstream's own readiness report says the adapter must not be used for LiDAR, delivery or motion advice. The demo therefore uses the **base Qwen3.5-2B + RAG + guard**.

## 7. Full stack together: resource check (2026-11-08 06:42–06:50 ET, replay of a recorded Pi frame)

The dashboard, the camera runner (Faster R-CNN + Depth-Anything metric every 3rd frame) and the Qwen RAG advisory (Ollama, called about every 8–10 s) all ran at once on the M4 Pro for about 85 s.

| | Value |
|---|---|
| Detector latency (n=168) | median 188 ms, P90 227 ms; max 491 ms during Qwen bursts |
| Mono depth (n=56) | median 126 ms, max 180 ms |
| Qwen advisory while the detector runs | 5.2–5.7 s, all `QWEN_GUARDED` |
| Resident memory | runner 1.3 GB, Ollama Qwen 3.3 GB, dashboard < 0.1 GB; system 62 % free |
| Camera loss | the dashboard shows STALE → UNKNOWN within 2 s, the map is all UNKNOWN and the route is unusable; `scripts/camera_demo.sh` restarted the runner in about 10 s |

There is no resource conflict: Qwen inference on Metal slows the detector by at most about 2× for single frames, and only during generation.

The live Pi path was verified earlier (§3). The Pi dropped off Tailscale at 06:38, so the full stack was re-verified with RECORDED frames.

## 8. Independent review fixes (before merge)

A separate reviewer found these issues; each was fixed and has a regression test:

- **Stale distance after a close approach.** A tracked obstacle that later fills the frame bottom kept its old, farther median distance and could read CLEAR. Now range counts as known only while the current estimate is valid, and the bottom-cut upper bound means BLOCKED.
- **FREE persisting behind obstacles.** FREE cells behind a new obstacle, or inside an unknown-range wedge, survived up to 1.5 s. They now become UNKNOWN in the same frame.
- **Stale map still drawn.** Stale views still drew FREE/OCCUPIED cells. The server now blanks them, and the browser also degrades to UNKNOWN when polling fails. Outdated advisories are hidden.
- **SUPPORTED routes never possible.** Footprint inflation over-covered the unobservable start band.
- **Advisor thread could die silently.** It now catches errors and type-checks the guard.
- **Only two methods fused.** All methods are now fused, with pairwise consistency checks.
- **Lens setback ignored.** It now shifts the lookahead and stop distance to the robot front.
- **Frame posts could stall the loop.** Posts now time out after 1 s.

## 9. Automated tests

`python3 -B -m pytest -q` passes in full (counts in the PR description). The camera_mapping suites cover:

- calibration logic;
- geometric distances;
- UNKNOWN handling: unmeasured mount, bottom-cut boxes, horizon, non-floor classes, occlusion, posture, truncation, tiny boxes;
- fusion and rejection;
- tracking, jump rejection, expiry;
- map coordinates, FOV, blind zone, shadows, unknown-range wedges;
- CLEAR / CAUTION / BLOCKED / UNKNOWN;
- routes;
- record fields and provenance;
- empty scenes, scene changes, camera disconnect / staleness;
- dashboard API validation (VERIFIED and mislabelled data refused);
- Qwen isolation (failure, motor-command discard, state immutability, no motor imports);
- rover adapter (never a RangeReading; UNCONFIRMED only);
- calibration metrics and the gate;
- regression of the existing dashboard endpoints.
