# 26 · Hackathon demo guide

This is the judge-facing demo plan. It covers what to set up, what to show in about five minutes, what to say at each step, which claims are safe, and what to do when something fails. It builds on the team's existing scripts: [docs/camera_mapping/JUDGE_DEMO.md](camera_mapping/JUDGE_DEMO.md) (the five-step flow), [docs/camera_mapping/DEMO.md](camera_mapping/DEMO.md) (launch options), [docs/lidar/LIDAR_C1_DEMO_RUNBOOK.md](lidar/LIDAR_C1_DEMO_RUNBOOK.md) (SIMULATED LiDAR) and [docs/rover/BENCH_RUNBOOK.md](rover/BENCH_RUNBOOK.md) (why the robot does not drive). It also corrects one important gap: what the demo **actually shows at `d1b607a`**, given that the camera mount was never measured.

**Status:** Hardware-verified for the camera, dashboard and Qwen path (live Pi runs on 8 Nov 2026). Navigation is shown in simulation only. The robot stays stationary.

**Related:** [00 Overview](00_PROJECT_OVERVIEW.md) · [20 Runbook](20_DEPLOYMENT_AND_RUNBOOK.md) · [21 Troubleshooting](21_TROUBLESHOOTING.md) · [16 Dashboard](16_DASHBOARD.md) · [17 Safety](17_SAFETY_ARCHITECTURE.md) · [25 Limitations](25_LIMITATIONS_AND_FUTURE_WORK.md)

---

## 1. The story in one breath

> "A rescue robot must never say 'clear' when it simply can't see. We built a camera-first reconnaissance stack in which every number carries its provenance and uncertainty, unknown stays unknown, a human confirms every person, and the AI explains but has no authority over the motors."

