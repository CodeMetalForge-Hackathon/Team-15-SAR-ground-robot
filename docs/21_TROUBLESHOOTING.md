# 21 · Troubleshooting

This is a symptom → cause → fix guide for the Team-15 stack. Every entry comes from something that actually happened (a CI failure, a PR review finding, a fix commit, a measured run, or an engineering session log) or from an error message in the code at `d1b607a`. The evidence column says which. Several "symptoms" are the system working as designed: an honest UNKNOWN is not a bug, and those entries say so.

**Status:** Implemented (a reference guide). Hardware-specific entries carry the evidence label of the run they come from.

**Related:** [20 Deployment and runbook](20_DEPLOYMENT_AND_RUNBOOK.md) · [19 Testing](19_TESTING_AND_BENCHMARKS.md) · [22 Experiments and failures](22_EXPERIMENTS_AND_FAILURES.md) · [17 Safety architecture](17_SAFETY_ARCHITECTURE.md) · [CI-001](experiments/reports/CI-001-ci-regression-history.md)

---

## How to diagnose quickly

1. Note which **badge** the dashboard shows (LIVE-HW, RECORDED, SIMULATED, STALE, DISCONNECTED). It tells you which source you are looking at.
2. `curl -s localhost:8000/api/perception/health` shows camera status, frames received, map age, calibration and producer conflicts.
3. Read the run's logs. The demo script writes `dashboard.log`, `camera.log`, `qwen.log` and `perception.jsonl` under `~/Team15_evidence/camera_mapping/<timestamp>/`.
4. Check exit codes. `perception.live_camera`: 0 sighting, 1 bad sector or evidence dir, 2 no person, 3 camera unavailable. `camera_mapping.live`: 3 camera lost, 4 producer conflict. `orientation_check`: 0 ok, 2 exposure not ok, 3 camera unavailable. `qwen_launcher`: 2 SQLite not serialized.

## 1. Setup, dependencies and CI

