# TEAM15_DRONE_SEARCH_BUILD.md

> **Conversion note.** Converted from the PDF build guide `Claude.pdf` (25 pages, author Mohammed Mubashir Uddin Faraz, 2026-11-07). Headings, tables, code blocks and terminal prompts are kept as in the PDF. Small grey source chips in the PDF (for example `apple`, `github`) had no link targets in the PDF and are kept as *(sources: …)*. Some wide code lines were already cut off at the right page edge in the PDF. Those lines appear exactly as printed, and a **⚠ Truncated in source PDF** note follows each affected block. The missing text was not guessed.

Created as a downloadable artifact by the assistant (no write access to the local repo); copy into the repository root as TEAM15_DRONE_SEARCH_BUILD.md.

**Bottom line:** Today we commit to three SIMULATED scouts plus a live laptop camera detector, an explicit synthetic trail graph with Dijkstra routing, a timestamped observation/track store, and Qwen as a validated, optional tool-caller; real aircraft are a staff-flown, daylight-only upgrade path, and the physical “mother ship” is out of scope.

**TL;DR**

- Build one shared pipeline (observation → candidate/track → route → dashboard) against one SYNTHETIC fixture, `fixtures/synthetic_g_to_k.jsonl`, so the simulator, perception, planner, dashboard and Qwen tools all integrate the moment each passes its own test; first end-to-end G→K checkpoint at H+4.
- Localization is honest by construction: default output is “candidate in sector G” (SECTOR_ONLY); ground-plane coordinates only with a measured camera pose; the iPhone BLE path works only while our app is in the foreground (Apple: in background, service UUIDs go to an overflow area a non-Apple receiver cannot decode), so BLE is a 60-minute experiment with a labeled stand-in beacon fallback. *(sources: apple, apple)*
- Run Qwen3.5-4B on the M4 Mac via llama-server (`--jinja`, thinking explicitly disabled) behind one OpenAI-compatible tool interface that also works on the Pi; the Pi’s 26 TOPS Hailo-8 HAT runs vision, not LLMs; every Qwen tool request passes a validator before execution, and everything still works if Qwen is down. *(sources: raspberrypi, github)*

---

## 0. What the assistant could and could not access

| Item | Status |
|---|---|
| Repo `https://github.com/CodeMetalForge-Hackathon/Team-15` | **Not readable.** Fetch returned a client error (consistent with a private repo); no README, branches or files were visible; nothing is indexed by search. |
| GitHub invitation | Organisation invitation to CodeMetalForge-Hackathon/Team-15 (2026-11-07). **Accept it first** — then the repo becomes visible. |
| Saturday Mission Brief text | **Not accessible.** Only the user’s statement: flights only with Code Metal staff, daytime only. |
| Organizer hardware inventory / photos of issued equipment | **Not accessible.** Equipment below is from the user’s description; everything else is UNCONFIRMED. |
| Local repo write access | **None.** This file is returned as content. |
| Official event page `https://www.codemetal.ai/forge-hackathon` | Read. Objectives: locate isolated people without reliable GPS/cell/fixed comms; detect life and hazards; map changing conditions; deliver critical information over degraded comms. Judged on mission relevance, a working live demonstration, and deployability. Build Sat Nov 7 10:00 → Sun Nov 8 12:00 hard cutoff; demos follow. Teams up to four. *(source: codemetal)* |

---

## 1. Start here (one page)

**Chosen architecture (commit today):** 3 SIMULATED scouts (D1 A–G, D2 H–P, D3 Q–Z) emit observations into a base-station store on the M4 Mac; a tracker turns observations into candidates/tracks; a Dijkstra planner routes the responder on an explicit SYNTHETIC trail graph; a browser dashboard shows markers, evidence, age, confirmation state and route versions. A live laptop/USB camera person detector can stand in as “D1 camera” (bench, no aircraft). Qwen proposes tool calls; a validator approves; deterministic code executes.

**Actual equipment dependencies**

| Need | Equipment | Status |
|---|---|---|
| Base station, Qwen host, dashboard | MacBook Pro M4 | In hand (RAM UNCONFIRMED: run `system_profiler SPHardwareDataType`) |
| Edge node, BLE receiver, Hailo vision | Raspberry Pi 5 kit labeled 16 GB / 26 TOPS | In hand; HAT model UNCONFIRMED until `hailortcli fw-control identify` shows `HAILO8` *(source: raspberry)* |
| Wired link Mac↔Pi | Ethernet switch + USB/Ethernet adapter | In hand |
| Stand-in BLE beacon | Two small Seeed boards | UNCONFIRMED type (possibly XIAO ESP32-class) |
| Physical demo props (buzzer/LCD “beacon heard” indicator) | Seeeduino + Grove kit γ | In hand; no GPS, no radio, no gas sensor |
| Camera | Mac built-in or USB webcam | In hand (Mac); Pi camera UNCONFIRMED |
| Drones, thermal, GNSS, UWB, LoRa | Organizer library | UNCONFIRMED until checked out |

**First three actions (everyone, next 30 minutes)**

1. Mubashir: accept the GitHub invite in Gmail; everyone: `gh repo clone CodeMetalForge-Hackathon/Team-15`.
2. Integration owner opens PR #1 (skeleton + contract + fixture + CI, < 100 lines) and merges it within 30 minutes.
3. Each owner starts their terminal with the startup prompt in §6 and runs their first command.

**Demo legend (badge on screen + `source_mode` tag in every log line)**

| Badge | `source_mode` | Meaning |
|---|---|---|
| 🟥 SIMULATED | `SIMULATED` | Aircraft, position and observation produced by our simulator |
| 🟨 RECORDED-IMAGERY | `RECORDED-IMAGERY` | Real frames captured earlier; keeps original capture time and source ID; never counted as live |
| 🟩 LIVE-HW (bench) | `LIVE-HW` + `platform=BENCH` | Real sensor right now, not airborne (e.g., laptop camera declared as “D1 camera”) |
| 🟩 LIVE-HW (airborne) | `LIVE-HW` + `platform=AIRCRAFT` | Real sensor on a staff-flown aircraft; requires human-observed evidence in the PR |

---

## 2. Architecture diagram

