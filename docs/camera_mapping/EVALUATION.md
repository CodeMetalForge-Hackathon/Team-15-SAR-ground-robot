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

## 7. Automated tests

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
