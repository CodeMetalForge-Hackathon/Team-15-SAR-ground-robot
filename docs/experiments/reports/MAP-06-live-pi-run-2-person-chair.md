# MAP-06: Second live Pi run: people and a chair, and the side-cut chair at "7.9 m"

**Label:** REAL HARDWARE (live Pi 5 IMX708 stream; real people and a real chair near the robot). **Status:** PARTIAL. Throughput and continuous updating were shown, and a ranging bug was found and fixed. Distance accuracy is not measurable: there is no ground truth, and the mount is unmeasured.

**In plain words.** We ran the one-command demo against the live Pi camera for about 70 seconds while teammates and a chair were in view. The pipeline ran at almost 4 frames per second without gaps. Most people were too close: their heads or feet were cut off by the edge of the picture, so the system said "distance unknown", which is correct. But a chair that was only partly in the picture, cut off at the left edge, was given a distance of 7.9 m and then 6.8 m. That is wrong in the dangerous direction: a cut-off object looks smaller, so it looks farther away. We changed the code so that any object touching the picture edge gets "unknown" instead.

## 1. Objective and hypothesis

Show continuous live operation of `scripts/camera_demo.sh` with real objects in view, and check that distance refusals behave as designed. Hypothesis: the pipeline sustains more than 3.5 fps, and every detection that cannot be ranged reads UNKNOWN.

## 2. Date, hardware, software

- **Date:** 2026-11-08, 11:52:06–11:53:17 UTC (70.4 s; 06:52–06:53 ET). The Pi had rebooted about 7 minutes earlier, and the camera was reported free.
- **Pi:** Raspberry Pi 5 Model B Rev 1.1, `imx708`, 1280×720 at 5 fps, JPEG quality 80, mount rotation 180, clock `SensorTimestamp+CLOCK_MONOTONIC->wall` (from `camera.log`).
- **Mac:** M4 Pro, MPS.
- **Code:** `c7ed6c5` (pushed 11:51:54 UTC). Known-height then refused boxes cut at the top or bottom only.
- **Launch:** `scripts/camera_demo.sh` (live; reusing the Qwen service on :8090).

## 3. Data and N

266 `LIVE-HW` states; 24 of them contain a detection (person ×10, chair ×14) across 8 tracks. Track validity: TENTATIVE 8, VALID 3, COASTING 13.

## 4. Ground truth

**None.** No tape distances were taken. The scene was described in the session only as people and a chair near the robot; the camera had been re-aimed by a teammate.

## 5. Metrics

Throughput, maximum frame gap, detector latency, the distance status per detection with the reason per method, and the assessment and route.

## 6. Results

| Metric | Value |
|---|---|
| Frames | 266 in 70.4 s = **3.76 fps**; max gap 0.80 s |
| Detector | median 245.9 ms, P90 332.3 ms, max 680.2 ms (inflated by a second runner on the same GPU; see [DSH-02](DSH-02-dashboard-duplicate-producer.md)) |
| Pi capture → Mac receive | median 269.4 ms, P90 373.0 ms |
| Capture → state posted | median 542.2 ms, P90 670.3 ms, max 1,004.9 ms |
| Person detections (10) | all `UNKNOWN`: `GROUND_PLANE` `MOUNT_UNMEASURED`, `KNOWN_HEIGHT` `BOX_TRUNCATED_BY_FRAME` (boxes touch y = 0, or reach y + h ≈ 716–720) |
| Chair detections (14) | 4 `UNKNOWN` (3 `BOX_TRUNCATED_BY_FRAME` at the top edge; 1 `NOT_UPRIGHT_OR_PARTLY_HIDDEN`). **10 `ESTIMATED` by `KNOWN_HEIGHT`** |
| Assessment / route | `UNKNOWN` ×266 / `NO_SUPPORTED_ROUTE` ×266 (mount unmeasured) |

**The side-cut chair (track #6).**

| frame_seq | Box [x, y, w, h] | Score | Validity | KNOWN_HEIGHT |
|---|---|---|---|---|
| 122 | [0.3, 51.1, 110.2, 156.9] | 0.653 | TENTATIVE | **7.913 m** = 1410.7 × 0.88 / 156.9 |
| 123–131 | [1.6, 22.3, 112.2, 183.8] | 0.545 | VALID, then COASTING | **6.756 m** = 1410.7 × 0.88 / 183.8 |

The box's left edge is 0.3–1.6 px from the frame border, so the chair was cut by the left edge. The visible height is not the whole chair, so `Z = fy·H/h_px` overestimates the range. Its corridor position was `LEFT_OF_CORRIDOR`, and the assessment stayed UNKNOWN, so no wrong verdict resulted in this run. The same error on a centred object could have placed an obstacle beyond the lookahead.

## 7. Fix

Commit `73539a7` (11:55 UTC): `known_height` refuses a box within `EDGE_MARGIN_PX` (4 px) of **any** frame edge (`BOX_TRUNCATED_BY_FRAME`). Regression test: `test_known_height_refuses_side_truncated_box`. [EVALUATION.md](../../camera_mapping/EVALUATION.md) §3b reports "~7.9 m" for scores "0.55–0.65". The data shows 7.91 m at 0.65 and 6.76 m at 0.545 for 9 states (1 VALID + 8 COASTING).

## 8. Evidence

| File | Where | SHA-256 |
|---|---|---|
| `perception.jsonl` (266 states) | `$TEAM15_EVIDENCE/camera_mapping/20261108-065157/` | `7017f97ce2671a281f0883b6f003386b1a29b877af72625f1660d5b9a47c98bb` |
| `camera.log` (Pi connect line; at the end `Timeout, server … not responding`, `ssh rc=255`, `reconnect 1/3`) | same | `86e07556d76a305fc046087eee2d7d4cb2e5b7f56ff6bc862e12ad5e201af1ad` |
| Session console log | 2026-11-08 11:51–11:55 UTC | — |

No images were stored.

## 9. Limitations and confounders

- No ground truth, and the mount is unmeasured, so ground-plane ranging never ran.
- A second runner (a replay) was posting to the same dashboard and sharing the GPU during this run. The detector latency here is pessimistic, and the dashboard's displayed state flipped between sources. The JSONL above is from the live runner only.
- The Pi dropped off Tailscale at the end of the run (~11:53–11:55 UTC). The runner then reconnected and failed.

## 10. Reproducibility

`scripts/camera_demo.sh` with `PI_HOST` set, the robot stationary and consenting participants. Only consenting people may be in view.

## 11. What it proves / does not prove

- **Proves:** live operation at about 3.8 fps with continuous map updates; that truncated person boxes are refused as designed; and that the side-edge truncation hole existed (now closed).
- **Does not prove:** detection recall or precision, distance accuracy, or map correctness.

## 12. Next time

Measure the mount first. Place the chair at taped distances. Make sure no other runner is live (the 409 lock now enforces this). Record the commit hash in the run directory.