```text
                 ┌──────────────────────── M4 Mac (base station, time authority) ───────────────────────┐
 SIMULATED       │                                                                 │
 scouts D1-D3 ──►│  ingest (HTTP POST /observations, JSONL replay)                 │
 (sim/)          │      │  dedup by obs_id, clock-correct, tag source_mode         │
                 │      ▼                                                          │
 LIVE camera ───►│  SQLite store (core/store.py): observations | tracks | routes(v) | scouts | coverage  │
 (perception/)   │      │                         ▲                                │
                 │      ▼                         │ validated tool results         │
 RECORDED  ─────►│  tracker/association ──► planner (Dijkstra on trail graph) ──► dashboard (browser)    │
 imagery         │  (core/tracker.py)        (planner/)                            (dashboard/)          │
                 │      ▲                         ▲                                │
                 │      │   tool calls            │                                │
                 │  Qwen (llama-server, OpenAI API) ──► VALIDATOR (agent/validator.py) ──► tools         │
                 │      (fallback: deterministic coordinator, agent/coordinator.py)                     │
                 └───────────────▲──────────────────────────────────────────────────────────────────
                                 │ Ethernet switch (team15-pi.local)
                 ┌───────────────┴──────────── Raspberry Pi 5 ─────────────────┐
                 │ BLE scanner (bleak/BlueZ) → observations kind=BLE_ENROLLED_BEACON │
                 │ Hailo-8 detection (optional) → observations kind=PERSON_VISUAL     │
                 │ llama-server (optional Qwen host, benchmarked)                  │
                 └──────────────────────────────────────────────────────────────────┘
 Aircraft motion: ONLY the approved flight controller / staff pilot or sim/. Our code sends tasking requests, never motion.
```

---

## 3. Worked example: G → K (ALL DATA SYNTHETIC)

### 3.1 Grid (SYNTHETIC)

Each cell is 10 m × 10 m; cell (col,row) spans x∈[10·col, 10·col+10] m, y∈[10·row, 10·row+10] m.

```text
row0:  A  B  C  D  E  F  G        ← D1 sector A–G
row1:  H  I  J  K  L  M  N        ← D2 sector H–P (H..N, O, P)
row2:  O  P  Q  R  S  T  U        ← D3 sector Q–Z (Q..U, V..Z)
row3:  V  W  X  Y  Z
```

### 3.2 Walkable trail graph (SYNTHETIC distances, undirected; no edge = no known trail)

| Edge | m | Edge | m | Edge | m |
|---|---|---|---|---|---|
| A–B | 10 | E–F | 10 | L–M | 10 |
| B–C | 10 | F–G | 10 | M–G | 14 |
| C–D | 10 | C–J | 10 | D–K | 12 |
| D–E | 10 | J–K | 10 | A–H | 11 |
| K–L | 10 | H–I | 10 | I–J | 10 |

Q–Z have **no known trail edges** (Drone 3’s sector is aerially searchable but not known-walkable).

### 3.3 Expected route results (CI asserts these)

| Case | From→To | Expected path | Length | Status |
|---|---|---|---|---|
| R1 first report | A→G | A-B-C-D-E-F-G | 60 m | OK (next best A-B-C-J-K-L-M-G 74 m) |
| R2 responder at C, target K | C→K | C-J-K | 20 m | OK (C-D-K 22 m) |
| R3 J–K blocked | C→K | C-D-K | 22 m | OK, reason “edge J–K blocked by responder report” |
| R4 remaining to G | C→G | C-D-E-F-G | 40 m | OK |
| R5 unreachable | C→Y | — | — | NO_KNOWN_ROUTE “Y has no known walkable connection” |

### 3.4 Timeline and dashboard at each step (mission clock T+seconds)

Association gate (SYNTHETIC parameter `v_max = 1.5 m/s`): two SECTOR_ONLY sightings can be one person only if `min_cell_distance / Δt ≤ v_max`. Minimum distance between cells G and K = 20 m (G spans x 60–70, y 0–10; K spans x 30–40, y 10–20).

| Step | Event (arrival time) | Dashboard shows |
|---|---|---|
| 1 | T+0 responder at A | Responder icon at A. No candidates. |
| 2 | T+120.4 rx `D1-b1-000007` (obs T+120.0, D1, rgb PERSON_VISUAL, cell G, SECTOR_ONLY, conf 0.81) | 🟥 SIMULATED badge. Track **T1** “Candidate in sector G — 0 s old — unconfirmed — 1 source (D1 RGB)”. Route **v1** A→G 60 m solid. Alert banner within 1 s. |
| 3 | T+230 responder reports at C | Responder at C; v1 progress 20/60 m; remaining C→G 40 m. |
| 4 | T+250.3 rx `D2-b1-000012` (obs T+250.0, D2, cell K, conf 0.77) | Gate: 20 m / 130 s = 0.15 m/s ≤ 1.5 → **feasible, not proven**. T1 stays at G (solid). K shown as hollow marker “**Possible match to T1 — UNRESOLVED — review**”. Proposed route v2 C→K 20 m dashed. Buttons: Same / Different / Unsure. |
| 5 | T+262.0 rx `D1-b1-000009` (obs **T+180.0**, cell G, conf 0.64, delivery=replayed_after_link_loss) | Filed to T1 history at its **observation** time: “Late packet: observed T+180, received T+262 (82 s late). Does not supersede K (T+250).” Gate recomputed: 20 m / 70 s = 0.29 m/s → still feasible. **No marker moves.** |
| 6 | T+270 operator OP1 → SAME_PERSON | T1 current = K (T+250). G sightings (T+120, T+180) kept as grey history. Route **v2 C→K 20 m via J** active; v1 marked superseded. Explanation: “Destination changed G→K: D2 saw a person at K at T+250, newer than last G sighting (T+180); movement feasible (0.29 m/s ≤ 1.5); confirmed by OP1 at T+270.” |
| 7 | T+275 duplicate `D1-b1-000007` arrives again | Ignored (idempotent by obs_id); counter “duplicates: 1”. No change. |

Variant (older packet before t1): if the late packet had obs T+95 at G, it is likewise filed to history only; it never moves the current marker because T+95 < T+250.

If OP1 answers **Different**: T1 stays at G, new **T2** at K; two people counted; dashboard shows both routes from C (C→K 20 m, C→G 40 m) and asks the responder lead to choose. If **Unsure** or no answer: both markers remain, route v1 stays active, review chip stays red.

### 3.5 Second case: two real people (fixture `fixtures/synthetic_two_people.jsonl`)

- T+300.0 D1 sees person at G (conf 0.79); T+302.0 D2 sees person at K (conf 0.74).
- Gate: 20 m / 2 s = 10 m/s > 1.5 → **impossible for one person** → automatic split: T1 (G), T2 (K). Operator is notified, not asked.
- T+330 D1 sees G again: same drone, same cell, within 60 s (SYNTHETIC dedup window) → attaches to T1; people count stays 2.
- Search resumes: coverage ledger marks G and K “COVERED-GOOD”; deterministic coordinator assigns the next lowest-coverage cells; no double counting because counting is per track, not per observation.

---

## 4. Mubashir — start here

**You own:** camera capture + person detection, the first shortest-route implementation, the initial sector-scan simulator. **Your files (nobody else edits them):** `perception/`, `planner/`, `sim/` (each with its own `tests/`). **Your branch/terminal:** `claude --worktree t1-mubashir` → branch `worktree-t1-mubashir`.

**First task (build in this order)**

