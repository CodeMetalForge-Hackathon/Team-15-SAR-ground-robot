# CAM-24 — Robot-mounted Pi camera: empty-room, chair and drone scenes (runs CAM-24, CAM-25, CAM-26)

**Label:** REAL HARDWARE (Pi 5 + IMX708 on the stationary robot; Mac MPS; bench). **Status:** CAM-24 (chair) COMPLETE. CAM-25 (genuinely empty room) COMPLETE, PASS. CAM-26 (powered-off quadcopter) INCONCLUSIVE.

**In plain words.** We checked what the detector does when there is *no* person. In an empty room, for 20 s, none of the four person detectors drew a single box, so no alert could be raised. With an empty office chair in view, the model called it "chair" in every frame and never called it a person. It did give silly labels to other things, such as "surfboard" for a paper mat. With a small drone on a table, the model could not name it, because its 80 COCO classes contain no drone. People also wandered into the background, so the safeguard withheld the image and the test could not be judged.

## 1. Objectives and hypotheses

- **CAM-25:** an empty scene raises zero false person alerts under the real trigger rule (score ≥ 0.6, height ≥ 108 px, 3 consecutive frames).
- **CAM-24:** Faster R-CNN detects an operator-placed chair (a COCO class) and does not confuse it with a person.
- **CAM-26:** baseline: what the COCO model predicts for a powered-off small quadcopter. COCO has no drone class, so a correct recognition is impossible by construction.

## 2. Date, hardware, software, model

| ID | Run | UTC (2026-11-08) | Code (branch `test/camera-live-countdown`, unmerged) | Pipeline |
|---|---|---|---|---|
| CAM-24 | `object-20261108T022506` | 07:25:06 | `a7d9628` | Object runner: Faster R-CNN only, **all COCO classes**, threshold 0.5. No HOG, no gate. |
| CAM-25 | `D1-b1794122894-empty` | 07:28:09 | `a7d9628` | The full `live_camera --source pi` pipeline (all four families), but `--min-box-frac 1.01`, so no sighting or image can be stored. Alerts were then counted by replaying the real rule (0.15) over the frame log. |
| CAM-26 | `object-20261108T024058` | 07:40:58 | `2b86a06` | Object runner, `--object-label drone` (a class the model lacks) |

Hardware as in [CAM-23](CAM-23-pi-live-person-poses.md): Pi 5 on a portable supply, 1280×720 at 5 fps, rotation 180. Model: `torchvision_frcnn_r50_fpn_v2_coco` (`fasterrcnn_resnet50_fpn_v2_coco-dd69338a.pth`, recorded in the CAM-26 report). Consent mode `no-people` for all three.

## 3. Procedure

Pi health pre-check, manual Enter, 10 s countdown with the camera off, then about 20 s of capture, with Pi health every 2 s. Under `no-people` consent the runner never saves an image from the empty scene, and saves an object reference frame only if that frame has no person box.

## 4. Ground truth

- **CAM-25:** the **operator's statement** that the chair was removed and nobody was in view. No image was stored by design, so emptiness cannot be verified independently.
- **CAM-24:** an operator-placed empty office chair, ~1–2 m away (`object_test.json`: "supplied_by": "operator", "bbox": null). The session assistant checked the saved reference frame.
- **CAM-26:** "small quadcopter, powered off, battery disconnected (operator-stated)". There is no ground-truth box and no image.

## 5. Metrics and why

Frames with person boxes and alerts the rule would raise (false alarms, CAM-25). Per-class frame frequency and score range (CAM-24/26). Inference time and capture→result latency.

## 6. Results

| | CAM-25 empty room | CAM-24 chair | CAM-26 drone |
|---|---|---|---|
| Frames | 96 (4.76 fps) | 101 (5.01 fps) | 100 (4.98 fps) |
| Frames with a person box | **0/96** (all four families: 0) | **0/101** at ≥ 0.5 | **100/100** (score 0.9704–0.9996) |
| Alerts the real rule would raise | **0** | n/a (objects never alert) | n/a |
| Images stored | 0 (by design) | 1 reference frame + annotated copy (no person box) | **0** (withheld: person boxes present) |
| Target class | — | **chair 101/101**, 0.9915–0.9965 (median 0.9949), box [600, 138, 375, 581] | **no drone class**; recognition 0/100 |
| Other labels seen | — | surfboard 101/101 (0.969–0.993), bench 78, tv 78, dining table 66, couch 20 (all 0.50–0.83) | couch 100, surfboard 100, cup 18, dining table 18, bottle 3, book 3 |
| Faster R-CNN per frame median / max | not instrumented | 190 / 243 ms | 192 / 220 ms |
| Capture → result median | — | 444 ms (p95 488, max 505) | 444 ms (p95 595, max 783) |
| Capture → Mac median / max | 307 / 421 ms | 189 / 275 ms | 189 / 481 ms |
| Pi temperature, EXT5V, throttled | 46.6–49.9 °C; 5.230–5.278 V; 0x0 | 46.6–49.4 °C; 5.251–5.273 V; 0x0 | 46.6–49.4 °C; 5.253–5.281 V; 0x0 |
| Verdict | **PASS** (no false alerts) | **MATCH**; chair never labelled person | **INCONCLUSIVE** |

