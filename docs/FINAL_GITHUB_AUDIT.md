# Final GitHub completeness and evidence audit

**Date:** 2026-11-08 (10:30–11:35 ET). **Audited revision:** remote `main` at `912e1f7` (PR #21), fetched fresh; `fc755b9` (one video, pushed to `main` at 11:14 ET) was checked separately.
**Method:** GitHub API (`gh`), a fresh clone in a clean directory, the documented commands, gitleaks plus a
custom identifier scan of every blob on every remote branch, SHA-256 matching of every hash the registry cites,
and read-only inspection of the private evidence stores. No motor was activated, no firmware was flashed, no
history was rewritten and repository visibility was not changed.

## Summary table

| Category | Local artifacts | On remote main | External reference | Missing / private | Verified |
|---|---|---|---|---|---|
| Source code | main tree + 4 unmerged lines of work (below) + 2 private Git workspaces (Qwen 380 files, robotics 49) | 368 files: 159 `.py`, 5 `.js`, 5 `.html`, 3 `.ino`, 3 `.h`, 2 `.sh` | — | PR #20 code (on its branch only); Qwen training, RAG and eval code (private, no remote) | fresh clone runs; firmware on `main` **does not compile**, PR #20 firmware compiles |
| AI models | ckpt-0088 + backups (47 files) | docs and loading recipe only (no weights, by design) | Hugging Face adapter, revision `21013d45`, Apache-2.0 | base weights (official Qwen repo) | adapter SHA-256 `a76f8371…ba2b` identical on HF, local and in session logs; LoRA activity re-measured |
| Datasets | Qwen SFT and eval sets, RAG corpus (private) | manifests, counts and hashes in [DATASET_INVENTORY](experiments/DATASET_INVENTORY.md) | COCO, Co-GLANCE (CC BY 4.0), SAREnv | training data and RAG corpus are **not publishable** (mixed licences) | inventory consistent with registry |
| Experiments | 5 private stores, 844 files | [registry](experiments/EXPERIMENT_REGISTRY.md): 157 rows (141 executed, 12 not run, 4 duplicates); 45 reports, 0 broken links | — | SIM-08 evidence was audit scratch only; post-`d1b607a` runs listed below | 52 rows' cited SHA-256 values match files; 1 typo fixed (SIM-06) |
| Benchmarks | full rerun output (scratch) | 1,540-run CSV, summary and metadata in `demo/evidence/` | — | — | **rerun from a fresh clone: 1,540/1,540 runs, 0 metric differences** |
| Hardware logs | identification record, firmware backup, 13 AI-rover sessions, 14 advice records | redacted summaries in [HARDWARE_STATUS](../demo/HARDWARE_STATUS.md) | — | flash log, DISARMED photos, STOP-ack output: **user-reported, not archived** | backup SHA-256 re-verified; sessions are SIMULATED MOTOR OUTPUT |
| Videos | 6 files (1 in repo + 5 on the presenter's desktop) | 1: `demo/videos/Team15_Dual_Robot_Rescue_Demo.mp4` | — | 4 desktop recordings must stay private; 1 is publishable | repo video SHA-256 and playback verified; GitHub copy byte-identical |
| Documentation | — | 123 Markdown files | — | — | docs check: 0 issues |
| Tests and CI | — | 6 workflows, all green on `912e1f7` | GitHub Actions | `team15_starter/tests` is in no workflow | fresh-machine run matches CI exactly |

## 1. GitHub state

* Remote `main` = local `main` after fetch = `912e1f7`. The repository is **PRIVATE**: anonymous requests for the
  repository page and the raw video return **404**. Four collaborators, all admin. The plan does not allow
  branch protection, so "required checks" are not enforced by GitHub.
* PRs: #1–#5, #7, #8, #10–#19 and #21 merged. **#20 is CLOSED, not merged** (draft, closed 2026-11-08 15:27 UTC,
  no comment); its branch `feature/mac-pi-rover-integration` is preserved at `0d7a11d`. **#6 is OPEN**,
  conflicting with `main`, with 2 failing docs checks.
* Work absent from `main`:

| Where | Commits ahead of `main` | What | Status |
|---|---|---|---|
| PR #20 branch (`0d7a11d`) | 10 | Pi-hosted safety stack (pi_host, HMAC-signed link, remote client, camera gate), Qwen + LoRA rover advisor, AI-rover session runner, wheels-lifted bench mode, approval-gated flash and restore scripts, **compiling firmware**, live `/demo` page | 638 passed, 2 skipped (re-run); docs check fails on 2 private-address lines and 1 dangling path. **Not merged: unverified hardware code** |
| PR #6 (`culubo/sensor-id-specs`, teammates) | 68 | Crazyflie scanner firmware, BLE-ID docs (147 files), mission control, iOS beacon app, evidence | 356 files absent from `main`; merge conflicts; owner action |
| `aurora-integration` (teammates, no PR) | 61 | same line as PR #6 plus 5 newer commits (Crazyflie sim, keyboard pilot, Bluetooth fixes) | still being pushed during the audit |
| `GavinPrescott-sarsim` | 1 | `sar_sim.zip` + `team_update.md` upload | superseded by PR #17 |
| local `test/camera-live-countdown` | 11 (never pushed) | consent-gated live camera runner, evidence import, 3 camera reports (2,594 lines) | **now on GitHub** as `archive/camera-live-countdown` (`882e9a4`): one snapshot commit, 2 lines redacted; 392 passed, 7 skipped |

Three other local-only branches and a stale scratch worktree were checked file by file: their content is
already on `main`, so nothing was lost.

## 2. Source code map (all on `main` unless marked)

| Subsystem | Files | Introduced by | Type |
|---|---|---|---|
| Dual-agent rescue simulation, shared map, coordination | `simulation/dual_rescue/` | PR #19 `2e9c7ca` | simulation |
| 3D Three.js twin | `dashboard/static/rescue/` (Three.js r160 vendored with its MIT licence), `dashboard/rescue_api.py` | PR #19 | simulation UI |
| Drone search and planning | `team15_starter/` (MCTS, fleet, SAREnv bench), `simulation/dual_rescue/aerial.py`, `TEAM15_DRONE_SEARCH_BUILD.md` | PR #17 `d1b607a`, PR #1 | simulation; drone hardware work is on PR #6 |
| Rover navigation, route planning, replanning | `rover/navigator.py`, `rover/simrun.py`, `planner/` | PR #8 `f55833a`, PR #2 | simulation-tested |
| SafetySupervisor | `rover/motion.py` | PR #8; fail-closed fixes PR #14 | production logic, mocked hardware |
| Camera obstacle mapping | `camera_mapping/` | PR #16 `0c9acc3` | advisory |
| Pi camera + Faster R-CNN | `perception/pi_source.py`, `perception/live_camera.py`, `perception/detectors.py` | PR #3 `baa1804` | real hardware (bench) |
| Qwen advisory contract and guarded client | `qwen_advisory/` | PR #12 `205dbc4` | stdlib client with fallback |
| Qwen + LoRA rover advisor | `scripts/qwen_rover_advisor.py` (from PR #20, byte-identical); the session runner stays on the PR #20 branch | PR #22 follow-up | experimental, advisory only |
| Qwen training, RAG, evaluation | private Qwen workspace (Git, no remote, HEAD `1dc877a`) | — | **not on GitHub** (disclosed in [10 RAG](10_RAG_PIPELINE.md)) |
| Pi-side authenticated control service | pi_host, link, remote | **PR #20 branch only** | experimental |
| StickC firmware, serial bridge, watchdog, STOP | `firmware/stickc_roverc_bridge/`, `rover/bridge.py`, `docs/rover/BRIDGE_PROTOCOL.md` | PR #15 `89a0e81`; firmware replaced by the PR #20 version (`0d7a11d`, compiles, StickC Plus SE settings; no protocol change) | firmware compiles; hardware run user-reported |
| Bench testing | `docs/rover/BENCH_RUNBOOK.md`; bench mode and Pi scripts on **PR #20 only** | PR #8 | gated |
| Sensors | `ranging/` (Grove), `lidar/` (RPLIDAR C1) | PR #7, PR #11 | simulation-tested; hardware gates closed |
| Dashboard and API | `dashboard/` | PR #5, #16, #19 | production |
| Tests, benchmarks, docs checks | 33 test files, `simulation/dual_rescue/benchmark.py`, `demo/record_demo.py`, `scripts/check_docs.py` | various | — |

## 3. Experiments and evidence

* Registry: 157 rows, 45 linked reports, all present. **52 rows** cite SHA-256 values that match a file in the
  private stores or in the repo. 99 rows cite console logs, PRs or CI runs (no hash). SIM-08's file was audit
  scratch and no longer exists.
* **Corrected in this PR:** SIM-06 hash abbreviation (`…0b6c` → `…0e6c`; the report's full hash was right);
  the false-CLEAR statement in [dual_rescue/BENCHMARKS](dual_rescue/BENCHMARKS.md) (the 16 reports are in the
  independent-mode baseline, 0 in the system under test, and the blind-camera fault produced 24, not 10).
* Experiments after the registry snapshot (`d1b607a`), with evidence:

| ID (audit) | Experiment | Result | Evidence | Label |
|---|---|---|---|---|
| A-SIM-1 | Dual-rescue benchmark at `953826b` | 1,540/1,540 runs; system under test 638/800 mission success, 799/800 correct outcome; **0 collisions, 0 unknown-corridor entries, 0 safety violations in all 1,540 runs**; 100/100 fault checks | `demo/evidence/dual_rescue_benchmark_runs_953826b.csv` (20fcb0d0…bd64) | SIMULATED |
| A-SIM-2 | Same benchmark re-run by this audit from a fresh clone of `912e1f7` (simulation code unchanged since `953826b`) | all 1,540 rows identical except revision and wall time; summary tables identical | this audit | SIMULATED |
| A-SIM-3 | 3D render performance | about 60 fps from 1080p to 2160p (M4 Pro) | `demo/evidence/render_perf_m4pro.json` (5537e19f…80e3) | SIMULATED |
| A-ROV-1 | StickC detection, esptool identification and full flash backup (2026-11-08 09:42 ET) | ESP32-PICO-D4, 4 MB; "likely StickC Plus, not confirmed"; backup SHA-256 `bc1366ef…bf95d`, re-hashed here: match | private identification record | REAL HARDWARE (read-only) |
| A-ROV-2 | Bridge firmware flashed, hash-verified, DISARMED shown, STOP acknowledged; rear label "M5StickC Plus SE" | **USER-REPORTED. Not archived**: no log or photo in any store; the Pi was unreachable | — | UNVERIFIED |
| A-BRG-1 | Firmware compile check (arduino-cli 1.5.1, m5stack:esp32 3.3.10, StickC Plus) | `main`: **compile error** at line 46; PR #20 `0d7a11d`: compiles (518,671 bytes) | this audit | build check |
| A-QWN-1 | Qwen + LoRA rover advisor, 13 sessions (09:24–10:01 ET) | 14 advice records, all `adapter_active_verified: true`; 12 model outputs (all REQUEST_OPERATOR_REVIEW), 2 errors → STOP | private session logs | REAL camera + MOCKED motors |
| A-QWN-2 | Independent LoRA activity check from public artifacts (base `15852e8c`, adapter `21013d45`) | 150 LoRA modules; max next-token logit difference **15.03**; with LoRA the output follows the step schema, with the adapter disabled it does not | this audit | SYNTHETIC prompt |
| A-CI-1 | Fresh-clone test run of `912e1f7`, private stores hidden | **557 passed, 8 skipped, 0 failed** (= CI); lidar 124, ranging 126, qwen_advisory 23, team15_starter 5; torch-gated tests pass after `pip install torch torchvision` | this audit | MOCKED / SIMULATED |

## 4. AI models

* Adapter: [huggingface.co/MOHDMUBASHIR/team15-qwen3.5-2b-rescue-mission-lora](https://huggingface.co/MOHDMUBASHIR/team15-qwen3.5-2b-rescue-mission-lora),
  public, not gated, revision `21013d45`, Apache-2.0, with LICENSE, NOTICE, SHA256SUMS, prompts and a loading script.
  The README recipe loads it as written.
* Configurations a reviewer can distinguish: **base Qwen** (A-QWN-2, adapter disabled), **base + RAG** (the live
  demo service, Ollama), **Qwen + LoRA** (A-QWN-2), **Qwen + LoRA + RAG** (218/230 frozen benchmark, QWN-017; the
  PR #20 advisor). Only the first three run from public inputs: the RAG corpus is private.
* Training and evaluation cannot be reproduced from GitHub: the code is in a private workspace, and the data
  cannot be published.

## 5. Videos

| Video | Where | Verified | Publishable? |
|---|---|---|---|
| 3D dual-robot rescue simulation (74.47 s, 1920×1080, H.264 High, 30 fps; SHA-256 `f9f446ea…52da`) | `demo/videos/`, README "Watch the Demo" | hash, codec, frames sampled: simulation UI only, "SIMULATION — NO PHYSICAL ROBOT MOVEMENT" banner | yes |
| Drone fleet-search simulation (104 s, 1912×978; SHA-256 `af476648…97b0`), added to `main` by `fc755b9` after the audit started | `demo/videos/` | frames sampled: simulated fleet UI over map tiles; audio near-silent. Its arrival broke `test_no_photos_tracked_in_git` on `main`; fixed by allow-listing it as synthetic media | yes |
| Fleet-search simulation clip (9.1 s) | presenter's desktop | simulated heat map only | yes (not uploaded) |
| Two Qwen + LoRA rover demos and two "live Pi camera + mock motors" sessions, including the final 10:00 ET one (27 s each) | presenter's desktop | the live camera panel shows a room and laptop screens, and the side panel shows a device serial path and a local home path | **no**: keep private |

## 6. Privacy, security and licences

* Current `main` tree: clean. gitleaks over every commit on every remote branch: 2 findings, both false positives
  on teammates' branches (a dummy test key and a file-hash manifest). The custom scan found no MAC address,
  device serial or real private address on `main`. One personal mailbox reference was removed in this PR.
* **History is not clean.** `main`'s history (before PR #18) and 12 stale merged branches contain the Pi's private
  network address, SSH key names, Wi-Fi names and a local home path. The PR #20 branch contains a device serial
  and MAC. The teammates' BLE logs contain device MACs and home paths. **Do not make this repository public as
  it is.** Use a sanitized public mirror (the current tree, no history) instead of rewriting this history.
* No real camera frame has ever been committed on any branch. Real frames stay private (consent not recorded).
* Licences: repository Apache-2.0; Three.js MIT (vendored with its licence); Qwen base Apache-2.0 (not
  redistributed); Co-GLANCE CC BY 4.0 (not redistributed); RAG corpus mixed licences (not publishable).

## 7. Remaining limitations

1. No wheel has turned. Battery voltage is not measured. The watchdog is verified only in the model.
2. Flash, DISARMED and STOP-acknowledgement evidence exists only as user reports. Archive the terminal output and
   photos in the private store, and copy the Pi's flash log once the Pi is reachable.
3. The firmware source on `main` does not compile. The running firmware's source is on the closed PR #20 branch.
4. PR #20, PR #6 and `aurora-integration` are unmerged. Merging needs owner review and hardware sign-off.
5. Docs written at `d1b607a` still say "controller NOT DETECTED" (docs 00, 13, 17, 25, 26). [HARDWARE_STATUS](../demo/HARDWARE_STATUS.md) is the current record.
6. `team15_starter/tests` is in no CI workflow. 6 dashboard tests need private robotics fixtures.

## 8. Readiness

The repository is complete and reproducible for the **simulation, dashboard, benchmark and inference** claims,
and honest about hardware. It is **not accessible to judges** while it is private: judges need collaborator
access or a sanitized public mirror, and both need the owner's approval.
