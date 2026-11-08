# CAM-01 — Person-detector latency and frame-rate benchmark (synthetic micro-benchmark + live measurements)

**Label:** CAM-01 itself is **SYNTHETIC** input (random tensors) on real Mac hardware. The live figures summarised in §8 are **REAL HARDWARE** and come from the runs named there. **Status:** COMPLETE (micro-benchmark); live latency PARTIAL (see limitations).

**In plain words.** Before picking a detector, we timed two torchvision Faster R-CNN variants on a random 720p image, on the Mac's CPU and its GPU (MPS). The bigger ResNet-50 model took about 158 ms per image on the GPU, and the lighter MobileNet model 29 ms. Later, on live Pi frames, the ResNet-50 model took about 0.2 s per frame. Including the detectors, the whole pipeline kept up with the Pi's 5 frames per second. A person standing in front of the robot reached the dashboard about 1.0–1.2 s after first appearing.

## 1. Objective and hypothesis

Choose a detector that runs at or near the camera stream rate (5 fps) on the operator's Mac. Hypothesis: Faster R-CNN ResNet-50 FPN v2 on MPS runs under 200 ms per 720p frame, so about 5 fps is achievable.

## 2. Date, hardware, software

| | |
|---|---|
| Date | 2026-11-07, 18:53 UTC (session console log) |
| Hardware | Operator's MacBook Pro (Apple silicon, MPS backend). Exact chip and RAM not recorded in the log: **Unknown**. |
| Software | torchvision detection builders, `COCO_V1` weights. The benchmark script was a one-off in the session scratchpad and is **not in the repo**. The repo's equivalent model table is `DNN_MODELS` in `perception/detectors.py`. |
| Model / checkpoint | `fasterrcnn_mobilenet_v3_large_fpn-fb6a3cc7.pth` (≈74 MB) and `fasterrcnn_resnet50_fpn_v2_coco-dd69338a.pth` (≈167 MB), downloaded by torchvision to `~/.cache/torch/hub/checkpoints/` |
| Library versions at this audit | torch 2.12.0, torchvision 0.27.0 (2026-11-08). The versions on the benchmark day were not recorded. |

## 3. Data and N

One `torch.rand(3, 720, 1280)` tensor (random noise). **Not a real image.** Per model and device: 1 warm-up call, then 5 timed calls, averaged. `box_score_thresh=0.3`.

## 4. Procedure

For each model and each device (`cpu`, `mps`): build with COCO weights, `.eval()`, move to the device, run one untimed call, time 5 calls, and print the mean ms per frame and the class at index 1 (`person`).

## 5. Ground truth

None needed: this measures timing only. Detection output on noise is irrelevant.

## 6. Metrics and why

Mean wall-clock ms per call. This is the quantity that bounds the processed frame rate, $\text{fps} \le 1000 / t_\text{ms}$.

## 7. Results (SYNTHETIC input, real Mac)

| Model | CPU ms/frame | MPS ms/frame | COCO val2017 box mAP (torchvision metadata, not ours) |
|---|---|---|---|
| Faster R-CNN MobileNet-V3-Large FPN | 229 | **29** | 32.8 |
| Faster R-CNN ResNet-50 FPN v2 | 902 | **158** | 46.7 |

Decision: ResNet-50 FPN v2 became the default (`DEFAULT_DNN_MODEL`). It is ≈6 fps on MPS on this input and has the higher published accuracy. MobileNet stays selectable (`--dnn-model frcnn_mbv3_fpn`). **Its accuracy on our scenes was never measured.**

## 8. Live measurements that confirm or correct the micro-benchmark (REAL HARDWARE)

| Metric | Value | Run / evidence |
|---|---|---|
| First Faster R-CNN call on MPS (kernel compile) | 3,710 ms | CAM-19, session console log 2026-11-07 22:48 UTC |
| Pi run before the warm-up fix | 3 frames in 4.4 s = 0.68 fps | CAM-17, `D1-b1794091323-pi-validation_summary.json` |
| Pi run after warm-up (`ae8b088`) | 88 frames in 20.2 s = 4.36 fps | CAM-19, session console log (files not located) |
| Stage timing on the live Pi stream: capture → Mac | median 192, p90 257, max 582 ms | CAM-19, session console log |
| Decode + rotate | median 2.1 ms | same |
| Faster R-CNN after warm-up | median 202, p90 220, max 305 ms | same |
| HOG + Haar | median 11 ms | same |
| Evidence write (PNG + JPEG, sighting only) | median 13.7 ms | same |
| Faster R-CNN, object runner, 720p | median 190, p95 216, max 243 ms | CAM-24 `run_report.json` |
| Faster R-CNN inside the person pipeline (timing commit 4035df1) | median 196 / 195 / 200 ms; max 239 / 241 / 223 ms | CAM-27 / 28 / 29 `run_report.json` |
| All detectors per frame | median 209 / 207 / 213 ms | same |
| Capture → detection result (object runner) | median 444, p95 488, max 505 ms | CAM-24 |
| Processed fps, Pi stream at 5 fps requested | 4.66–5.01 | CAM-18, CAM-23–29 |
| Processed fps, MacBook camera 1920×1080 | 4.33–4.93 | CAM-03–14 summaries |
| Gate delay (first person frame → sighting) | 0.4–0.6 s | CAM-27/28/29 |
| Live capture → dashboard receive | 499 / 593 / 508 ms | CAM-27/28/29 `run_annotation.json` |

