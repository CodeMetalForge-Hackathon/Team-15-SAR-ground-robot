# Camera performance results

All numbers are **LIVE HARDWARE**, computed from the run files under `~/Team15_evidence/camera_live_test/`:

- `*_summary.json` and `*_frames.jsonl` from the person pipeline,
- `object_frames.jsonl` from the object runner,
- `pi_health.jsonl` and `run_report.json`, which hold Pi health samples taken over SSH every 2 s.

Each run was about 20 s, after a 10 s countdown with the camera off.

## Setup

| | |
|---|---|
| **Pi stream** | 1280×720, 5 fps requested, JPEG quality 80, sent over SSH |
| **Transport** | Tailscale via the DERP relay "nyc" (not a direct path), with the Mac on the venue guest Wi-Fi |
| **Detector** | Faster R-CNN ResNet-50 FPN v2 (COCO) on the Mac's MPS, with warm-up |
| **Person pipeline** | also runs OpenCV HOG and the Haar cascades on every frame |

## Throughput and latency

| Metric | Person present | Chair (object) | Genuinely empty |
|---|---|---|---|
| Frames processed | 96 in 20.2 s | 101 | 96 in 20.2 s |
| **Processed FPS** | **4.75** | **5.01** | **4.76** |
| Pi frames received / delivered / dropped as stale | 105 / 97 / 7 | 104 / 102 / 1 | 104 / 97 / 6 |
| Malformed frames / decode failures / reconnects | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 |
| **Capture → Mac (transport)**, median / p95 / max | 290 / 379 / 386 ms | 189 / – / 275 ms | 307 / 382 / 421 ms |
| Frame spacing at the Mac, median / max | 208 / 262 ms | – | 208 / 255 ms |
| **Faster R-CNN inference** (MPS), median / p95 / max | not instrumented | **190 / 216 / 243 ms** | not instrumented |
| **Capture → detection result**, median / p95 / max | not instrumented | **444 / 488 / 505 ms** | not instrumented |
| Model load / warm-up | warm-up 0.39 s | load 0.45 s | warm-up 0.38 s |

**How to read these numbers:**

- **The stream sets the frame rate.** The Pi sends 5 fps. The object runner, which runs Faster R-CNN only, kept up fully at 5.01 fps. The person pipeline, which adds HOG and the Haar cascades, processed 4.75–4.76 fps and dropped 6–7 stale frames. So its total time per frame is just under the 200 ms frame period. Its inference time is not logged per frame.
- **Transport delay varied between runs.** The median ranged from 189 to 307 ms over the Tailscale relay, without any change to the setup. A direct Tailscale path would likely cut this, but that is **NOT TESTED**.
- **End-to-end to the dashboard:** a live push during a run is **NOT TESTED**. The only dashboard figure, "capture→dashboard 504 s" for `D1-b1794121685-000001`, measures when the evidence was imported after the run, not pipeline latency. Expected live latency would be about capture → result (≈0.45 s) plus the gate's 3-frame confirmation (≈0.4 s at 5 fps) plus a local HTTP POST. That is an estimate, not a measurement.

## Tests 4–6: drone, seated person, lying person

| Metric | Drone (object) | Seated person | Lying person |
|---|---|---|---|
| Frames processed / FPS | 100 / **4.98** | 94 / **4.68** | 94 / **4.69** |
| Pi frames received / delivered / dropped as stale | 104 / 101 / 2 | 103 / 95 / 7 | 104 / 95 / 8 |
| Capture → Mac, median / p95 / max | 189 / – / 481 ms | 296 / 385 / 435 ms | 293 / 375 / 387 ms |
| Faster R-CNN per frame, median / max | 192 / 220 ms | **196 / 239 ms** | **195 / 241 ms** |
| All detectors per frame, median / max | – | 209 / 254 ms | 207 / 252 ms |
| Capture → detection result, median / p95 / max | 444 / 595 / 783 ms | – | – |
| First person frame → alert (3-frame rule) | n/a (objects never alert) | 0.6 s | 0.4 s |
| **Live capture → dashboard** | n/a | **499 ms** | **593 ms** |
| Pi temperature | 46.6–49.4 °C | 47.2–49.9 °C | 46.6–49.4 °C |
| EXT5V | 5.253–5.281 V | 5.245–5.285 V | 5.187–5.268 V |
| `get_throttled` | `0x0` throughout | `0x0` throughout | `0x0` throughout |
| Memory used, max | 891 MB | 877 MB | 902 MB |
| SSH health session, median / max | 0.46 / 0.90 s | 0.38 / 0.45 s | 0.38 / 0.54 s |

- **Live capture → dashboard** is the dashboard's own receive time minus the Pi capture time of the sighting frame, recorded at live delivery. Adding the 3-frame rule (0.4–0.6 s) gives about 1.0–1.2 s from a person appearing to the alert on the dashboard.
- **Supply voltage:** the lying run had the lowest reading so far, 5.187 V. That is still well above the Pi's under-voltage level, and no throttling was reported.
- **SSH round trip** before Test 6 was 0.35–0.40 s, measured over 3 timed connections.

## Pi health

| Metric | Person present | Chair | Genuinely empty |
|---|---|---|---|
| Samples (failed) | 11 (0) | 11 (0) | 11 (0) |
| CPU temperature | 47.7–50.5 °C | 46.6–49.4 °C | 46.6–49.9 °C |
| EXT5V | 5.241–5.272 V | 5.251–5.273 V | 5.230–5.278 V |
| `get_throttled` | `0x0` throughout | `0x0` throughout | `0x0` throughout |
| Memory used, max | 883 MB of 16 GB | 885 MB | 896 MB |
| Health stop triggered | no | no | no |
| Network dropouts (SSH reconnects / failed samples) | 0 / 0 | 0 / 0 | 0 / 0 |

- **At idle,** before and after the runs: 46.6–49.4 °C, EXT5V 5.26–5.27 V, `throttled=0x0`, about 750–800 MB used.
- **Under load,** with the camera streaming, the Pi rose by at most about 3 °C. The supply did not sag below 5.23 V.
- **Endurance on the portable supply** beyond these 20 s runs is **NOT TESTED**.
- **Processes:** no other camera, LiDAR or LLM process was running during the tests. `hailort_service` was idle, and Hailo-8 was not used.

## Not measured

- *(Now measured:* Faster R-CNN time inside the person pipeline (`detect_s`, since commit 4035df1) and live capture → dashboard latency. See Tests 4–6.*)*
- CPU load on the Pi.
- Wi-Fi signal strength. A Tailscale-specific round trip was not measured; only SSH session time was.
- Behaviour at higher resolution or frame rate, or with Hailo-8 on the Pi.