1. `planner/graph.py` + `planner/route.py`: load `fixtures/trail_graph_synthetic.json`, Dijkstra with `heapq`, `blocked` edge set, returns `RouteResult{status: OK|NO_KNOWN_ROUTE|UNKNOWN_NODE, path, edges, length_m, reason}`. Cross-check against `networkx.dijkstra_path` in tests only.
2. `sim/handoff.py`: replays a fixture JSONL into the store/ingest API, preserving `obs_time_s`, `rx_time_s`, `source_mode=SIMULATED`, with `--step` to advance one event per keypress.
3. `sim/scan.py`: lawnmower sweep per sector (D1 A→G, D2 H→P, D3 Q→Z), per-cell SYNTHETIC canopy fraction, coverage ledger rows.
4. `perception/live_camera.py` (separate test, later): OpenCV capture → pretrained person detector → observation `source_mode=LIVE-HW, platform=BENCH, drone_id=D1, cell=G (declared), how=SECTOR_ONLY`.

**Command to run (laptop, no aircraft)**

```bash
gh repo clone CodeMetalForge-Hackathon/Team-15 && cd Team-15
python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.t
pytest -q planner/tests sim/tests          # synthetic handoff tests
uvicorn dashboard.app:app --port 8000 &     # dashboard (integration owner's code)
python -m sim.handoff --fixture fixtures/synthetic_g_to_k.jsonl --post http://local
```

> ⚠ **Truncated in source PDF:** lines 2 (`…requirements.t`) and 5 (`…--post http://local`) are cut off at the right page edge.

**Expected result**

- Test A (SYNTHETIC D1 camera observation in G, 🟥 SIMULATED): map shows candidate at G; route v1 A→G = A-B-C-D-E-F-G, 60 m.
- Test B (responder at C, sighting at K): before confirmation the dashboard shows both G and K and a review prompt; after `SAME_PERSON`, route v2 = C-J-K, 20 m; G retained as history; the late G packet (obs T+180) does not move the marker.
- `pytest` prints all pass for: `test_route_a_to_g_60`, `test_route_c_to_k_20`, `test_blocked_jk_reroutes_22`, `test_y_no_known_route`, `test_handoff_preserves_obs_time`.

**Live-camera test (separate; run when a camera is ready)**

```bash
python -m perception.live_camera --camera 0 --declare-drone D1 --declare-cell G --p
```

> ⚠ **Truncated in source PDF:** the line is cut off after `--declare-cell G --p`.

Pass = a person stepping into view produces one 🟩 LIVE-HW (bench) candidate at G within a few seconds, with the frame thumbnail and bbox; no person → no candidate for 60 s. Record a phone video and the observer’s name in the PR (human-observed evidence). This is **not** an aerial detection claim.

**Who consumes your output next:** the integration owner’s `core/tracker.py` + dashboard (observations and `RouteResult`), and the Qwen owner’s `compute_route` tool, which wraps `planner.route.compute_route`.

**Startup prompt for Opus (paste into Claude Code)**

> You are working in repo CodeMetalForge-Hackathon/Team-15 on branch worktree-t1-mubashir. Read TEAM15_DRONE_SEARCH_BUILD.md sections 3 and 4 only. You may edit only perception/, planner/, sim/. Task 1: implement planner/route.py (Dijkstra with heapq, blocked-edge set, statuses OK / NO_KNOWN_ROUTE / UNKNOWN_NODE with human-readable reason) loading fixtures/trail_graph_synthetic.json, plus planner/tests/test_route.py asserting the five route cases in §3.3 exactly (60, 20, 22, 40, NO_KNOWN_ROUTE). Task 2: sim/handoff.py replaying fixtures/synthetic_g_to_k.jsonl to POST /observations, preserving obs_time_s and rx_time_s, tagging source_mode=SIMULATED, with --step. Do not invent hardware APIs. Commit after each passing test and push.

---

## 5. Other owners (one section each; no overlapping files)

Names other than Mubashir were not provided — fill them in.

### 5.1 Teammate B — Integration owner (contracts, store, tracker, dashboard, CI)

- **Files:** `contracts/`, `fixtures/`, `core/` (store.py, ingest.py, tracker.py, clock.py), `dashboard/`, `.github/`, `CODEOWNERS`, `Makefile`, `README.md`, `requirements*.txt`, `tests/e2e/`.
- **Branch:** `worktree-t2-integration`.
- **Input:** observation JSON (`contracts/observation.schema.json`), `RouteResult` from planner, validated tool results. **Output:** `GET /state` JSON (tracks, history, routes with versions, coverage, badges, review queue), `POST /observations`, `POST /operator_decision`, `POST /responder_position`, `POST /block_edge`.
- **First task:** PR #1 (§8.2). Then `core/tracker.py` implementing the gate, late-packet rule and review queue from §3.4; `dashboard/` as one HTML page polling `/state` every 500 ms (SVG grid, markers, route polyline, badges, explanation panel, “NO KNOWN ROUTE” red banner with reason).
- **Run:** `uvicorn dashboard.app:app --port 8000` then open `http://localhost:8000`.
- **Acceptance:** `pytest -q tests/e2e` passes `test_stale_g_after_k_does_not_move_marker`, `test_ambiguous_k_requires_review`, `test_two_people_split`, `test_replay_not_counted_live`, `test_duplicate_obs_idempotent`.

### 5.2 Teammate C — Qwen tools + validator owner (the named validator owner)

- **Files:** `agent/` (tools.py, schemas/\*.json, validator.py, qwen_client.py, coordinator.py), `bench/`.
- **Branch:** `worktree-t3-qwen`.
- **Input:** store queries via `core` functions; planner `compute_route`. **Output:** validated tool calls, tool results, an audit log row per request (`accepted|rejected`, reason).
- **First task:** write the five tool schemas (§7.4) and `validator.py` with tests rejecting: unknown tool, bad sector, unavailable drone, any coordinate/velocity argument, thermal when not checked out.
- **Run:** `pytest -q agent/tests && python -m bench.route_tool_call --base-url http://localhost:8080/v1 --runs 5`.
- **Acceptance:** 5/5 valid `compute_route` tool calls parsed; validator rejects all negative cases; `coordinator.py` produces the same next action with Qwen stopped.

### 5.3 Teammate D — Pi, SSH, networking, BLE experiment owner

- **Files:** `deploy/pi/`, `ble/`, `hardware/`, `docs/evidence/`.
- **Branch:** `worktree-t4-pi-ble`.
- **Input:** none upstream. **Output:** a reachable `team15-pi.local`; BLE observations `kind=BLE_ENROLLED_BEACON` posted to `/observations`; Pi benchmark numbers in `docs/evidence/`.
- **First task:** flash/boot Pi with hostname `team15-pi`, SSH key auth, wired link through the switch (§7.1); run the hardware identification commands; then the 60-minute BLE experiment (§9.3).
- **Run:** `ssh $PI_USER@$PI_HOST 'cd Team-15 && source .venv/bin/activate && python -m ble.scan --uuid $TEAM15_UUID --post http://<mac-ip>:8000'`.
- **Acceptance:** `ping team15-pi.local` works over Ethernet; `hailortcli fw-control identify` output pasted in PR; BLE result table filled (foreground / background / locked) with observer name and timestamp.