So on real frames the R50 model costs ~195–200 ms, not 158 ms. Real images give more proposals than noise, and the pipeline adds conversions. That is just below the 200 ms frame period, so the person pipeline processes 4.7 fps and drops 6–9 stale frames per 20 s run.

## 9. Failures

The 0.68 fps first Pi run (CAM-17) was a measurement trap: MPS compiles kernels on the first call. The fix is `warm_up()` in `perception/live_camera.py`, which discards one frame before capture. No other failures.

## 10. Evidence files

| File (in `$TEAM15_EVIDENCE`, private) | SHA-256 |
|---|---|
| `$TEAM15_EVIDENCE/camera_pi_validation/D1-b1794091323-pi-validation_summary.json` | `34ef05326d2050e624238edb04b686d69ec52e50195d9dee0135064aaf2e5dae` |
| `$TEAM15_EVIDENCE/camera_live_test/object-20261108T022506/run_report.json` | `8833f919fca8de6caa76b496a6be3a5ad4ff04a086247150e39c54c2b06d0bbf` |
| `$TEAM15_EVIDENCE/camera_live_test/person-20261108T024843/run_report.json` | `f5d98e08e5c95983b7e57c2731bc9f70864c060e2a0cea7f6d00b2f7435d1ac8` |
| `$TEAM15_EVIDENCE/camera_live_test/person-20261108T025948/run_report.json` | `4a4505d60a77aa7fa3fb05a1fd3c02f20eb17c3ad090b45d8a5cf942f486df6d` |
| `$TEAM15_EVIDENCE/camera_live_test/person-20261108T030702/run_report.json` | `91d61f4c1f0f5be8a4be4ccde808ac40ecd62af834fd799b64fc3f7477e7ce01` |

The micro-benchmark output exists only in the session console log (2026-11-07 18:53 UTC).

## 11. Limitations and confounders

- Random-noise input under-represents the work of the RPN and RoI heads on real scenes.
- Only 5 timed iterations, with no variance reported.
- Mac model and thermal state were not recorded. Other processes (the dashboard, and in later runs Ollama/Qwen) could compete for the GPU. The live tests deliberately kept Qwen off.
- The live per-frame timings exist only for runs on the unmerged branch `test/camera-live-countdown` (a timing-only change to `perception/live_camera.py`).
- `capture_to_rx` compares Pi and Mac clocks (±~0.1–0.2 s offset).

## 12. Reproducibility

```bash
python3 - <<'EOF'
import time, torch
from torchvision.models import detection as D
dev = "mps" if torch.backends.mps.is_available() else "cpu"
for name, fn, w in [("frcnn_mbv3_fpn", D.fasterrcnn_mobilenet_v3_large_fpn, D.FasterRCNN_MobileNet_V3_Large_FPN_Weights.COCO_V1),
                    ("frcnn_r50_fpn_v2", D.fasterrcnn_resnet50_fpn_v2, D.FasterRCNN_ResNet50_FPN_V2_Weights.COCO_V1)]:
    m = fn(weights=w, box_score_thresh=0.3).eval()
    for d in ("cpu", dev):
        mm = m.to(d); x = [torch.rand(3, 720, 1280, device=d)]
        with torch.no_grad():
            mm(x); t = time.time()
            for _ in range(5): mm(x)
        print(name, d, f"{(time.time()-t)/5*1000:.0f} ms/frame")
EOF
```

## 13. What this proves / does not prove

- **Proves:** on this Mac, R50-FPN-v2 on MPS runs at roughly the 5 fps stream rate once warmed up, and the live pipeline delivers a sighting to the dashboard about 0.5–0.6 s after the evidence frame was captured.
- **Does not prove:** accuracy, behaviour on other Macs, sustained thermal performance (runs lasted at most ~16 min on the Mac camera, CAM-22, and 90 s on the Pi), or anything about Pi-side inference.

## 14. Next time

Benchmark on recorded real frames, with ≥100 iterations and percentiles. Record the Mac model, macOS, torch version and power state. Also time MobileNet on the same real frames and measure its recall before deciding.
