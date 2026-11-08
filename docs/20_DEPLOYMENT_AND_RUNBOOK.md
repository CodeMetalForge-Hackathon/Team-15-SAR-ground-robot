# 20 · Deployment and runbook

This runbook lists the commands that start, check and stop every part of the Team-15 stack: Mac setup, the dashboard, the live camera paths, camera mapping with the Qwen advisor, the recorded-frame fallback, the simulators, the tests, and a clean shutdown. Every flag shown was checked against the module's `--help` output (argparse) at `d1b607a` on 8 Nov 2026. Hosts, users and keys appear only as environment variables. Hardware steps are listed only as pointers to their gated procedures. **Nothing in this document moves the robot.**

**Status:** Implemented. The commands were verified against argparse. The live Pi commands were last run successfully on 8 Nov 2026 (REAL HARDWARE). The Pi was unreachable during this audit, so the Pi steps were not re-run.

**Related:** [01 Architecture](01_SYSTEM_ARCHITECTURE.md) · [02 Raspberry Pi setup](02_RASPBERRY_PI_SETUP.md) · [03 Mac inference](03_MAC_AI_INFERENCE.md) · [19 Testing](19_TESTING_AND_BENCHMARKS.md) · [21 Troubleshooting](21_TROUBLESHOOTING.md) · [26 Demo guide](26_HACKATHON_DEMO_GUIDE.md) · [docs/camera_mapping/DEMO.md](camera_mapping/DEMO.md) · [docs/lidar/LIDAR_C1_DEMO_RUNBOOK.md](lidar/LIDAR_C1_DEMO_RUNBOOK.md) · [docs/rover/BENCH_RUNBOOK.md](rover/BENCH_RUNBOOK.md)

---

## 0. Conventions

```bash
export TEAM15_PI_HOST=...      # Pi SSH host or Tailscale name (read by perception/pi_source.py)
export TEAM15_PI_USER=...      # SSH user
export TEAM15_PI_KEY=...       # path to the SSH private key
export PI_HOST="$TEAM15_PI_HOST"   # scripts/camera_demo.sh reads PI_HOST (its default is a hostname alias)
export QWEN_WORKSPACE=...      # private Qwen workspace (contains rescue_qwen/); not in this repo
export TEAM15_EVIDENCE=~/Team15_evidence   # where the camera tools write evidence (outside Git)
```

All commands run from the repository root unless stated otherwise. `-B` (no `.pyc` files) is used throughout the repo's own instructions, so stray `__pycache__` does not get committed (it was once: `9efbed7`).

## 1. Mac setup

### 1.1 Python environment

```bash
python3 --version                    # bench Mac: 3.13.5; CI: 3.11 (ci, lidar, ranging, qwen) and 3.13 (perception)
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt      # pinned: pytest 8.3.4, networkx 3.4.2, fastapi 0.115.6, starlette 0.41.3,
                                     # uvicorn 0.34.0, httpx 0.28.1, numpy 2.1.3, opencv-python-headless 4.13.0.92
```

**Do not unpin OpenCV.** An unpinned install resolved `opencv-python-headless 5.0.0.93`, which has no `cv2.HOGDescriptor`, and CI broke ([CI-001](experiments/reports/CI-001-ci-regression-history.md)).

### 1.2 Optional: detector and depth models

`requirements.txt` deliberately leaves out torch, because CI does not need it. The live detectors do:

```bash
pip install torch torchvision        # bench Mac ran torch 2.12.0 / torchvision 0.27.0 on MPS
python3 -c "import torch; print(torch.backends.mps.is_available())"
```