| Symptom | Cause | Fix | Evidence |
|---|---|---|---|
| `AttributeError: module 'cv2' has no attribute 'HOGDescriptor'` in `perception/live_camera.py` | unpinned install pulled `opencv-python-headless 5.0.0.93`; OpenCV 5 moved HOGDescriptor out of the main package | `pip install -r requirements.txt` (pins `4.13.0.92`); in your own environments keep `opencv-python-headless>=4.8,<5` | CI runs 42403983799 and 42404031282; fix `a36a658` |
| `test_no_photos_tracked_in_git` fails | an image file (`.jpg/.jpeg/.png/.heic/.mp4/.mov`) is tracked | remove it from Git and keep evidence under `~/Team15_evidence/`. Only genuine UI assets may be exempted, by exact path in `VENDORED_ICONS` | CI run 42478121738 (Leaflet icons, PR #17); fix `159c678`. PR #6's 5 browser screenshots would fail the same way (PR #6 review comment) |
| 8 tests "skipped" in CI or on a clean checkout | private SIMULATED fixtures, cached torch weights or recorded Pi frames are absent | expected. To run them, install torch, cache the weights, and set `TEAM15_ROBOT_FIXTURES` | [19 §3.2](19_TESTING_AND_BENCHMARKS.md#32-why-ci-skips-8-tests-that-pass-locally) |
| Two workflows both called "ci" in GitHub's UI | `perception.yml` was first committed with `name: ci` | renamed to `perception` | PR #10 (`edb6756`) |
| add/add merge conflict on `.github/workflows/ci.yml` | two branches each created `ci.yml` | the perception workflow was moved to `perception.yml` before merging | `8f351fe` |
| Merge conflicts in `.gitignore` and `README.md` | both sides added the same files (PR #6 vs `main` / PR #13) | keep both sets of lines; put PR #6's BLE README under `docs/ble-id/` and link it | PR #13 description; PR #6 review comment (still **open**) |
| `__pycache__/` shows up in `git status` or a commit | running without `-B` | use `python3 -B …`; `__pycache__` is ignored | `9efbed7` (accidentally committed, then removed) |
| `team15_starter/tests/test_link.py` "collects 0 tests" under pytest | it is a script, not a pytest module | run `cd team15_starter && python3 tests/test_link.py` | local run, 8 Nov (30 checks pass) |
| Red CI on a PR from a branch that forked long ago | CI tests the PR merged with `main`, so it sees `main`'s tests | merge `main` into the branch and re-run | `95b6f67` (PR #17 forked from the initial commit) |

## 2. Camera and the Pi link

| Symptom | Cause | Fix | Evidence |
|---|---|---|---|
| `Camera unavailable: could not obtain real frames …` (Mac camera) | macOS camera permission (TCC) denied for the terminal, or another app holds the camera | System Settings → Privacy & Security → Camera → allow the terminal, then restart the terminal. No frame is ever faked | `CAMERA_HELP` in `perception/live_camera.py` |
| `camera N opened but returned only empty/black frames` | same as above, or a privacy shutter | same | `perception/live_camera.py` |
| `Pi camera unavailable: … Check TEAM15_PI_HOST/--pi-host, the SSH key, and that the host key is already trusted` | SSH runs with `BatchMode=yes`, so an unknown host key or a missing key fails immediately | `ssh "$TEAM15_PI_HOST"` once by hand to trust the key; check the `TEAM15_PI_*` variables | `perception/live_camera.py`, `perception/pi_source.py` `build_ssh_command` |
| `no Pi host: pass --pi-host or set TEAM15_PI_HOST` | no host given | set the variable or pass the flag | `perception/pi_source.py` |
| `no frame from the Pi within Ns (ssh stderr: …)` | the sender did not start: the camera is busy, picamera2 is missing, or the network is slow | read the stderr tail; check that nothing holds the camera; raise `--pi-startup-timeout-s` | `PiSourceError` in `perception/pi_source.py` |
| `T15ERR no camera detected by libcamera` (sender exit 4) | the camera ribbon is unseated, or the wrong port is used | power down and reseat; check `rpicam-hello --list-cameras` on the Pi | `SENDER_SCRIPT` in `perception/pi_source.py` |
| Demo preflight: `Pi camera already in use` | another `picamera2`, `rpicam-` or `python3 -u -` process on the Pi | stop that session. The script deliberately kills nothing | `scripts/camera_demo.sh` |
| `cannot ssh to $PI_HOST. Fix Tailscale/SSH, or run: … --replay` | the Pi is offline or unreachable | use `scripts/camera_demo.sh --replay` (RECORDED) and say so; fix the network separately | `scripts/camera_demo.sh`. The Pi dropped off Tailscale several times on 7–8 Nov (for example at 06:55 ET on 8 Nov, EVALUATION §3b) and was unreachable during this audit. **Root cause UNKNOWN**: suspects in [LIDAR_C1_HARDWARE_CHECKLIST](lidar/LIDAR_C1_HARDWARE_CHECKLIST.md) include CPU load and USB back-feed. The journal did not persist across reboots |
| Stream works but is slow or bursty over Tailscale | the guest Wi-Fi blocked direct connections, so Tailscale relayed (about 7 Mbit/s; the stream uses about 1.4 Mbit/s) | expected. The source keeps only the newest frame, so no backlog builds; after 3 failed reconnects it exits with code 3 | PR #5 description |
| First seconds of a live run at about 0.7 fps | cold Faster R-CNN on MPS: the first call took 3.7 s | already fixed: detectors warm up on one discarded frame | `ae8b088` (0.68 → 4.36 fps), PR #3 |
| Detector median about 246 ms instead of about 186 ms | the GPU was shared with another process (a second runner, depth, Qwen) | stop other GPU users; expect slower numbers with `--depth` and Qwen together | EVALUATION §3, §3b |
| Image upside down | wrong `--pi-rotation` for the mount | default 180 was verified on the robot mount; re-run `python3 -m perception.orientation_check …` after any remount | PR #3 comment (orientation check, 7 Nov). The older bench sighting `D1-b1794091323-000001` is upside down for this reason and was kept unchanged as history |
| False "person" on an empty scene | window glass reflections, or bystanders at the frame edge; the detector boxed reflections at up to 0.99 | aim away from glass; keep `--min-box-frac 0.15`; never auto-confirm | PR #3 bench runs `empty60d` (FAIL) and `empty60*`; the 60 s empty-scene test **never passed** |
| HOG, face or upper-body boxes appear but no sighting | by default only `PERSON_DETECTOR` triggers | `--trigger any` if you really want them (not recommended: the face cascade fired on a blank wall in 80 of 97 frames) | PR #3 |
| `evidence dir … is inside a Git work tree` (exit 1) | `--out-dir` points into a repo | use a folder outside Git (default `~/Team15_evidence/camera`) | `perception/sightings.py` |

## 3. Dashboard

| Symptom | Cause | Fix | Evidence |
|---|---|---|---|
| `port 8000 busy (another dashboard?)` | a dashboard is already running | `PORT=8001 scripts/camera_demo.sh`, or stop the old one (see [20 §9](20_DEPLOYMENT_AND_RUNBOOK.md#9-safe-shutdown-and-cleanup)) | `scripts/camera_demo.sh` |
| `POST /observations` returns **422** | the sighting breaks the ingest contract: for example, a Pi sighting whose `obs_time` is not the Pi capture time, a wrong transport or clock, coordinates on a `SECTOR_ONLY` sighting, or a bad `obs_id` | fix the producer. The rules are in [PI_CAMERA_CONTRACT §3](../contracts/PI_CAMERA_CONTRACT.md); the exact message comes from `InvalidObservation` in `core/ingest.py` | e2e test `test_pi_camera_integration.py` (11 rule-breaking sightings rejected) |
| A repeated sighting does not create a new person or alert | dedup by `obs_id` and `evidence.frame_sha256`, one track per sector | expected | PR #5 |
| Sighting stays "unconfirmed" | only `POST /operator_decision` with an operator name changes it | the operator presses Confirm or Reject | PR #5 |
| Panel D shows a **producer conflict**; runner logs `another camera runner is already feeding this dashboard` and exits with **4** | two `camera_mapping.live` runners posting to one dashboard (on 8 Nov a stray `--source replay` runner ran alongside the live Pi runner) | stop the extra runner (`pkill -f "camera_mapping.live --source replay"`); the lock frees after 4 s of silence | EVALUATION §3b; fix `73539a7` (HTTP 409) |
| Ctrl-C on the demo script did not stop it; the camera runner kept restarting | the INT trap cleaned up but did not exit, so the restart loop continued | fixed: the trap now runs `cleanup; exit 130` (SIGTERM verified to leave 0 processes; interactive Ctrl-C unverified, so check with `pgrep -fl camera_mapping.live`) | `73539a7` |
| Panel status **STALE**, corridor UNKNOWN, map empty | no perception state for more than 2 s (runner stopped, Pi dropped) | expected safe behaviour. The script restarts the runner up to `MAX_RESTARTS` (5) times | `stale_view` in `camera_mapping/pipeline.py`; EVALUATION (STALE → UNKNOWN within 2 s) |
| Forward obstacle range card says **DISCONNECTED** | no `--range-url`, `--robot-url` or fixture configured, or a wrong schema, non-200 or 401 answer | expected. For a demo use `--range-fixture …` (always badged SIMULATED) | `dashboard/range_source.py`, PR #5 |
| Range URL points at `:8765` on the Mac and shows nonsense or DISCONNECTED | on the bench Mac, `:8765` is an unrelated app | tunnel the Pi's service to 18765: `ssh -L 18765:127.0.0.1:8765 …`, then `--range-url http://127.0.0.1:18765/range` | `dashboard/serve.py` help text |
| Range card shows SIMULATED although the fixture claims HARDWARE | fixture mode is always SIMULATED; HARDWARE needs `source_mode=="LIVE-HW"`, `driver=="gpiod"` and a non-blank `wiring_verified_by` | expected (spoof resistance) | `7624788`; 31 spoof tests (PR #5) |
| `clock_skew` flag on a sighting | the capture time is more than 2 s in the dashboard's future | check NTP on the Pi and the Mac; the flag is shown, never hidden | `core/ingest.py`, PR #5 |
| Sightings lost after restarting the dashboard | `MissionStore` is in memory | the camera's `sightings.jsonl` keeps them; reload with `--observation` | PR #5 known limits |

## 4. Camera mapping and distances

| Symptom | Cause | Fix | Evidence |
|---|---|---|---|
| Corridor is **always UNKNOWN**, no FREE cells, route `NO_SUPPORTED_ROUTE` | the camera mount height and pitch are **unmeasured** (`mount.measured: false` in `camera_mapping/configs/imx708_robot.json`). By design, the ground-plane method is then off and nothing can be CLEAR | measure the mount: `python3 -m camera_mapping.calibrate set-mount --height-m H --pitch-deg P --by NAME`, then the tape procedure in [CALIBRATION](camera_mapping/CALIBRATION.md) | every frame of every demo-script run on 8 Nov was UNKNOWN (6 runs; see [26](26_HACKATHON_DEMO_GUIDE.md)) |
| Person distance UNKNOWN (`NO_METHOD_APPLICABLE`) | the box is cut by the frame top or bottom (person close to the camera), so known-height is refused, and ground-plane is off | step back so the whole person is in frame; measure the mount | EVALUATION §3b, §5 |
| Implausible far distance (for example about 7.9 m) for a nearby object cut by the image side | known-height applied to an edge-cut box | fixed: known-height refuses any edge-cut box (regression test) | EVALUATION §3b; `73539a7` |
| "chair ~1.0 m ±0.4" never appears as in JUDGE_DEMO step 2 | the same: no mount, and the known-height prior alone often refuses | treat JUDGE_DEMO steps 2–4 as describing the **calibrated** pipeline; see [26 §3](26_HACKATHON_DEMO_GUIDE.md) | config at `d1b607a` |
| Mono-depth distances shown but not used | `METRIC_UNVALIDATED`: never fused until it passes the tape gate | expected | EVALUATION §4 |
| Boxes, cables or glass not detected | COCO has no "box" class, and the camera cannot see untrained objects, glass or drop-offs | expected limitation; FREE means only "nothing detected" | [camera_mapping/README](../camera_mapping/README.md) |

## 5. Qwen advisor

| Symptom | Cause | Fix | Evidence |
|---|---|---|---|
| Every C_QWEN_RAG request returns HTTP 500, `sqlite3.ProgrammingError` | `rescue_qwen.service` builds its in-memory SQLite FTS index in the main thread, while FastAPI runs sync endpoints in worker threads | start the service through `python3 -B -m camera_mapping.qwen_launcher` (opens SQLite with `check_same_thread=False`). The proper fix is on a Qwen-workspace branch, **not merged** | `camera_mapping/qwen_launcher.py` docstring (seen 8 Nov); PR #16 |
| `refusing: sqlite3 is not built serialized (threadsafety != 3)` (exit 2) | this Python's SQLite is not thread-safe, so the workaround would be unsafe | use a Python whose `sqlite3.threadsafety == 3` (the bench Mac's does) | `camera_mapping/qwen_launcher.py` |
| `WARN Ollama not answering: advisory will be DETERMINISTIC only` | Ollama is not running on `:11434` | `ollama serve`; the deterministic summary is still shown and labelled | `scripts/camera_demo.sh` |
| `port 8090 busy with something else: advisory DETERMINISTIC only` | some other service on 8090 does not answer `/health` with `"advisory_only":true` | free the port or use `QWEN_PORT=…` | `scripts/camera_demo.sh` |
| Advisory appears 4–6 s after the scene changes | local 2B model latency (4.0–5.9 s measured) | expected; the advisory is asynchronous (default every 10 s, `--advise-every-s`) and never blocks frames | EVALUATION §6 |
| First advisory very slow | cold model load | the script warms the model with one `num_predict: 1` request | `scripts/camera_demo.sh` |
| Someone expects the fine-tuned LoRA in the demo | Ollama (0.40.2 in MODEL.md) does not load LoRA adapters, and `rescue_qwen.service` has only Ollama/OpenAI backends | expected: the demo is **base Qwen3.5-2B + RAG + guard**. Load the adapter with PEFT as in `README.md` for offline evaluation | [qwen/MODEL.md](qwen/MODEL.md), EVALUATION §6 |
| Qwen output mentioning motion is discarded | the guard rejects anything more permissive than the deterministic policy | expected | [QWEN_ADVISORY_CONTRACT](qwen/QWEN_ADVISORY_CONTRACT.md) |

## 6. Range sensors, rover and bridge

| Symptom | Cause | Fix | Evidence |
|---|---|---|---|
| Grove `diagnose` on the Pi: **0/50 VALID, 50/50 NO_ECHO, 0 echo edges**, verdict `NO_RESPONSE_EVER`, health FAULT | **UNKNOWN**. Candidates include: sensor unplugged or unpowered, wrong GPIO, a level-shifting or pull-down problem, or a board revision mismatch | follow [ranging/WIRING.md](../ranging/WIRING.md): measure VCC (3.20–3.45 V) and SIG idle (≤ 1.2 V) with power off/on as documented, confirm the GPIO5 line, and get the two-person sign-off. Motion stays STOP whatever the cause | REAL HARDWARE, two runs on 8 Nov about 10:43 and 10:50 UTC (session console log); [14](14_GROVE_ULTRASONIC.md) |
| `ranging check-config --hardware` or `serve --hardware` refuses | the config is not fully verified (checklist, named wirer **and** independent verifier, SIG idle ≤ 1.2 V) | expected gate; do the checklist in [ranging/HARDWARE_VALIDATION.md](../ranging/HARDWARE_VALIDATION.md) | CI step in `ranging.yml` |
| `lidar check-config --hardware` exits 2; `scan-once` exits 3 | unverified config, or no `--approved-by` | expected gate; follow [LIDAR_C1_STATIONARY_SCAN_PROCEDURE](lidar/LIDAR_C1_STATIONARY_SCAN_PROCEDURE.md) | CI steps in `lidar.yml`; local run 8 Nov |
| LiDAR range shows on the dashboard card but the rover treats it as UNKNOWN | the rover does not accept source `rplidar-c1` yet, and the compat snapshot always sets `forward_motion_allowed: false` | intended; LiDAR-driven motion is blocked pending review | PR #11 |
| Simulated rover latches `SENSOR_STALE` after a missed ping | range freshness for motion is 0.20 s; one or two missed pings at 0.1 s exceed it | keep the ping interval ≤ 0.1 s; `SENSOR_STALE` needs an operator reset (nothing restarts by itself) | PR #7 comment, [ROVER_NAV_CONTRACT §2](../contracts/ROVER_NAV_CONTRACT.md) |
| `tick()` raised on every cycle after the controller link died | the latched branch called `_hard_zero()`, which re-raised the driver error | fixed: zero is re-asserted without raising; `DRIVER_STOP_FAILED` is recorded and `DRIVER_FAULT` stays latched | `14fde0d`, found by the USB-bridge end-to-end test; regression `test_dead_link_never_crashes_tick_and_stays_latched` |
| `RoverCAdapter` refuses to construct | `HardwareVerification` is incomplete (wiring, link, firmware, power, measured link-loss stop, wheel mapping) | expected. [rover/BENCH_RUNBOOK](rover/BENCH_RUNBOOK.md) gates 5→6 | `rover/hardware.py` |
| No StickC or RoverC visible from the Pi | USB showed only root hubs, no serial devices, I²C only the camera and HDMI DDC, header `i2c-1` disabled | identify the controller and cable; use only a `/dev/serial/by-id/…` path (`open_serial` refuses anything else) | read-only inspection (PR #8, [rover/HARDWARE_READINESS](rover/HARDWARE_READINESS.md)) |
| `use the stable /dev/serial/by-id/... path of the verified StickC` | `open_serial` was given `/dev/ttyUSB0` or similar | pass the by-id path | `rover/bridge.py` |
| Firmware will not build | the sketch has **never been compiled** (no `arduino-cli` on the bench); the ESP32 core version and the `Wire` vs M5Unified `Ex_I2C` question are open | compile with the documented core first, dry-run with the RoverC **off**, and get separate approval before flashing | PR #15 "Unverified / remaining" |
| PR #8's merge commit message names the wrong ranging commit | the `82f5079` merge message says `19c43d8` | historical only; the tree is correct (`a980eed`) | PR #8 description |