Judges score mission relevance, a working live demonstration, and deployability ([00 §1](00_PROJECT_OVERVIEW.md#1-the-problem)). The demo puts the live camera first, because that is the part that really runs on hardware. It then shows the safety engineering in simulation, and it is open about what is not yet proven.

## 2. Before the judges arrive (10 minutes)

| Check | How | If it fails |
|---|---|---|
| Robot **stationary**, motor power **off**, camera looking down a clear corridor | visual | — |
| Consent from anyone who will appear on camera | ask | point the camera away from people |
| Camera not facing glass (window reflections caused false person boxes on the bench) | visual | re-aim ([21 §2](21_TROUBLESHOOTING.md#2-camera-and-the-pi-link)) |
| Pi reachable | `ssh -o BatchMode=yes -o ConnectTimeout=6 "$PI_HOST" true` | plan on `--replay` (§5) |
| Ollama up | `curl -sf localhost:11434/api/version` | `ollama serve`, or run `--no-qwen` |
| Port 8000 free | `lsof -nP -iTCP:8000 -sTCP:LISTEN` | `PORT=8001` |
| No stray camera runners | `pgrep -fl camera_mapping.live` | `pkill -f "camera_mapping.live"` |
| Start | `scripts/camera_demo.sh` | read the `FAIL` line; see [21](21_TROUBLESHOOTING.md) |

The script prints `calibration=UNCALIBRATED mount_measured=False`. At `d1b607a` that is expected, and it changes what the judges will see (§3).

Optional and honest: if a teammate can **measure** the lens height above the floor and the camera pitch before the demo, record it with `python3 -m camera_mapping.calibrate set-mount --height-m <h> --pitch-deg <p> --by <name>`. That enables the ground-plane method and FREE cells. Distances stay `UNCALIBRATED_ESTIMATE` until the tape procedure in [CALIBRATION](camera_mapping/CALIBRATION.md) passes. Never enter guessed values.

## 3. What the demo really shows at `d1b607a`

`docs/camera_mapping/JUDGE_DEMO.md` steps 2–4 describe a chair at "~1.0 m ±0.4" from the ground-plane method, a BLOCKED verdict, and a blue alternate route appearing when the chair moves. **Those outputs need a measured mount.** With the shipped config (`mount.measured: false`), the code does the following, as designed ([camera_mapping/README](../camera_mapping/README.md)):

- the ground-plane method is off. Distances come only from the known-height prior, which refuses edge-cut and non-upright boxes;
- there are no FREE cells, the corridor is **never CLEAR**, and the route is `NO_SUPPORTED_ROUTE`.

Every recorded run of the demo script agrees: **every frame had corridor status UNKNOWN.**

| Run folder (`$TEAM15_EVIDENCE/camera_mapping/`, local time −0500, 8 Nov) | Source mode | States logged | Corridor status | `perception.jsonl` SHA-256 |
|---|---|---|---|---|
| `20261108-064151` | RECORDED | 434 | UNKNOWN 434/434 | `0beec0d5…f2040b7` |
| `20261108-064602` | (dashboard only; no states) | 0 | — | — |
| `20261108-064743` | RECORDED | 46 | UNKNOWN 46/46 | `14fa9ebb…74090` |
| `20261108-064835` | RECORDED | 486 | UNKNOWN 486/486 | `a7aaf433…bd4` |
| `20261108-065157` | **LIVE-HW** | 266 | UNKNOWN 266/266 | `7017f97c…c98bb` |
| `20261108-065518` | RECORDED | 50 | UNKNOWN 50/50 | `16e774ed…e0698` |
| `20261108-071628` | RECORDED | 10 | UNKNOWN 10/10 | `88e38851…a16a19` |

The LIVE-HW run is the one in [EVALUATION §3b](camera_mapping/EVALUATION.md): 266 frames at 3.76 fps, with a real person and chair detected. So **present the UNKNOWN as the feature**: the system refuses to call the corridor clear because it knows its own geometry is unmeasured. Do not narrate a BLOCKED, CLEAR or route moment unless you can see it on the screen.

## 4. Five-minute flow

### 0:00 Opening (15 s)

**Show:** the dashboard at `http://localhost:8000/`, scrolled to panels A–D below the sector map.

**Say:** "Everything here is labelled. Detections are LIVE from the Pi camera on the robot. Distances are camera ESTIMATES with uncertainty, or UNKNOWN. Navigation is advisory and simulated. The robot does not move in this demo."

### 0:15 Step 1: person detection (60 s)

**Do:** a consenting teammate walks into view, full body visible and a few metres away.

**Show:** Panel A shows a green `person 0.9x` box. Panel C shows "Potential person detected · UNCONFIRMED".

**Say:** "This is COCO Faster R-CNN running on the Mac's GPU at about 4–5 frames a second. On the live Pi stream we measured a 186 ms median detector time and about 480 ms from capture to dashboard. A detection is a *candidate*. Only an operator can confirm it."

If the person is close, the distance reads **UNKNOWN** (`NO_METHOD_APPLICABLE`) because the box is cut by the frame edge. Point that out; it is the honest output.

### 1:15 Step 2: obstacles and the honest UNKNOWN (60 s)

**Do:** place a chair on the centreline.

**Show:** Panel A shows `chair` with either a known-height estimate labelled `UNCALIBRATED_ESTIMATE` or `UNKNOWN` with its reason. Panel C shows the corridor **UNKNOWN**, with reasons that include the unmeasured mount.

**Say:** "To turn a box into metres we need the camera's height and tilt. We haven't tape-measured them yet, so the system refuses to call the corridor clear and offers no route. A rescue robot that guesses 'clear' is worse than one that says 'I don't know'."

*(If the mount was measured in §2, JUDGE_DEMO steps 2–4 apply instead: BLOCKED, then a solid or dashed route when the chair moves aside. Say "uncalibrated estimate" for every distance.)*

### 2:15 Step 3: the local map (30 s)

**Show:** Panel B shows the robot at the bottom, the blue camera field of view and the detected objects. Cells stay grey (UNKNOWN).

**Say:** "This is a robot-relative map. We don't claim SLAM. Grey means unknown, and we never assume the space behind an obstacle is free."

### 2:45 Step 4: rescue guidance with Qwen + RAG (45 s)

**Show:** the "Qwen (guarded, RAG)" box in Panel C. It summarises the scene, flags the person for operator review, names the next observation, and cites knowledge-base chunks such as `team-ugv-guide#false-positives-at-ground-level-0`.

**Say:** "This is Qwen3.5-2B running locally through Ollama, with retrieval over our rescue knowledge base and behind a guard. It takes about 4–6 seconds per advisory, asynchronously. It explains; it has no authority. Anything motor-like is discarded. We also trained a LoRA adapter. It scored 218 of 230 on our synthetic mission benchmark and is public on Hugging Face, but this demo runs the **base** model, because our serving path can't load the adapter yet."

### 3:30 Step 5: failure behaviour (30 s)

**Do:** stop the camera runner. Easiest: unplug the Pi's network, or `pkill -f "camera_mapping.live"` from another terminal. Ctrl-C on the script would stop everything.

**Show:** Panel D goes **STALE**, the map empties to UNKNOWN, and the status becomes UNKNOWN within about 2 s. The script restarts the runner in about 10 s (up to 5 times).

**Say:** "When we lose the camera, we never keep showing the last answer."

### 4:00 Safety engineering in simulation (60 s; pick one)

| Option | Command | Say |
|---|---|---|
| Rover rerouting | `python3 -m rover.simrun C` (or `--list`) | "Scenario C: an obstacle blocks D–E. The robot scans, retreats 4 m and replans D-K-L-M-G, 46 m, on a synthetic graph. Scenario G latches SENSOR_STALE and does not restart by itself." |
| LiDAR | `python3 -m lidar replay --scenario 08_obstacle_approaching --serve` → `http://127.0.0.1:8775/` | "360° view versus the ultrasonic's narrow cone. No return reads UNKNOWN, not clear. Everything here is SIMULATED; the LiDAR has not been scanned for real." Never say a LiDAR range is a person's distance |
| Gates | `python3 -m lidar check-config --config lidar/configs/c1_pi5.UNVERIFIED.json --hardware; echo $?` | "Hardware stays locked until a two-person checklist is filled in. CI checks that this refusal still happens." |

### Close (15 s)

"Live camera perception with honest uncertainty, an operator in the loop, and the AI kept advisory. The motion stack is built and fail-closed in simulation; the hardware is gated until it is verified."

## 5. Fallbacks

| Problem during the demo | Fallback | What to say |
|---|---|---|
| Pi unreachable | `scripts/camera_demo.sh --replay`; the dashboard says **RECORDED FRAMES** | "These are recorded frames from the Pi camera on the robot, replayed. The pipeline is identical." |
| Ollama or Qwen down | `scripts/camera_demo.sh --no-qwen`, or let it degrade (the script warns, and Panel C shows the deterministic summary) | "The deterministic summary is always there; Qwen only adds explanation." |
| Mac detector too slow | stop other GPU work; drop `--depth` | — |
| Dashboard port taken | `PORT=8001 scripts/camera_demo.sh` | — |
| Camera mapping broken | bench sightings path: `python3 -B -m perception.live_camera --source pi --sector G --duration-s 600 \| python3 -B -m core.camera_bridge`, plus `python3 -B -m dashboard.serve`; or use the Mac camera without `--source pi` | "This is the original person-sighting pipeline with operator confirm/reject and route A→G." |
| Everything live fails | simulations only (§4 options) and the recorded evidence in [EVALUATION](camera_mapping/EVALUATION.md) | be explicit that this is simulation or recorded data |
| Drone-fleet question | `cd team15_starter && python3 homebase.py --sim --web` → `http://localhost:8080` | "This is a separate SIMULATED drone-fleet planner from teammates; it shares no code with the robot." |

## 6. What not to claim

- **No measured distances.** Every camera distance is `UNCALIBRATED_ESTIMATE` or `UNKNOWN`. Distance accuracy is **NOT MEASURED**.
- **No driving, autonomy or SLAM.** No wheel has turned under this code. The StickC firmware has never been compiled or flashed, and no StickC was detected on the Pi in reported checks.
- **No working range sensor.** The Grove ultrasonic returned 0 of 50 valid readings in each of two real runs, cause unknown. The RPLIDAR C1 has never scanned.
- **Not the LoRA.** The demo model is base Qwen3.5-2B + RAG + guard. The 218/230 score is on a **synthetic** benchmark.
- **Not a box detector.** COCO has no "box" class.
- **Not a validated person detector.** It false-alerted on window reflections, and a clean 60 s empty-scene test was never achieved.
- Don't call camera FREE space "clear floor". It means only that nothing was detected.

## 7. Likely questions

| Question | Honest answer | Source |
|---|---|---|
| "How accurate are the distances?" | "Not measured yet. The tape calibration and mount measurement are the next step; the tooling and its pass/fail gate exist." | EVALUATION §1, [05](05_DEPTH_AND_DISTANCE_ESTIMATION.md) |
| "Why run on the Mac, not the Pi?" | "About 186 ms per frame on the Mac GPU. The Pi streams JPEGs over SSH; nothing is installed on it." | [03](03_MAC_AI_INFERENCE.md) |
| "What stops Qwen driving the robot?" | "Nothing it outputs reaches the motor path. A static test fails the build if non-allow-listed code imports the supervisor, driver, protocol or bridge, and the guard discards motion-like output." | [17](17_SAFETY_ARCHITECTURE.md), [11](11_AI_AGENT_AND_TOOLS.md) |
| "What happens if the link to the motors dies?" | "In design: the host supervisor latches a fault, and the StickC firmware zeroes the motors after 250 ms without valid frames. That is tested against a model of the firmware only, not on hardware." | [13](13_M5STICKC_BRIDGE.md) |
| "Why didn't the ultrasonic work?" | "Unknown. Two real 50-ping runs gave no echoes at all. Wiring, power, pin choice and level shifting are all candidates." | [14](14_GROVE_ULTRASONIC.md) |
| "How many tests?" | "818 automated tests plus a 30-check protocol script, all passing at the final commit. They prove logic, not physical safety." | [19](19_TESTING_AND_BENCHMARKS.md) |
| "Why does the sighting say drone D1 / sector G?" | "The project started as a drone search plan; the format kept those fields, and the sector is operator-assigned, never measured." | [27](27_PROJECT_TIMELINE.md), [SIGHTING_FORMAT](../perception/SIGHTING_FORMAT.md) |

## 8. After the demo

Ctrl-C the script. It stops everything it started and prints the log folder. Then check the ports with `lsof` ([20 §9](20_DEPLOYMENT_AND_RUNBOOK.md#9-safe-shutdown-and-cleanup)). The run's `perception.jsonl` (state only, no images) stays in `~/Team15_evidence/camera_mapping/<timestamp>/`. Keep it out of Git.