---

## 6. Parallel terminals

**Recommendation: exactly 4 coding terminals** (one per person). More sessions than people means unreviewed code; fewer leaves an owner idle. Non-coding shells (dashboard server, llama-server, ssh) do not count.

Claude Code: `claude --worktree <name>` creates `.claude/worktrees/<name>/` on branch `worktree-<name>` (Claude Code worktrees docs, `code.claude.com/docs/en/worktrees`); the repo needs at least one commit first. *(sources: claude, claudelessons)*

| T | Owner | Branch | Directories | Input → Output | First task | Run | Acceptance |
|---|---|---|---|---|---|---|---|
| T1 | Mubashir | worktree-t1-mubashir | perception/ planner/ sim/ | fixture, camera → observations, RouteResult | Dijkstra + 5 route tests | `pytest -q planner/tests sim/tests` | §3.3 numbers exact |
| T2 | Integration | worktree-t2-integration | contracts/ fixtures/ core/ dashboard/ .github/ tests/e2e | observations, RouteResult → /state, UI | PR #1, then tracker | `uvicorn dashboard.app:app --port 8000` | e2e 5 tests pass |
| T3 | Qwen/validator | worktree-t3-qwen | agent/ bench/ | store, planner → validated tool calls | schemas + validator | `pytest -q agent/tests` | negatives rejected; 5/5 tool calls |
| T4 | Pi/BLE | worktree-t4-pi-ble | deploy/ ble/ hardware/ docs/evidence/ | radio, Pi → BLE observations, benchmarks | SSH + identify hardware | `python -m ble.scan ...` | evidence table filled |

**Same small fixture for everyone:** `fixtures/synthetic_g_to_k.jsonl`, `fixtures/synthetic_two_people.jsonl`, `fixtures/trail_graph_synthetic.json` (owned by T2, read by all). Integrate as soon as each passes: T1’s planner merges → T2’s tracker calls it → T3’s `compute_route` wraps it → T4’s BLE posts into the same `/observations`.

**Startup prompts (copy-paste)**

T2:

> Repo CodeMetalForge-Hackathon/Team-15, branch worktree-t2-integration. Read TEAM15_DRONE_SEARCH_BUILD.md §3, §5.1, §8. Edit only contracts/, fixtures/, core/, dashboard/, .github/, tests/e2e/, CODEOWNERS, Makefile, README.md, requirements\*.txt. Step 1: create PR #1 exactly as §8.2 (< 100 lines). Step 2: core/store.py (SQLite tables observations, tracks, track_history, routes(version), scouts, coverage, operator_decisions, tool_audit), core/tracker.py implementing the association gate, late-packet rule (file by obs_time, never supersede newer state), dedup by obs_id, review queue. Step 3: dashboard/app.py (FastAPI) + one static HTML page polling /state. Write the five e2e tests in §5.1 first. Commit small, push often, open draft PRs.

T3:

> Repo CodeMetalForge-Hackathon/Team-15, branch worktree-t3-qwen. Read §7.3–§7.6. Edit only agent/ and bench/. Implement JSON schemas for inspect_sector, get_recent_observations, request_view, assign_scout, compute_route; agent/validator.py that checks every request before execution (whitelist, schema, legal sector A–Z, drone available, sensor checked out, no motion/coordinate arguments, rate limit) and logs accept/reject; agent/qwen_client.py using the OpenAI-compatible /v1/chat/completions with tools against QWEN_BASE_URL; agent/coordinator.py deterministic fallback. bench/route_tool_call.py measures time-to-first-token and end-to-end latency for one real compute_route call. Tests first.

T4:

> Repo CodeMetalForge-Hackathon/Team-15, branch worktree-t4-pi-ble. Read §7.1, §7.2, §9.3. Edit only deploy/, ble/, hardware/, docs/evidence/. Write deploy/pi/bootstrap.sh (apt packages, venv, clone), ble/scan.py using bleak BleakScanner with a detection_callback filtering our 128-bit service UUID, emitting observations kind=BLE_ENROLLED_BEACON with rssi and source_mode=LIVE-HW, and hardware/identify.md recording what each unknown board is. Never claim RSSI = distance. 60-minute time box on the iPhone test, then fall back to a stand-in beacon labelled STAND-IN.

---

## 7. Pi deployment and Qwen tool integration

### 7.1 Pi setup, SSH, local networking (owner: Teammate D)

[VERIFIED] Raspberry Pi OS disables SSH by default; enable it in Raspberry Pi Imager under Customisation → Remote Access (password or public-key), or later with `sudo systemctl enable --now ssh` (Raspberry Pi remote-access documentation). *(sources: raspberrypi, linuxize)*

```bash
# On the Mac
ssh-keygen -t ed25519 -C team15            # paste ~/.ssh/id_ed25519.pub into Image
# Imager: device Raspberry Pi 5, Raspberry Pi OS 64-bit, hostname team15-pi, user t
# Cable: Mac (USB/Ethernet adapter) ── Ethernet switch ── Pi
ping team15-pi.local
ssh $PI_USER@$PI_HOST

# On the Pi: identify and prepare
cat /proc/device-tree/model; free -h; df -h; nproc
sudo apt update && sudo apt install -y git python3-venv build-essential cmake libcu
sudo apt install -y hailo-all && sudo reboot      # Raspberry Pi AI software stack
hailortcli fw-control identify                    # expect "Device Architecture: HA
git clone git@github.com:CodeMetalForge-Hackathon/Team-15.git && cd Team-15
python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements-p
```

> ⚠ **Truncated in source PDF:** five lines are cut off at the right page edge: the `ssh-keygen` comment (`…into Image`), the Imager comment (`…user t`), the `apt install` line (`…cmake libcu`), the `hailortcli` comment (`…Architecture: HA`), and the final `pip install` (`…requirements-p`).

If `.local` does not resolve, read the Pi’s IP from `ip -4 addr` on a console, or from the Mac with `arp -a`.

[VERIFIED] Raspberry Pi AI HAT documentation: AI HAT+ uses Hailo-8L (13 TOPS) or Hailo-8 (26 TOPS); “Large Language Model (LLM) support: Not supported”; LLMs need AI HAT+ 2 (Hailo-10H, 40 TOPS). *(source: raspberrypi)* **So the Hailo-8 runs our detector, not Qwen.**

