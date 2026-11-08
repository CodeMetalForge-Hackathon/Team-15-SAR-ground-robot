# Video index

| Video | What it is | Evidence type | Length / size | Where |
|---|---|---|---|---|
| **Team15_Dual_Robot_Rescue_Demo.mp4** | 3D dual-robot rescue digital twin, scenario B (dynamic debris) | **SIMULATION**: a real browser session rendering the real simulation. **No physical robot moved.** | 74.5 s, 18.5 MB, 1920 × 1080, H.264, 30 fps | [`videos/Team15_Dual_Robot_Rescue_Demo.mp4`](videos/Team15_Dual_Robot_Rescue_Demo.mp4) |
| Qwen + LoRA real-camera demo | Recorded separately by the team | Real camera + model | — | **Not in this repository.** It is a different recording; do not confuse the two. |

SHA-256 of the MP4: `f9f446ea8dfbc6bae083b62933306ce0ba99e2c3b48ca613b549090247d052da`

## How the simulation video was made

* A real Google Chrome session ran headless with GPU rendering (ANGLE Metal, Apple M4 Pro) at
  1920 × 1080 against the dashboard's `/rescue` page. Chrome DevTools' screencast captured 3857
  compositor frames over 74.3 s (about 52 fps).
  [`assemble_video.py`](assemble_video.py) turned them into a constant-30 fps MP4 using each frame's
  real timestamp, so the video plays at the speed the browser rendered.
* [`record_demo.py`](record_demo.py) changed only the simulation **speed**, the **camera** and an
  on-screen **caption**. Each caption waits for the real coordinator event it describes. The drone, the
  rover, the debris event, the stop, the replan and the Qwen report all come from the running
  simulation and the live Qwen service. Capture log: [`evidence/video_capture_log.json`](evidence/video_capture_log.json).
* The recording server ran **without** a recorded-evidence folder, so **no real camera image** appears
  in the video.
* Every frame carries the label **SIMULATION — NO PHYSICAL ROBOT MOVEMENT**.

## Chapters (video time)

| Time | Chapter | What you see (all simulated) |
|---|---|---|
| 0:00 | Intro | Collapsed-building site (48 m, synthetic). Corridors start UNKNOWN (hatched amber). |
| 0:04 | 1 · Aerial search | AIR-1 runs PR #17's MCTS belief search. The cyan square is its camera footprint. |
| 0:09 | 2 · Survivor candidate | The survivor is reported only once it is inside the footprint. Three-look confirm hover. |
| 0:10 | 3 · Shared map + route check | The coordinator has the drone observe the rover's route first. Drone-seen debris on M1-N1 is avoided. |
| 0:14 | 4 · Handoff | GND-1 drives on its real Navigator + safety supervisor, over corridors observed CLEAR only. |
| 0:21 | 5 · Dynamic event | The simulator drops debris on the planned corridor. Agents are not told. Grey = ground truth, shown to the viewer only. |
| 0:30 | 6 · Obstacle | Ultrasonic STOP → VERIFY (3 readings) → MARK BLOCKED → SCAN. The drone re-checks the block. |
| 0:40 | 7 · Cooperation | No KNOWN-clear detour (stale observations): the rover holds and requests sensing, and the drone observes the detour. |
| 0:45 | 8 · Replan | The Navigator replans with Dijkstra over corridors now observed CLEAR. |
| 0:49 | 9 · Rescue approach | The rover follows the detour. |
| 0:59 | 10 · Safety decision | At the standoff the rover's simulated camera sees the survivor. The rover stops, and the sighting stays UNCONFIRMED until a human reviews it. |
| 1:03 | 11 · Rescue intelligence | The Qwen3.5-2B + RAG report (status `QWEN_GUARDED (RAG)`, authority NONE) appears beside the deterministic summary. |
| 1:09 | Summary card | Test and benchmark counts. SIMULATION, no real drone flight. |

What this run shows about Qwen: its free-text explanation was cautious and partly off ("no sighting
was provided"). The simulation passes the drone's sighting as timestamped notes, not as the service's
structured `sighting` field. The deterministic summary next to it is the reliable record.

Reproduce: see [DEMO.md](DEMO.md#re-record-the-video).