**Statistical reading of CAM-25.** 0 false frames out of 96 gives a 95% upper confidence bound on the per-frame false-positive rate of about $3/n = 3.1\%$ (the "rule of three"). Frames 200 ms apart are correlated, so the effective sample is smaller still. One room, one viewpoint, no glass in the field of view.

**CAM-26 person boxes** (from box geometry, unverified): an upright box moving out of frame at 11–13 s and smaller drifting boxes at 4–6 s are probably real passers-by. A static wide box, about [430, 325, 845, 225], appears in every frame. Its shape matches the lying-person boxes in CAM-28, so a person lying or sitting low is plausible, but that is **UNVERIFIED**. If nobody was there, it would be a serious false positive above the trigger height.

## 7. Failures and issues

- **Unreliable non-person labels** in this room: "surfboard" at up to 0.99 for a paper floor mat and a round white object; "tv" for the chair's mesh back; and false furniture labels. This matters for `camera_mapping`, which uses obstacle classes ([06 Obstacle mapping](../../06_OBSTACLE_MAPPING.md)).
- **CAM-26** could not be evaluated: the background had people in it, so the image was withheld and the drone's position is unknown.
- The six drone reference photos mentioned by the operator never reached the session.

## 8. Evidence files (private, `$TEAM15_EVIDENCE/camera_live_test/`)

| File | SHA-256 |
|---|---|
| `$TEAM15_EVIDENCE/camera_live_test/empty-20261108T022809/D1-b1794122894-empty_summary.json` | `92ff7ad20139d0d1ae0d58f14772092b8a850a2e98b549a89b332efee69108ee` |
| `$TEAM15_EVIDENCE/camera_live_test/empty-20261108T022809/run_report.json` | `0041a841a2dd863d00b0140e7ffc92b3f875f8a2d298dc3b5c93677daab586fd` |
| `$TEAM15_EVIDENCE/camera_live_test/object-20261108T022506/run_report.json` | `8833f919fca8de6caa76b496a6be3a5ad4ff04a086247150e39c54c2b06d0bbf` |
| `$TEAM15_EVIDENCE/camera_live_test/object-20261108T022506/object_test.json` | `47fad6ecd40cdce0aa3c3a1d0bcbaf1edc837be0eb090b7aa624f89a9a7ab7d4` |
| `$TEAM15_EVIDENCE/camera_live_test/object-20261108T024058/run_report.json` | `cdcd8d113f40a47656370032b8488f2e92999556a20f1e4f8984e2f057132389` |
| `$TEAM15_EVIDENCE/camera_live_test/object-20261108T024058/object_test.json` | `814937e6edb2d4fd3c414b5a7a56f3dafe77dce408461cc62ddb85dc8b80098c` |

## 9. Limitations and confounders

The object runner is not the person pipeline: it uses threshold 0.5, all classes, no HOG and no gate. The empty-scene result rests on the operator's word. There is one sample of 20 s per scene, and the chair and empty scenes used the same viewpoint. These runners are on an unmerged branch.

## 10. Reproducibility

With merged code, CAM-25 can be approximated by running `perception.live_camera --source pi --min-box-frac 1.01 …` on an empty scene and replaying the 0.15 rule over the frame log (snippet in [04 §16](../../04_CAMERA_PERCEPTION.md#16-how-to-reproduce)). The object runner exists only on the unmerged branch.

## 11. What this proves / does not prove

- **Proves:** in this room and view, with no glass, the person pipeline raised no false alerts in 20 s. The chair was not confused with a person. The model cannot recognise drones.
- **Does not prove:** a field false-alarm rate, robustness to reflections (CAM-12 showed the opposite near glass), or the reliability of any non-person class.

## 12. Next time

Run a longer empty scene (≥ 5 min, several viewpoints, including one with glass). Store downscaled context frames under explicit no-people consent to verify emptiness. For drones, test an open-vocabulary detector offline on person-free frames, as a separate family that never feeds the person trigger.