Identify the two small Seeed boards (UNCONFIRMED): read the silkscreen; plug into the Mac and run `ls /dev/cu.*` and `system_profiler SPUSBDataType | grep -A6 -i -E "xiao|espressif|seeed"`; on the Pi `lsusb`. If it reports an Espressif chip, `pip install esptool && esptool.py --port <port> chip_id` names the ESP32 variant. Record results in `hardware/identify.md`. ESP32-C3/S3/C6 or nRF52840 boards can advertise BLE; a SAMD21 board cannot.

### 7.2 Host selection procedure (decide by measurement, not expectation)

1. **RAM/storage:** Mac `system_profiler SPHardwareDataType | grep -E "Chip|Memory"; df -h /`; Pi `free -h; df -h`.
2. **Runtime support:** llama.cpp runs on both (Pi CPU; Mac Metal). Qwen3.5 small models (0.8B/2B/4B/9B) are supported by llama.cpp and MLX (Qwen README, verified earlier this week).
3. **Tool-calling compatibility:** [VERIFIED] llama.cpp server supports OpenAI-style function calling “with the --jinja flag” (llama.cpp function-calling docs). *(sources: github, github)* Ollama mirrors the tools API and accepts `"think": false` (Ollama tool-calling and thinking docs). *(sources: ollama, bswen)* `mlx_lm.server` exposes an OpenAI-compatible server; tool calling depends on the model’s chat template. *(source: autohand)*
4. **Thinking mode:** sources conflict — earlier verification said small Qwen3.5 models think by default; Unsloth’s Qwen3.5 guide says reasoning is disabled by default for 0.8B–9B; a llama.cpp issue (#20182) reports `enable_thinking:false` not taking effect in one build. *(sources: unsloth, github)* **Set it explicitly and check every response for `<think>`; the benchmark fails a run that emits thinking.**
5. **Benchmark one real `compute_route` tool call on each host**, 5 runs, record time-to-first-token, end-to-end latency (request → parsed tool call → planner result → final message), and validity.

```bash
# Mac (M4): Qwen3.5-4B
brew install llama.cpp
llama-server -hf unsloth/Qwen3.5-4B-GGUF:UD-Q4_K_XL --jinja \
  --chat-template-kwargs '{"enable_thinking":false}' --host 127.0.0.1 --port 8080 -
# Pi 5 CPU: Qwen3.5-0.8B (build llama.cpp from source)
git clone https://github.com/ggml-org/llama.cpp && cd llama.cpp
cmake -B build -DCMAKE_BUILD_TYPE=Release && cmake --build build -j 4
./build/bin/llama-server -hf unsloth/Qwen3.5-0.8B-GGUF:UD-Q4_K_XL --jinja \
  --chat-template-kwargs '{"enable_thinking":false}' --host 0.0.0.0 --port 8080 -c
# Either host, from the Mac:
QWEN_BASE_URL=http://127.0.0.1:8080/v1 python -m bench.route_tool_call --runs 5
QWEN_BASE_URL=http://team15-pi.local:8080/v1 python -m bench.route_tool_call --runs
```

> ⚠ **Truncated in source PDF:** three lines are cut off at the right page edge: the Mac `--chat-template-kwargs` line (`…--port 8080 -`), the Pi `--chat-template-kwargs` line (`…--port 8080 -c`), and the last benchmark line (`…--runs`).

If the GGUF tag is not found, list the repo’s files on Hugging Face and pick a Q4 quant; record the exact tag in `docs/evidence/qwen_host.md`. Fallback runtime: `ollama run qwen3.5:4b --think=false`. *(source: computingforgeeks)*

**Only external data point for the Pi:** a community llama.cpp run on a 2 GB Pi 5 measured Qwen2.5-0.5B Q4_0 at 33.84 tokens/s decode (2 threads) and 289.92 tokens/s prompt processing (4 threads) (llama.cpp discussion #30069). *(source: github)* A tool-schema prompt is roughly 1,000+ tokens, so even that tiny model spends seconds on prefill; a 4B model will be much slower. Apple’s Machine Learning Research note on MLX and the M5 reports “120GB/s for the M4” and that “TTFT is compute-bound, while generation is memory-bandwidth-bound,” so long tool-schema prompts cost prefill time. **Expected (assumption, to be measured): Mac hosts Qwen3.5-4B; the Pi hosts BLE and Hailo vision.**

**Decision rule:** a host qualifies if 5/5 runs produce a schema-valid `compute_route` call with no `<think>` and median end-to-end ≤ 5 s (our SYNTHETIC threshold). Prefer the Pi only if Qwen3.5-0.8B qualifies there (better deployability story); otherwise the Mac.

| Host / model | TTFT median | End-to-end median | Valid calls | Status |
|---|---|---|---|---|
| Mac M4 / Qwen3.5-4B Q4 | — | — | —/5 | MEASURED: not yet |
| Pi 5 CPU / Qwen3.5-0.8B Q4 | — | — | —/5 | MEASURED: not yet |

### 7.3 One shared tool interface

All clients call `POST {QWEN_BASE_URL}/chat/completions` with `tools=[...]` (OpenAI schema). Switching hosts = changing one environment variable. Tool execution never happens inside the model server: `agent/qwen_client.py` receives `tool_calls` → `agent/validator.py` → `agent/tools.py` → result appended as a `role:"tool"` message.

### 7.4 The five tools

| Tool | Inputs | Output | Timeout | Fallback |
|---|---|---|---|---|
| `inspect_sector` | `sector` (A–Z) | coverage state, canopy tag, last visit time, open candidates | 1 s | read store directly; show “unknown” |
| `get_recent_observations` | `since_s` (≤ 3600), optional `sector` | list of observations (id, time, kind, how, confidence, source_mode) | 1 s | last 20 from store |
| `request_view` | `target` (sector or track id), `sensor` (rgb / ble / thermal) | tasking ticket id, status `QUEUED_SIM` or `PENDING_STAFF_PILOT` | 5 s (sim ack); 120 s (staff ack) | mark “view not obtained”; keep candidate unconfirmed |
| `assign_scout` | `drone_id` (D1–D3), `sector` | ticket; sim reassigns sweep; LIVE-HW shows request to staff pilot | 2 s | deterministic coordinator assignment |
| `compute_route` | `from_node`, `to_node` | `RouteResult` (status, path, length_m, reason, route_version) | 1 s | planner runs automatically on every track change anyway |

Example schema (`agent/schemas/compute_route.json`):

```json
{"type":"function","function":{"name":"compute_route",
 "description":"Shortest KNOWN walkable route on the trail graph. Does not certify
 "parameters":{"type":"object","additionalProperties":false,
  "properties":{"from_node":{"type":"string","pattern":"^[A-Z]$"},
                "to_node":{"type":"string","pattern":"^[A-Z]$"}},
  "required":["from_node","to_node"]}}}
```

> ⚠ **Truncated in source PDF:** the `"description"` string is cut off after `Does not certify`, so this block is not valid JSON as printed.

### 7.5 First successful tool-call example (expected shape — replace with captured output)

Request (abridged): system “You coordinate a search. Use tools; never invent distances.” + user “Responder is at C. Track T1 was confirmed at K. What route?” + `tools=[compute_route, ...]`. Expected assistant message:

```json
{"role":"assistant","content":null,"tool_calls":[{"id":"call_1","type":"function",
 "function":{"name":"compute_route","arguments":"{\"from_node\":\"C\",\"to_node\":\
```

> ⚠ **Truncated in source PDF:** the second line is cut off after `\"to_node\":\`.

Validator: `ACCEPT compute_route(C,K)`. Tool result: `{"status":"OK","path":["C","J","K"],"length_m":20,"route_version":2}`. Final model text must quote the tool result, e.g., “Route v2: C→J→K, 20 m (SYNTHETIC distances).”

### 7.6 G-to-K test with an out-of-order sighting through the tool interface

`python -m agent.run_fixture --fixture fixtures/synthetic_g_to_k.jsonl --qwen $QWEN_BASE_URL` Pass criteria: after step 4 Qwen may call `get_recent_observations` and `request_view(target="T1", sensor="rgb")` but the store still shows K unresolved; after step 5 the late G packet is in history and no tool call can move T1; after step 6 a `compute_route(C,K)` result matches 20 m. Repeat with `--no-qwen`: identical dashboard state (deterministic coordinator).

### 7.7 Validator rules (owner: Teammate C)

Reject and log if: tool not in whitelist; arguments fail schema; sector not A–Z or outside the approved demo area; drone not `AVAILABLE`; sensor not checked out (thermal default UNAVAILABLE); any field resembling motion (lat/lon, x/y, velocity, altitude, yaw) — our tools carry none; more than 5 tool calls per 10 s; `assign_scout` on a LIVE-HW aircraft without the staff-pilot flag. **Drone movement stays within the approved flight controller or simulator.**

### 7.8 What still works if Qwen is unavailable

Everything except natural-language suggestions: ingest, dedup, tracking, review prompts, automatic rerouting, coverage ledger, and the deterministic coordinator (assign each idle scout to its lowest-coverage unvisited cell; for a new unconfirmed candidate, request an RGB view from the nearest available scout). Qwen calls time out after 8 s; the dashboard shows “Qwen offline — deterministic coordinator active.”

### 7.9 Mission memory and RAG

Structured store = SQLite (`observations`, `tracks`, `track_history`, `routes` versioned, `scouts`, `coverage`, `operator_decisions`, `tool_audit`, `notes`). **RAG assessment:** with < 1,000 notes/frames in 18 hours, exact queries by time/sector/track plus SQLite FTS5 over `notes.text` answer every question we need; vector RAG adds an embedding model, indexing and failure modes for little gain. Fallback = FTS5 + `ORDER BY obs_time DESC`.

---

## 8. GitHub workflow and CI

### 8.1 Rules

- One branch per terminal; commit every passing test; push at least hourly; open a **draft PR immediately** after the first commit; mark ready when acceptance passes; one reviewer from a different terminal; squash-merge.
- `CODEOWNERS` (owned by T2), e.g.:

```text
/perception/ /planner/ /sim/                 @<mubashir-handle>
/contracts/ /fixtures/ /core/ /dashboard/ /.github/ /tests/e2e/ /CODEOWNERS  @<integration-handle>
/agent/ /bench/                              @<qwen-handle>
/deploy/ /ble/ /hardware/ /docs/evidence/    @<pi-handle>
```

### 8.2 PR #1 (Integration owner; < 100 lines; merge within 30 minutes)

Contents: directory skeleton with `__init__.py`; `contracts/observation.schema.json`; the three fixtures; `requirements.txt` (fastapi, uvicorn, jsonschema, pytest, networkx); `tests/e2e/test_fixture_schema.py` (every fixture line validates); `.github/workflows/ci.yml`; `.github/pull_request_template.md`.

```bash
git switch -c pr1-skeleton
git add . && git commit -m "PR1: skeleton, observation contract, synthetic G-to-K f
git push -u origin pr1-skeleton
gh pr create --draft --title "PR1: skeleton + contract + fixture + CI" --body "Synt
gh run watch        # see Actions run
gh pr ready && gh pr merge --squash
```

> ⚠ **Truncated in source PDF:** the `git commit -m` message (`…synthetic G-to-K f`) and the `gh pr create --body` text (`…"Synt`) are cut off, so both quotes are left open as printed.

Observation contract (required fields): `obs_id` (`{drone}-{boot}-{seq:06d}`), `drone_id`, `boot_id`, `seq`, `source_mode` (SIMULATED | RECORDED-IMAGERY | LIVE-HW), `platform` (SIM | BENCH | AIRCRAFT), `sensor` (rgb | ble | thermal), `kind` (PERSON_VISUAL | BLE_ENROLLED_BEACON | THERMAL_WARM_OBJECT), `obs_time`, `rx_time`, `stale_after_s`, `how` (SECTOR_ONLY | BEARING_ONLY | GROUND_PLANE | MULTI_VIEW), `cell`, optional `xy_m`, `ce_m`, `bearing_deg`, `confidence`, `evidence` (frame_ref, bbox), `replay_of` (original source + capture time). Pattern borrowed from MITRE Cursor-on-Target events (time/start/stale/how/ce).

### 8.3 CI workflow (`.github/workflows/ci.yml`)

```yaml
name: ci
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.11" }
      - run: pip install -r requirements.txt
      - run: pytest -q
```

(Action major versions are the commonly used ones; bump if GitHub warns of deprecation.)

**Behaviors CI must exercise:** shortest valid route (A→G 60, C→K 20); blocked edge (J–K → 22) and unreachable (Y → NO_KNOWN_ROUTE); stale G packet after K does not move the marker; ambiguous K enters review instead of moving T1; two-people split; replay/recorded events never counted as live; duplicate obs_id idempotent; validator rejects motion arguments.

**What CI does / does not do:** it runs our Python tests on a GitHub-hosted Ubuntu runner on every push and PR, using synthetic fixtures. It does **not** fly anything, touch a sensor, deploy to the Pi, or run Qwen. Pi deployment is manual: `rsync -av --exclude .venv ./ $PI_USER@$PI_HOST:Team-15/`.

### 8.4 PR template (`.github/pull_request_template.md`)

```markdown
## What changed
## Tests run (paste pytest summary)
## Data mode: [ ] SIMULATED  [ ] RECORDED-IMAGERY  [ ] LIVE-HW (bench)  [ ] LIVE-HW (airborne)
## Human-observed evidence (REQUIRED for any physical flight or sensor claim)
- Observer name:
- Local time observed:
- Photo/video link:
- Equipment (model + serial/label, or "UNCONFIRMED"):
- Staff pilot (for any flight):
```

---

## 9. Research decisions 1–6

Tags: **[VERIFIED]** from a named primary source; **[ASSUMPTION]** model-dependent; **[TEST]** proposed; **[MEASURED]** results (none yet).

### 9.1 Aircraft and deployment

| Capability | Hardware | SDK | Permissions | Staffing | Tests |
|---|---|---|---|---|---|
| A. Physical mother aircraft carrying and releasing scouts | A carrier with payload margin, a release mechanism, scouts able to start mid-air | None off the shelf for microdrones | Staff, venue, and FAA rules for outdoor flight | Staff pilot(s) | Release, recovery, safety — a **research project**, not a weekend build |
| B. Three independently launched scouts, one controller | 3 programmable drones (EXAMPLE: Tello EDU, Crazyflie 2.1, PX4 dev kit) | Vendor SDK | Staff-only, daytime-only (brief); venue rules indoors | Staff pilot + our operator | Hover, video into our software, position source |
| C. Three simulated scouts | Laptop | Our `sim/` | None | Us | CI + fixtures |

**Commit today: C**, plus RECORDED-IMAGERY and LIVE-HW (bench) camera. Path to B: our tasking tickets (`assign_scout`, `request_view`) are already the interface a staff pilot or an approved controller fulfils.

EXAMPLE capability checks (run only on checked-out hardware, with staff):

- **Tello EDU (EXAMPLE)** [VERIFIED, Tello SDK 2.0 User Guide]: Wi-Fi UDP; send `command` to 192.168.10.1:8889; state on UDP 8890; `streamon` sends video to UDP 11111; mission pads via `mon`/`mdirection`. *(source: ryzerobotics)* Test: `command` → `ok`, state packets received, one decoded frame on our laptop **without takeoff**. Ryze’s Tello User Manual v1.2 gives a maximum flight time of “approximately 13 minutes” in windless conditions (base Tello; confirm for the unit issued). A community ROS driver notes Tello auto-lands if no command arrives for 15 s. *(source: github)*
- **Crazyflie 2.1 (EXAMPLE)** [VERIFIED, Bitcraze docs]: Flow deck v2 detects flow and height (position hold); AI deck streams camera images over Wi-Fi (NanoCockpit, network `aideck-nanocockpit`); Bitcraze states AI-deck functionality is examples, not guaranteed. *(sources: bitcraze +2)* Test: cfclient connects, deck detected, image viewer receives frames.
- **PX4/MAVSDK dev kit (EXAMPLE)**: not researched in this session — UNVERIFIED; test = telemetry and a position source visible over MAVLink without arming.

FAA [VERIFIED, 14 CFR Part 107 / FAA AIM]: §107.29 daylight operation (civil twilight only with anti-collision lighting); §107.39 limits operation over people; recreational flyers need TRUST. *(sources: faa, avsport)* Indoor flight: venue rules apply; confirm with Code Metal staff. Downtown Boston airspace authorization for outdoor flight: ask staff, do not assume.

### 9.2 Forest search and camera localization

- **Box → location.** [VERIFIED, OpenCV calib3d docs] `cv2.calibrateCamera` estimates intrinsics K and distortion; `cv2.solvePnP` gives pose from known 3D-2D points. *(sources: github +3)* With K, pose (R, C) and a flat ground plane z=0: undistort the bbox bottom-centre (u,v), ray `d = Rᵀ K⁻¹ [u v 1]ᵀ`, `t = −C_z / d_z`, ground point `P = C + t·d`. The drone’s position is not the person’s position.
- **Error propagation (computed):** ground range r = h / tan θ (θ = depression angle), so dr = (h / sin²θ)·dθ. At h = 30 m, θ = 30°, a 1° tilt error moves the point about 2.1 m; at θ = 10° about 17 m. Range scales linearly with altitude error. Slopes break the flat-ground assumption.
- **Footprint/GSD:** nadir footprint width = 2h·tan(HFOV/2) (e.g., SYNTHETIC HFOV 70°, h 10 m → 14.0 m); GSD = sensor width × h / (focal length × image width).
- **Canopy** [VERIFIED]: the POP UAV thermal dataset (Scientific Data 12, art. 300, 2025) reports detection precision “was not attenuated until the occlusion rate exceeded 70%”, while at 90% occlusion a quarter of images had no detection and average performance approached chance; Rietz et al. (Transboundary and Emerging Diseases 2023, Bavarian Forest National Park) found “for a canopy openness of <29.3%, the probability of carcass detection was <25%” (meadow 97% vs. deciduous forest 24%); airborne optical sectioning (Kurmi, Schedl & Bimber, Scientific Reports 12, 3804, 2022) integrates many views to allow “optical slicing through dense occlusion (caused by leaves, branches, and bushes)”. **An overflight is not a search.**
- **Defensible outputs:** GROUND_PLANE only with calibrated K, measured pose and roughly flat visible ground; MULTI_VIEW triangulation needs ≥ 2 posed views with a real baseline; BEARING_ONLY (“direction known, range unknown”) when the camera’s heading is known but altitude/terrain is not; SECTOR_ONLY (“candidate in sector G”) when only the assigned cell is known — **our default in simulation and for the bench camera**. No GPS → no absolute coordinates; everything is in the local sector grid.
- **“Covered” definition:** cell = COVERED-GOOD if ≥ 80% (SYNTHETIC) of its area lay inside the footprint of at least one frame with usable visibility (canopy fraction ≤ 0.3 SYNTHETIC, image not blurred); COVERED-OBSTRUCTED if overflown but visibility below threshold (re-task with another view or sensor); UNOBSERVED otherwise. Each ledger row stores drone, time, frame ref, visibility score.
- **Room-scale test [TEST]:** tape a 4 × 4 grid of 1 m squares on the floor, label cells, tape-measure each mark (ground truth by a second person); mount the camera on a tripod at measured height; recover pose with an AprilTag/chessboard + `solvePnP`; *(sources: arxiv, pythonpool)* a volunteer stands on 10 marked points; log predicted vs. measured; report mean and max error and cell accuracy. Repeat with the camera tilted 10° more to show sensitivity.
- **Replay rule:** RECORDED-IMAGERY frames carry original capture time and source ID in `replay_of`; ingest never rewrites `obs_time` to now.

### 9.3 iPhone/Bluetooth feasibility (60-minute time box)

- [VERIFIED, Apple `startAdvertising(_:)` via Apple DTS and the Core Bluetooth Programming Guide] An iOS app acting as peripheral may advertise only `CBAdvertisementDataLocalNameKey` and `CBAdvertisementDataServiceUUIDsKey`; foreground gets 28 bytes plus 10 bytes of scan response for the local name; UUIDs that don’t fit go to an “overflow” area discoverable “only by an iOS device explicitly scanning for them”; “While your app is in the background, the local name isn’t advertised and all service UUIDs are in the overflow area.” *(sources: apple, apple)* Apple DTS: background advertising needs `UIBackgroundModes` = `bluetooth-peripheral`; advertising frequency may decrease; a non-Apple central cannot decode the overflow area. *(source: apple)*
- **Roles:** iPhone (consenting volunteer, our test app) **advertises** one 128-bit service UUID; the Pi 5 (BlueZ + `bleak.BleakScanner` with `detection_callback`, reading `service_uuids` and `rssi`) **scans**, or the Mac as backup receiver. *(sources: readthedocs, readthedocs)* Do not key on MAC addresses (iPhones randomize them) or assume arbitrary phones advertise anything usable.
- **Predicted (from docs, to be measured):** foreground = visible to Pi; background = not identifiable by Pi; locked = treat as background.
- **Experiment:** (1) 0–20 min build/run app; (2) 20–40 min foreground at 1, 5, 10 m (SYNTHETIC distances, tape-measured), 60 s each, record hits/min and RSSI; (3) 40–55 min background and locked; (4) 55–60 min write results. **Pass:** our UUID heard ≥ 1/min at 5 m in foreground.
- **Semantics:** an observation says “our enrolled beacon was heard by receiver R at time t, RSSI x” — never “a person is here”, and RSSI never becomes a distance.
- **Fallback:** if not passing by minute 60, flash a Seeed board (if BLE-capable) to advertise the same UUID, labelled **STAND-IN BEACON** on screen and in logs.

| Condition | Heard by Pi? | Hits/min | RSSI range | Observer / time |
|---|---|---|---|---|
| Foreground 1 m | MEASURED: not yet | | | |
| Foreground 5 m | | | | |
| Background | | | | |
| Locked | | | | |

### 9.4 Two different routing problems

- **Aerial coverage plan** (sim/scan.py): each scout sweeps its sector cells in lawnmower order; the ledger decides re-visits; aerial results never add or remove walking edges.
- **Walking route** (planner/): explicit graph of known trails only. Dijkstra vs A\*: with an admissible heuristic A\* returns the same optimal path; NetworkX’s A\* with no heuristic is literally h=0, i.e., Dijkstra (NetworkX docs). *(sources: reintech, networkx)* For 26 nodes, **Dijkstra (simplest)**.
- Blocked edge: removed with timestamp and source (responder report); unknown terrain stays unknown (no edge); unreachable → red banner “NO KNOWN ROUTE to Y: no known walkable connection. Aerial view does not certify passability.” Destination change → new route version with explanation text. Responder partway → re-plan from the last reported node (C).

### 9.5 Qwen tools and mission memory

See §7.3–§7.9. Division of labor: the planner computes distances; sensor code supplies observations; the staff pilot or approved controller moves aircraft; Qwen only chooses among validated tools.

### 9.6 Multiple scouts and moving people

- **Clocks:** the Mac is time authority; each scout stamps `boot_id` + monotonic time + `seq`; base estimates offset by ping exchange (offset = ((t1−t0)+(t2−t3))/2) and converts to mission time; `rx_time` always recorded.
- **Frames:** sector grid (local); optional metres within a cell; no global coordinates without a position source.
- **Dedup:** exact `obs_id` → ignore; same drone + same cell + within 60 s (SYNTHETIC) → attach to existing track.
- **Late packets:** inserted at `obs_time`; may add history and change feasibility, never supersede a newer observation.
- **Link loss:** scout queues locally and replays with original times, `delivery=replayed_after_link_loss`.
- **Stale:** TTL by sensor (SYNTHETIC: RGB 300 s, BLE 60 s, thermal 120 s); stale tracks greyed with age; never silently deleted.
- **Linking evidence:** kinematic feasibility (gate) is necessary, not sufficient; auto-link only with an independent identity cue (same enrolled BLE ID; operator confirmation); otherwise review. Impossible kinematics → automatic split. Counting is per track.

---

## 10. Plan to Sunday 12:00

Assumes H+0 = Saturday 16:30; shift clock times if you start later.

| H+ | Clock | Milestone |
|---|---|---|
| 0–0.5 | 16:30–17:00 | Invite accepted, PR #1 merged, 4 terminals running |
| 0.5–2 | 17:00–18:30 | Planner tests green; store/tracker skeleton; validator schemas; Pi on SSH |
| 2 | 18:30 | Contracts frozen |
| 4 | 20:30 | **Checkpoint 1: synthetic G→K end-to-end on dashboard** |
| 4–5 | 20:30–21:30 | BLE experiment (hard stop 21:30); Qwen host benchmark; live camera on Mac |
| 6 | 22:30 | **Checkpoint 2:** Qwen tool loop through validator; live bench camera candidate |
| 6–9 | 22:30–01:30 | Hailo detection on Pi; two-people case; metrics harness; hardware checkout decision |
| 9–13 | 01:30–05:30 | Sleep in pairs; hardening; recorded imagery ingest |
| 13–15 | 05:30–07:30 | Baseline runs; demo rehearsal |
| 15–17 | 07:30–09:30 | Optional staff-flown, daylight capability test (only if staff + aircraft available) |
| 17 | 09:30 | Feature freeze |
| 18 | 10:30 | Three timed rehearsals; record backup video |
| 19 | 11:30 | Submit; 12:00 hard cutoff |

**Cut order (first to go):** mother-ship concept → live aircraft → thermal → BLE → Qwen → multi-person.

**Three-minute judge-controlled demo:** (0:00) legend and architecture; (0:20) judge picks the sector hiding the volunteer in the simulator, or steps in front of the bench camera; (0:50) candidate + route A→G appears; (1:20) judge moves responder to C and triggers the D2 sighting at K → review prompt → judge confirms → route C→K with explanation; (2:00) judge injects the stale G packet → history only; (2:20) judge blocks J–K → reroute 22 m; blocks to Y → NO KNOWN ROUTE; (2:45) kill Qwen → deterministic coordinator continues.

**Baseline:** a teammate reads the raw observation JSONL and routes by hand on a printed graph. **Metrics:** time to first actionable report (obs_time → route on screen); sector/location error (room test); route correctness vs. brute force; update latency (rx → dashboard); false detections per minute (empty-scene bench test); identity switches (track reassignment without confirmation).

**What invalidates the main claim:** any route differing from brute force on a fixture; a late packet moving a marker; a replay counted as live; an identity switch without operator confirmation; no improvement over the baseline in time to actionable report; any hardware claim without human-observed evidence.

---

## 11. Closing sentences (repeat these)

- **Hardware in hand:** “We show a live camera detecting a real person on the bench, a Pi on our network, and — if the foreground test passes — our enrolled BLE beacon being heard.”
- **Depends on checkout:** “Airborne imagery, thermal and any real scout flight depend on checked-out hardware and a Code Metal staff pilot in daylight.”
- **Simulation:** “The three scouts, their sectors, the forest grid, the trail distances and the G-to-K scenario are simulated and labeled SIMULATED on screen.”
