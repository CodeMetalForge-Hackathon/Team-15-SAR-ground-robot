# MAP-04: Full stack on one Mac: detector + mono depth + Qwen RAG + dashboard (resource check)

**Label:** RECORDED HARDWARE (one real Pi frame replayed). **Status:** COMPLETE.

**In plain words.** Before the demo we needed to know whether everything could run at once on one laptop without slowing to a crawl. That means the camera detector, the depth model, the Qwen language model and the dashboard. We replayed a saved Pi photo for about 3.5 minutes with all of them running. The detector kept its usual speed of about 0.19 s per frame. It slowed to about 0.5 s only for single frames while Qwen was generating an answer. Qwen answered in about 5–6 s each time, and memory was fine.

## 1. Objective and hypothesis

Check that the detector, the depth cross-check, the Qwen RAG advisor and the dashboard can run concurrently on the M4 Pro without starving the perception loop. Hypothesis: the detector median stays under 250 ms, and Qwen does not block perception, because the advisor runs in its own thread.

## 2. Date, hardware, software

- **Date:** 2026-11-08, 11:41:57–11:45:35 UTC (218.2 s). The Pi had dropped off Tailscale at ~11:38 UTC, so the run used a recorded frame.
- **Mac:** Apple M4 Pro, 24 GB, MPS.
- **Code:** `feature/camera-mapping` at `f482f21` plus uncommitted edits. The runner process started at 11:41:49, *before* the review fixes were applied at 11:44, so it ran pre-fix code. The fixes do not affect latency.
- **Launch:** `scripts/camera_demo.sh --replay --depth`. The dashboard ran on :8000; the Qwen service on :8090 via `camera_mapping.qwen_launcher`, config `C_QWEN_RAG`, Ollama `qwen3.5:2b-q4_K_M`; the runner used `--depth metric`.
- **Models:** Faster R-CNN R50-FPN-v2 COCO; Depth-Anything-V2-Metric-Indoor-Small; base Qwen3.5-2B (q4_K_M) + RAG + guard. **The LoRA adapter was not used.**

## 3. Data and N

- 434 perception states (`RECORDED`) from replaying one frame, `D1-b1794091323-000001.png`, at 2 fps.
- 144 of them include a depth evaluation (every third frame).
- Qwen advisories were polled from `/api/perception/advisory` during ~70 s of the run.

## 4. Ground truth

Not applicable (resource test). The frame shows one person, with the box top cut by the frame.

## 5. Metrics and why

Detector, depth, mapping and total latency (median, P90, max); the Qwen advisory latency and status; and resident memory (from `ps`, session console log). These metrics show whether co-locating the models is viable.

## 6. Results

Full run, recomputed from the state file during this audit:

| Stage | n | Median | P90 | Max |
|---|---|---|---|---|
| Detector | 434 | 188.4 ms | 239.7 ms | 509.3 ms |
| Mono depth | 144 | 124.6 ms | 147.4 ms | 180.0 ms |
| Mapping | 434 | 0.1 ms | 0.3 ms | 0.5 ms |
| Capture → state posted | 434 | 227.9 ms | 413.3 ms | 524.7 ms |

Snapshot after the first ~85 s, as reported in [EVALUATION.md](../../camera_mapping/EVALUATION.md) §7 (the first 168 states):

- detector median 188 ms, P90 227 ms, max 491 ms;
- depth n = 56, median 126 ms, max 180 ms.

These are the same run, computed earlier while it was still going. The full-run figures above supersede them.

| Other measurement | Value | Source |
|---|---|---|
| Qwen advisories while the detector ran | 6 calls, 5,175–5,671 ms, all `QWEN_GUARDED` | session console log 11:42–11:43 UTC |
| Resident memory | runner 1.3 GB, Ollama Qwen 3.3 GB, dashboard < 0.1 GB; 62 % of system memory free | EVALUATION §7 (session `ps`) |
| Perception outputs | person track #1 VALID in 433/434 states; distance UNKNOWN ×434; corridor UNKNOWN ×434; route `NO_SUPPORTED_ROUTE` ×434; mono depth 0.412 m ×144 (not fused) | state file |

## 7. Failures

None in the resource sense. Detector spikes to about 0.5 s coincide with Qwen generation, which shares the Metal GPU.

## 8. Evidence

| File | Where | SHA-256 |
|---|---|---|
| `perception.jsonl` (434 states) | `$TEAM15_EVIDENCE/camera_mapping/20261108-064151/` | `0beec0d5f3909ee0b137072f70ae51ab50e1d20150eace1cad959bc88f2040b7` |
| `camera.log` | same | `8d965df0bc061202f1be0b1c659e56c00030a9021cd3c1547b64040fd87e88c8` |
| `dashboard.log` (empty) | same | `e3b0c442…b855` (empty file) |
| Session console log | 2026-11-08 11:41–11:45 UTC | — |

## 9. Limitations and confounders

- One static frame: the detector always sees the same image, which is unrealistically easy for caching and tracking.
- The live Pi transport was not included.
- Memory figures come from a single `ps` snapshot.
- The Qwen latency sample is small (6 calls).

## 10. Reproducibility

`scripts/camera_demo.sh --replay --depth`, with Ollama serving `qwen3.5:2b-q4_K_M` and the Qwen workspace at `$QWEN_ROOT`. Output goes to `~/Team15_evidence/camera_mapping/<timestamp>/`.

## 11. What it proves / does not prove

- **Proves:** the full demo stack fits on one M4 Pro, and Qwen does not block the perception loop.
- **Does not prove:** live-stream performance under the same load, or anything about perception accuracy.

## 12. Next time

Run the same check on the live Pi stream, log `ps` samples periodically, and record the commit hash in the run directory.
