# MAP-03: Monocular depth (Depth-Anything-V2) on a recorded Pi frame

**Label:** RECORDED HARDWARE (one real Pi IMX708 frame, replayed on the Mac). **Status:** INCONCLUSIVE for accuracy, because there is no ground truth. COMPLETE for latency and integration.

**In plain words.** We tried two off-the-shelf "depth from one photo" neural networks on a saved Pi photo of a person standing close to the camera. The metric model said the person was about 0.41 m away, which looks plausible, but nobody measured the real distance, so we can't say whether it is right. The relative model only says what is nearer or farther, with no units, so it can never give metres. We kept the metric model as an optional, clearly-labelled cross-check that is **not** used in the distance shown to the operator.

## 1. Objective and hypothesis

Decide whether either Depth-Anything-V2 checkpoint can serve as a distance source or cross-check, without fine-tuning. Hypothesis: the metric-indoor model gives plausible metres at an acceptable latency (under 200 ms), and the relative model cannot give metres.

## 2. Date, hardware, software

- **Date:** 2026-11-08 ~11:26 UTC (session console log). Models downloaded at ~11:11 UTC.
- **Mac:** Apple M4 Pro, MPS.
- **Code:** `camera_mapping/depth.py` (`MonoDepth`, `box_depths`) in the pre-commit working tree. It is unchanged in substance at `d1b607a`.
- **Models:** `depth-anything/Depth-Anything-V2-Metric-Indoor-Small-hf` (metric, trained on synthetic Hypersim indoor scenes) and `depth-anything/Depth-Anything-V2-Small-hf` (relative inverse depth). Both are Hugging Face Hub checkpoints, kept in the Hub cache and not in Git.

## 3. Data and N

- One frame: `D1-b1794091323-000001.png`, 1280×720, captured by the Pi IMX708 on 2026-11-07 during the CAM-17 live test (one consenting person, no bystanders; see [CAM-15](CAM-15-pi-transport-and-first-e2e.md)).
- Faster R-CNN detects a `person` (score 0.87) with box `[22, 1, 739, 627]` (x, y, w, h). The box top is at the frame edge.
- Latency: median of 5 runs per model.
- **N = 1 frame.**

## 4. Ground truth

**None.** The person's distance was not measured when the frame was captured.

## 5. Metrics and why

The box depth is the median of the depth map over the lower-central box region (x 30–70 %, y 55–90 %), as in `box_depths`; the code samples there to avoid the background. Also recorded: the depth range over the whole frame, and inference latency. The geometry methods were run on the same box for a cross-check.

## 6. Results

| Model | Output kind | Latency (median of 5) | Person box value | Whole frame |
|---|---|---|---|---|
| Metric-Indoor-Small | metres | 116.6 ms | **0.41 m** (`ESTIMATED`, `METRIC_UNVALIDATED`) | 0.31–1.95 m |
| Small (relative) | unitless inverse depth | ≈117 ms | 2.160 (`UNKNOWN`, `RELATIVE_DEPTH_ONLY`) | — |

Geometry on the same box: `GROUND_PLANE` → `MOUNT_UNMEASURED`; `KNOWN_HEIGHT` → `BOX_TRUNCATED_BY_FRAME`; fused → `UNKNOWN` (`NO_METHOD_APPLICABLE`). **No cross-check was possible.**

Re-observation in [MAP-04](MAP-04-full-stack-resource-check.md) (same frame replayed with `--depth metric` every third frame, 2026-11-08 11:41–11:45 UTC): 144 depth evaluations, all 0.412 m. The median depth latency was 124.6 ms (max 180 ms) while Qwen and the detector shared the GPU.

## 7. Decision taken

Keep the metric model as an **optional cross-check** (`camera_mapping.live --depth metric`, every `--depth-every` = 3 frames). It is labelled `METRIC_UNVALIDATED` and **excluded from fusion** until `calibrate report --apply` shows that it passes the same gate as the geometry (`depth_model_validated`). Never convert the relative model to metres. No evidence justified fine-tuning.

## 8. Evidence

| File | Where | SHA-256 |
|---|---|---|
| `D1-b1794091323-000001.png` (contains a person; never publish) | `$TEAM15_EVIDENCE/camera_pi_validation/` | `5a22e84b658528d931f50e82c8a900828e2ddac18cd1cec683b3254091367d55` |
| MAP-04 state file with the depth values | `$TEAM15_EVIDENCE/camera_mapping/20261108-064151/perception.jsonl` | `0beec0d5f3909ee0b137072f70ae51ab50e1d20150eace1cad959bc88f2040b7` |
| Session console log | 2026-11-08 ~11:11–11:27 UTC | — |
| [EVALUATION.md](../../camera_mapping/EVALUATION.md) §4 | repo | — |

## 9. Limitations and confounders

- One frame, one scene, one person, very close and filling the frame, with no ground truth.
- The camera viewpoint (low, 48.8° HFOV) is unlike typical indoor training data.
- Latency was measured on MPS; CPU would be much slower. Neither model runs on the Pi.

## 10. Reproducibility

```bash
python3 -B -m camera_mapping.live --source replay --replay "$TEAM15_EVIDENCE/camera_pi_validation/*.png" \
    --depth metric --depth-every 3 --duration-s 30 --dashboard http://127.0.0.1:8000 --jsonl <out>
```

(Run `python3 -B -m dashboard.serve` first. The first run downloads the checkpoints from the Hugging Face Hub.)

## 11. What it proves / does not prove

- **Proves:** the integration works, the latency is about 120 ms on MPS, and the relative model cannot give metres.
- **Does not prove:** that 0.41 m is correct, or anything about accuracy at other distances or in other scenes.

## 12. Next time

Capture tape-measured samples with `calibrate capture --depth` at 0.5/1/1.5/2 m. The calibration report then evaluates `MONO_DEPTH` against the gate automatically.