The first run downloads the Faster R-CNN weights (about 170 MB for R50-FPN-v2, per PR #3) into `~/.cache/torch`, outside Git. The optional mono-depth cross-check (`--depth`) also needs the Depth-Anything-V2 weights; see [05](05_DEPTH_AND_DISTANCE_ESTIMATION.md). `scripts/camera_demo.sh` refuses to start unless `import torch, torchvision, cv2, fastapi, uvicorn` succeeds.

### 1.3 Optional: local Qwen

The advisor needs **Ollama** serving `qwen3.5:2b-q4_K_M` on `127.0.0.1:11434`, plus the private Qwen workspace for `rescue_qwen.service` (RAG + guard). Model details are in [08](08_QWEN_MODEL.md) and [10](10_RAG_PIPELINE.md).

```bash
ollama serve &                                  # if not already running
curl -sf localhost:11434/api/version            # the demo script's own check
```

The fine-tuned LoRA adapter is **not** served by this path. Ollama does not load PEFT adapters ([docs/qwen/MODEL.md](qwen/MODEL.md)).

## 2. Raspberry Pi

Pi preparation is in [02 Raspberry Pi setup](02_RASPBERRY_PI_SETUP.md). The camera path installs **nothing** on the Pi: the Mac pipes the sender script over SSH. These are the only requirements:

- `picamera2` (and OpenCV) are present on the Pi;
- the SSH host key is already trusted (SSH runs with `BatchMode=yes`; an unknown host fails instead of prompting);
- nothing else holds the camera (`scripts/camera_demo.sh` checks for `picamera2`, `rpicam-` or `python3 -u -` processes and refuses, without killing anything).

Check the orientation after any remount (writes a report under `~/Team15_evidence/orientation_checks`):

```bash
python3 -m perception.orientation_check --pi-host "$TEAM15_PI_HOST" --pi-user "$TEAM15_PI_USER" --pi-key "$TEAM15_PI_KEY"
# exit 0 = exposure ok; 2 = exposure not ok; 3 = camera unavailable
```

## 3. Dashboard

`python3 -m dashboard.serve` flags: `--observation FILE` (repeatable), `--evidence-dir DIR` (repeatable), `--range-fixture FILE`, `--robot-fixture FILE`, `--range-url URL`, `--robot-url URL`, `--responder NODE` (default `A`), `--host` (default `127.0.0.1`), `--port` (default `8000`).

```bash
python3 -B -m dashboard.serve                                   # http://localhost:8000/
python3 -B -m dashboard.serve --port 8001                       # if 8000 is busy
python3 -B -m dashboard.serve --observation ~/Documents/Team-15-evidence/camera/<obs_id>.json   # preload history
```

- Photos are served only from `~/Team15_evidence/camera`, the folder of each `--observation`, and each `--evidence-dir`.
- With no range source configured, the "Forward obstacle range" card reads **DISCONNECTED**. That is correct behaviour.
- The range URL has **no default** on purpose: on the bench Mac, `:8765` belongs to an unrelated app. To view a live Pi range service, tunnel it first: `ssh -L 18765:127.0.0.1:8765 "$TEAM15_PI_HOST"`, then `--range-url http://127.0.0.1:18765/range`. That service has never produced a valid hardware reading ([14](14_GROVE_ULTRASONIC.md)).

Health check: `curl -s localhost:8000/api/perception/health`.

## 4. Live camera, person sightings (`perception/`)

`python3 -m perception.live_camera` needs `--sector` (alias `--declare-cell`), the operator-assigned sector A–Z. The evidence directory (`--out-dir`, default `~/Team15_evidence/camera`) must be outside any Git work tree, or the tool refuses (exit 1).

```bash
# Terminal 1
python3 -B -m dashboard.serve
# Terminal 2a: Pi camera -> Mac Faster R-CNN -> dashboard
python3 -B -m perception.live_camera --source pi --sector G --duration-s 1800 \
  | python3 -B -m core.camera_bridge --post http://localhost:8000/observations
# Terminal 2b (fallback): the Mac's own camera
python3 -B -m perception.live_camera --sector G --duration-s 1800 \
  | python3 -B -m core.camera_bridge --post http://localhost:8000/observations
```

| Flag | Default | Meaning |
|---|---|---|
| `--source {local,pi}` | `local` | local camera, or the Pi over SSH |
| `--pi-host/--pi-user/--pi-key` | `$TEAM15_PI_HOST/USER/KEY` | SSH target |
| `--pi-size`, `--pi-fps`, `--pi-quality` | `1280x720`, 5, 80 | stream settings |
| `--pi-rotation {0,90,180,270}` | 180 | verified upright on the robot mount on 7 Nov |
| `--pi-startup-timeout-s` | 30 | |
| `--start-delay-s` | 0 | ignore frames at first (lets the operator leave the view) |
| `--once` | off | stop after the first sighting |
| `--trigger {any,person}` | `person` | `any` lets HOG, upper-body and face hits trigger too |
| `--dnn-model {frcnn_mbv3_fpn,frcnn_r50_fpn_v2}` | `frcnn_r50_fpn_v2` | |
| `--no-dnn` | off | OpenCV detectors only (no torch needed) |
| `--person-thresh` | 0.6 | |
| `--min-box-frac` | 0.15 | drops short boxes (window reflections, from bench tuning) |
| `--confirm-frames`, `--rearm-s` | 3, 60 | one sighting per person |

Exit codes: **0** a sighting was emitted, **1** bad sector or evidence directory, **2** no person, **3** camera unavailable. `core.camera_bridge` flags: `--post URL` (default `http://localhost:8000/observations`), `--retry-s` (how long to retry one line while the dashboard is down).

## 5. Camera mapping demo (`camera_mapping/`), one command

`scripts/camera_demo.sh` starts the dashboard, the Qwen RAG advisor and the live Pi camera runner. It checks preconditions first and cleans up on Ctrl-C. Read it before running it; it is about 150 lines.

```bash
scripts/camera_demo.sh                 # live Pi camera (default)
scripts/camera_demo.sh --replay        # recorded Pi frames, labelled RECORDED (no Pi needed)
scripts/camera_demo.sh --no-qwen       # deterministic advisory only
scripts/camera_demo.sh --depth         # add the (unvalidated) mono-depth cross-check (--depth metric)
PORT=8001 scripts/camera_demo.sh       # other dashboard port
```

| Env var | Default | Used for |
|---|---|---|
| `PORT` | 8000 | dashboard |
| `QWEN_PORT` | 8090 | Qwen advisory service |
| `PI_HOST` | a host alias in the script | `ssh "$PI_HOST"` (no user or key flags: configure them in `~/.ssh/config`) |
| `QWEN_ROOT` | `~/Documents/Team-15-Qwen` | path to `$QWEN_WORKSPACE` |
| `REPLAY_GLOB` | `$HOME/Team15_evidence/camera_pi_validation/*.png` | frames for `--replay` |
| `MAX_RESTARTS` | 5 | camera-runner restarts before giving up |

What it does, in order:

1. **Preflight.**
   - The Python deps import.
   - The dashboard port is free (`lsof -iTCP:$PORT -sTCP:LISTEN`).
   - The camera config loads; it prints `calibration=UNCALIBRATED mount_measured=False` at `d1b607a`.
   - `ssh -o BatchMode=yes -o ConnectTimeout=6 "$PI_HOST" true` succeeds, and the Pi camera is free (or the replay frames exist).
   - Ollama answers on `:11434`.
2. **Qwen.** If `:$QWEN_PORT` already answers `/health` with `"advisory_only":true`, the script reuses it. Otherwise it starts `camera_mapping.qwen_launcher` and warms the model with one request.
3. **Dashboard** on `:$PORT`, waiting until `/api/perception` answers.
4. **Camera runner:** `camera_mapping.live --source pi --pi-host "$PI_HOST"` (or `--source replay --replay $REPLAY_GLOB`) with `--dashboard`, the optional `--qwen-url` and `--depth`, and `--jsonl $LOG/perception.jsonl`. It waits up to 90 s for `frames_received > 0`.
5. It opens `http://localhost:$PORT/#percep`, prints one status line every 5 s, and restarts the runner when it dies.
6. **Logs** go to `~/Team15_evidence/camera_mapping/<YYYYmmdd-HHMMSS>/` (`dashboard.log`, `camera.log`, `qwen.log`, `perception.jsonl`, state only, no images).

### 5.1 Manual equivalent (three terminals)

```bash
python3 -B -m dashboard.serve --port 8000
python3 -B -m camera_mapping.qwen_launcher --qwen-root "$QWEN_WORKSPACE" --port 8090      # optional
python3 -B -m camera_mapping.live --source pi --pi-host "$TEAM15_PI_HOST" --pi-user "$TEAM15_PI_USER" \
  --pi-key "$TEAM15_PI_KEY" --dashboard http://127.0.0.1:8000 --qwen-url http://127.0.0.1:8090 \
  --jsonl "$TEAM15_EVIDENCE/camera_mapping/manual.jsonl"
```

`camera_mapping.live` flags: `--source {pi,local,replay}` (default `pi`), `--camera N`, `--pi-host/--pi-user/--pi-key`, `--pi-fps` (5), `--pi-rotation` (180), `--replay FILE…`, `--replay-fps` (2), `--config` (default `camera_mapping/configs/imx708_robot.json`), `--dashboard` (default `http://127.0.0.1:8000`), `--qwen-url`, `--advise-every-s` (10), `--dnn-model` (`frcnn_r50_fpn_v2`), `--depth {off,metric,relative}`, `--depth-every` (3), `--duration-s` (0 = until Ctrl-C), `--jsonl FILE`, `--jpeg-quality` (70). Exit codes: **3** camera unavailable or stream lost; **4** another runner already feeds this dashboard (HTTP 409).

`camera_mapping.qwen_launcher` flags: `--qwen-root`, `--host` (`127.0.0.1`), `--port` (8090), `--config {A_DETERMINISTIC,B_QWEN_BASE,C_QWEN_RAG}` (default `C_QWEN_RAG`), `--model` (`qwen3.5:2b-q4_K_M`), `--ollama-url` (`http://127.0.0.1:11434`), `--timeout-s` (15). It exits with code 2 if `sqlite3.threadsafety != 3`. That check exists because it opens SQLite with `check_same_thread=False` to work around a threading bug in `rescue_qwen.service` ([21](21_TROUBLESHOOTING.md)).

### 5.2 Recorded-frame fallback (no Pi)

```bash
scripts/camera_demo.sh --replay
# or manually:
python3 -B -m camera_mapping.live --source replay --replay "$TEAM15_EVIDENCE"/camera_pi_validation/*.png \
  --dashboard http://127.0.0.1:8000
```

The dashboard labels these frames **RECORDED**. Say so out loud during a demo. The frames are private and not in Git.

### 5.3 Camera calibration (still to do)

`python3 -m camera_mapping.calibrate {capture,set-mount,fit-pitch,report}`. The procedure, with tape-measured distances and a named measurer (`--by`), is in [docs/camera_mapping/CALIBRATION.md](camera_mapping/CALIBRATION.md). Until `set-mount --height-m … --pitch-deg … --by …` has been run, the corridor is never CLEAR and no route is offered.

## 6. Simulations

| What | Command | Label |
|---|---|---|
| Route A→G | `python3 -m planner.route A G` (also `--block J-K`, `--graph FILE`) | SYNTHETIC graph |
| Rover scenarios | `python3 -m rover.simrun --list`; `python3 -m rover.simrun C` (prints the final `team15.rover_nav_status/1`) | SIMULATED |
| Grove ranging, console | `python3 -m ranging read --count 10 --sim-scenario approach` (`--sim-scenario {static,approach,open,disconnected}`, `--sim-distance`, `--sim-noise`, `--sim-dropout`) | SIMULATED (default config `simulated`) |
| Grove ranging, service | `python3 -m ranging serve --sim-scenario approach --no-evidence` → `http://127.0.0.1:8765/range` | SIMULATED |
| Grove consumer view | `python3 -m ranging watch --url http://127.0.0.1:8765/range` | SIMULATED |
| LiDAR panel JSON | `python3 -m lidar replay --scenario 08_obstacle_approaching` | SIMULATED |
| LiDAR replay server | `python3 -m lidar replay --scenario 08_obstacle_approaching --serve` → `http://127.0.0.1:8775/` | SIMULATED |
| LiDAR on the dashboard card | `python3 -B -m dashboard.serve --range-fixture lidar/fixtures/dashboard_range_series_approach.json` | SIMULATED |
| LiDAR processing latency | `python3 -m lidar bench -n 200` | SIMULATED scans |
| Drone fleet, in process | `cd team15_starter && python3 homebase.py --sim --web` → `http://localhost:8080` | SIMULATED |
| Drone fleet over a virtual serial port | terminal 1: `cd team15_starter && python3 fleet_sim.py --pty`; terminal 2: `python3 homebase.py --port <printed pty>` | SIMULATED |
| Fleet studies (may take minutes; `--workers` parallelises) | `cd team15_starter && python3 fleet_eval.py --study fleet` ; `python3 run_compare.py --trials N` | SIMULATED |

Scenario lists: `rover.simrun --list` prints A–H, and `lidar/fixtures/index.json` lists the LiDAR scenarios. Details are in [18 Simulation](18_SIMULATION.md).

## 7. Hardware procedures (pointers only; each needs explicit approval)

| Hardware | Gate | Procedure |
|---|---|---|
| Grove ultrasonic | `ranging check-config --hardware` must pass with a two-person-verified config. Read-only Pi checks: `python3 -m ranging preflight --config …` | [ranging/WIRING.md](../ranging/WIRING.md), [ranging/HARDWARE_VALIDATION.md](../ranging/HARDWARE_VALIDATION.md), [14](14_GROVE_ULTRASONIC.md) |
| RPLIDAR C1 | `lidar check-config --hardware` must pass; `scan-once` also needs `--approved-by` | [LIDAR_C1_STATIONARY_SCAN_PROCEDURE](lidar/LIDAR_C1_STATIONARY_SCAN_PROCEDURE.md), [LIDAR_C1_DEMO_RUNBOOK](lidar/LIDAR_C1_DEMO_RUNBOOK.md) |
| StickC firmware and RoverC motors | `RoverCAdapter` refuses to construct until `HardwareVerification` is complete; flashing needs separate approval with the RoverC switched OFF | [rover/BENCH_RUNBOOK](rover/BENCH_RUNBOOK.md), [rover/BRIDGE_PROTOCOL](rover/BRIDGE_PROTOCOL.md) |

`python3 -m lidar discover` lists candidate serial devices without opening any. That is the only device-adjacent command that is safe to run at any time.

## 8. Tests

```bash
python3 -m pytest -q -p no:cacheprovider                     # default: 540 at d1b607a
python3 -B -m pytest -q -p no:cacheprovider lidar/tests      # 124
python3 -B -m pytest -q -p no:cacheprovider ranging/tests    # 126
python3 -B -m pytest -q -p no:cacheprovider qwen_advisory/tests   # 23
python3 -B -m pytest -q -p no:cacheprovider team15_starter/tests  # 5
(cd team15_starter && python3 -B tests/test_link.py)         # 30 checks
```

See [19](19_TESTING_AND_BENCHMARKS.md) for what skips without private data.

## 9. Safe shutdown and cleanup

1. **Demo script:** press **Ctrl-C** in its terminal. The `INT` trap kills every PID it started (Qwen service, dashboard, camera runner), waits, prints the log folder and exits with code 130. Before `73539a7` the trap did not exit, so the restart loop carried on; the fix is on `main`.
2. **Manual processes:** Ctrl-C each terminal. `camera_mapping.live` then posts `camera_status: STOPPED` to the dashboard. Stopping the runner first and the dashboard last lets panel D show the stop.
3. **Leftovers.** The engineering session logs used these patterns. Each matches only Team-15 processes:

   ```bash
   pkill -INT -f "scripts/camera_demo.sh"          # lets the trap clean up its children
   pkill -f "camera_mapping.live"                  # e.g. a stray --source replay runner (the 8 Nov double-producer case)
   pkill -f "dashboard.serve --port 8000"
   pkill -f "rescue_qwen"                          # only if a Qwen service was started outside the launcher
   ```

   Do not use a bare `pkill python3`; it can kill unrelated work, such as another session's Qwen benchmark.
4. **Port release check:**

   ```bash
   lsof -nP -iTCP:8000 -sTCP:LISTEN; lsof -nP -iTCP:8090 -sTCP:LISTEN; lsof -nP -iTCP:8775 -sTCP:LISTEN
   ```

   No output means the ports are free. Leave Ollama (`:11434`) running unless you started it for this demo.
5. **On the Pi** (only if you started something there): the camera sender exits when its SSH session closes, and writes nothing to disk. Check that no `picamera2`/`rpicam-` process remains with `ssh "$TEAM15_PI_HOST" "ps -eo pid,args | grep -E '[p]icamera2|[r]picam-'"`. A `ranging serve` started with `--hardware` (never done) would need Ctrl-C on the Pi; its snapshot file goes stale on its own, and consumers then read UNKNOWN.
6. **Rover (when hardware exists):** the e-stop is latched (`EmergencyStop`, stop file, `POST /rover/estop` in the unmounted router). There is deliberately **no** remote reset. The physical RoverC power switch is the final stop ([rover/SAFETY_AND_LIMITATIONS](rover/SAFETY_AND_LIMITATIONS.md)).

## 10. Evidence hygiene

- Everything the camera tools write goes under `~/Team15_evidence/` or `~/Documents/Team-15-evidence/`, never into the repo. `test_no_photos_tracked_in_git` fails CI if an image is committed.
- Never commit model weights (`.gitignore` blocks `*.safetensors`, `*.gguf`, `*.pt`, …).
- Do not paste hosts, IPs or key paths into committed files; use the environment variables from §0.
