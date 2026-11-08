# MAP-01: First live Pi camera run through the camera-mapping pipeline (latency, empty scene)

**Label:** REAL HARDWARE (Raspberry Pi 5 + IMX708 live stream; detection and mapping on the Mac). **Status:** COMPLETE for latency and throughput. Nothing about distance or map accuracy can be measured from this run: the scene was empty, and the mount was unmeasured.

**In plain words.** We pointed the live Pi camera, by accident at a wall, and ran the whole camera-mapping chain on the Mac for about 25 seconds. That chain is detector → distance → tracker → map → corridor verdict → route. We timed each stage. The detector takes about 0.19 s per frame. Everything else (distance, tracking, map, verdict and route search) takes about 2 ms. The largest delay is getting the picture from the Pi to the Mac (about 0.27 s). End to end, a state reached the dashboard about half a second after the photo was taken.

## 1. Objective and hypothesis

Measure the per-stage and end-to-end latency of `camera_mapping` on the live Pi stream. Hypothesis: mapping adds negligible time (under 10 ms) compared with the detector, and end-to-end latency stays under 1 s.

## 2. Date, hardware, software

- **Date:** 2026-11-08, 11:22:51–11:23:16 UTC (06:22 ET), 24.8 s.
- **Pi:** Raspberry Pi 5, IMX708 (standard lens), 1280×720 JPEG at 5 fps over SSH (Tailscale), receiver rotation 180.
- **Mac:** Apple M4 Pro, 24 GB, PyTorch on MPS, Python 3.13 (per [EVALUATION.md](../../camera_mapping/EVALUATION.md) §0).
- **Software:** the uncommitted working tree of branch `feature/camera-mapping`, about 8 minutes before its first commit `f482f21` (11:31 UTC). This is **not** the code at `d1b607a` (see §8).
- **Model:** torchvision Faster R-CNN R50-FPN-v2 COCO (`TorchObstacleDetector`, multi-class), the same cached weights as `perception/`.
- **Config:** `camera_mapping/configs/imx708_robot.json`: nominal intrinsics, mount **unmeasured**, `UNCALIBRATED`.

## 3. Data, N and procedure

- N = **117** perception states (one per processed frame), all `source_mode: LIVE-HW`, camera `pi5-imx708`, transport `ssh-jpeg`.
- Procedure: `python3 -B -m camera_mapping.live --source pi --pi-host $PI_HOST --dashboard <test dashboard> --jsonl <file>`. The state JSONL was then summarised with `statistics.median` and linear-interpolated percentiles.
- No images were stored; only the state JSONL.

## 4. Ground truth

None needed for latency. Scene content per the run: the camera faced a wall (EVALUATION §3 and CALIBRATION.md item 6), so **0 detections** were expected and observed.

## 5. Metrics and why

Per-stage latency (`latency_ms.*` in each state): `detector_ms`, `mapping_ms` (distance + tracking + grid + assessment + A\*), `annotate_ms`, `capture_to_rx_ms` (Pi sensor timestamp → Mac receive) and `total_ms` (capture → state posted). Median, P90 and max were used because latency distributions are skewed, so a mean hides the tail. Throughput is (N − 1) / span.

## 6. Results

| Stage | Median | P90 | Max |
|---|---|---|---|
| Faster R-CNN (MPS) | 186.5 ms | 203.9 ms | 447.1 ms |
| Mapping | 1.9 ms | 3.4 ms | 9.0 ms |
| Annotation | 1.3 ms | 2.1 ms | 5.2 ms |
| Pi capture → Mac receive | 274.4 ms | 347.7 ms | 379.1 ms |
| **Capture → state posted** | **479.8 ms** | **563.3 ms** | 804.4 ms |

Throughput: 117 frames in 24.8 s = **4.68 fps**. Assessment `UNKNOWN` ×117. Route `ROUTE_THROUGH_UNOBSERVED_SPACE` ×117. These numbers were recomputed during this audit from the state file and match EVALUATION.md §3 exactly.

## 7. Failures found

- **Route suggested with the mount unmeasured.** Every state proposed a route "through unobserved space", although no cell could be FREE. The code at the time ran A\* over an all-UNKNOWN grid. Fixed before `f482f21`: `suggest_route` now returns `NO_SUPPORTED_ROUTE` when `MountGeometry.usable` is False (`test_no_route_when_mount_unmeasured`). Every later run shows `NO_SUPPORTED_ROUTE`.
- **Camera aim.** The camera faced a wall, so the run exercised no detection or ranging.

## 8. Evidence

| File | Where | SHA-256 |
|---|---|---|
| `live_pi1.jsonl` (117 lines, states only) | **A temporary session scratch directory on the Mac, not in `$TEAM15_EVIDENCE`.** It may be lost on reboot; copy it into the evidence store if it is to be kept | `a4c2a8e4199514d9c7ec0b6f75fb9941e128395e2c7fa6c560fa8e4946e6cb63` |
| Session console log | 2026-11-08 ~11:22–11:27 UTC | — |
| [EVALUATION.md](../../camera_mapping/EVALUATION.md) §3 | repo | — |

## 9. Limitations and confounders

- `mapping_ms` (median 1.9 ms) includes an A\* search that **current code skips** when the mount is unmeasured. Later runs show a median mapping time of 0.1–0.3 ms for that reason, so 1.9 ms is a fair estimate of the cost *with* A\*.
- With an empty scene, the tracker and the distance code did almost nothing. Latency with many detections will be higher.
- Pi→Mac latency depends on the Tailscale path: at the venue it went through a relay (see [CAM-15](CAM-15-pi-transport-and-first-e2e.md)).
- One run, one network state, and a pre-commit code revision.

## 10. Reproducibility

The run can be repeated with `python3 -B -m camera_mapping.live --source pi --pi-host "$PI_HOST" --dashboard http://127.0.0.1:8000 --duration-s 25 --jsonl <out>` (the robot stationary and the Pi camera free). Exact reproduction of the pre-commit code is not possible: it was never committed.

## 11. What it proves / does not prove

- **Proves:** the full pipeline runs on the live Pi stream at about 4.7 fps. Mapping is computationally negligible next to detection. Capture-to-display latency is about 0.5 s (median).
- **Does not prove:** detection quality, distance accuracy, map correctness or any behaviour while moving.

## 12. Next time

Aim the camera along the floor first (CALIBRATION.md item 6). Store the JSONL in `$TEAM15_EVIDENCE/camera_mapping/` from the start. Record the git commit inside the state.
