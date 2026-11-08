# Dataset inventory

This inventory lists every dataset, fixture set, evidence store and third-party model that a Team-15 experiment used. It is merged and de-duplicated from the six domain audits. For each entry it records where the data came from, whether it is real or synthetic, how large it is, how it is labelled, where it is stored, and **whether it may be published**. Nothing in this page copies raw data: no frames, no training rows, no prompts, no log excerpts. Counts were taken by the domain auditors on 2026-11-08 by parsing the files.

**Status:** Reference index (audit of 2026-11-08, repository at `d1b607a`).

**Related:** [Experiment registry](EXPERIMENT_REGISTRY.md) · [Experiment summary](EXPERIMENT_SUMMARY.md) · [Benchmark results](BENCHMARK_RESULTS.md) · [09 LoRA training](../09_LORA_TRAINING.md) · [10 RAG pipeline](../10_RAG_PIPELINE.md) · [04 Camera perception](../04_CAMERA_PERCEPTION.md) · [18 Simulation](../18_SIMULATION.md)

---

## 1. Read this first: publication rules

| Rule | Why |
|---|---|
| **No camera frame or evidence image may be published.** This covers the Mac bench runs, the Pi validation frames, the orientation-check frames and the Pi live-test frames. | They show consenting teammates (consent scope: capture, local display, storage; `public_sharing: false`) and, in the Mac bench runs, **non-consenting bystanders** and reflections of people. |
| **No Qwen training, validation or test data may be published.** | The prompts embed chunks of a private RAG corpus whose sources carry mixed licences, some non-commercial or no-derivatives. Every dataset card says human review is still PENDING. |
| **Evidence logs must be redacted before sharing.** | Some Pi-side logs contain network addresses, local paths, a hostname or a personal handle. |
| **Third-party data and models keep their own licences.** | COCO, Co-GLANCE, SAREnv and Depth-Anything have their own terms. We do not redistribute any of them. |
| Repo fixtures (`fixtures/`, `lidar/fixtures/`, test code) are public with the repo. | They are synthetic or simulated and contain no personal data. |

Placeholders: `$TEAM15_EVIDENCE` (local camera and mapping evidence store), `$QWEN_WORKSPACE` (Qwen workspace, a separate private Git repository), `$ADAPTER_BACKUPS` (adapter backups, metadata only here), `$ROBOT_WORKSPACE` (robotics workspace). All of them are **private and not in Git**. "On the Pi" means a private folder on the Raspberry Pi, which was unreachable during this audit, so those files were not hashed.

## 2. Summary table

| ID | Dataset | Real / synthetic | N | Storage | Publishable? | Used by |
|---|---|---|---|---|---|---|
| [DS-CAM-01](#ds-cam-01-mac-bench-camera-runs) | Mac bench camera runs | Real | 15 runs, ≈7,100 frame-log lines | private | **No** | CAM-02…14, CAM-22 |
| [DS-CAM-02](#ds-cam-02-first-pi-validation-and-e2e-runs) | First Pi validation and e2e runs (includes the replay frame) | Real | 2 runs; 1 evidence frame | private | **No** | CAM-17, CAM-18, MAP-03…08, MAP-10 |
| [DS-CAM-03](#ds-cam-03-orientation-check) | Orientation check | Real | 1 frame + report | private | **No** (DO_NOT_TRAIN_OR_DISTRIBUTE) | CAM-20 |
| [DS-CAM-04](#ds-cam-04-pi-live-test-series) | Pi live test series | Real | 7 runs (675 frames) | private | **No** | CAM-23…29 |
| [DS-MAP-01](#ds-map-01-camera-mapping-state-logs) | Camera-mapping state logs | Real + recorded | 1,292 states (demo script) + 158 (run-1 recovered) | private | aggregates only | MAP-01, 02, 04…08, DSH-02 |
| [DS-QWN-01](#ds-qwn-01-v01-seed-and-v01-sft) | v0.1 seed / v0.1 SFT | Synthetic + public + bench metadata | 45 | private | No | QWN-009, v0.2 SFT |
| [DS-QWN-02](#ds-qwn-02-v01-frozen-eval) | v0.1 frozen eval | Synthetic + public | 46 | private | No | QWN-001 |
| [DS-QWN-03](#ds-qwn-03-co-glance-public-items) | Co-GLANCE public items | Real (public, CC BY 4.0) | 36 | private copy | Attribution only; we do not redistribute | QWN-001, v0.2 SFT |
| [DS-QWN-04](#ds-qwn-04-v02-ground-rescue-curriculum-and-frozen-v02-test) | v0.2 curriculum + frozen v0.2 test | Simulated | 1,012 tool steps (230 frozen) | private | No | QWN-008, 013…017, 026 |
| [DS-QWN-05](#ds-qwn-05-v02-sft-train-and-val) | v0.2 SFT train / validation | Simulated + synthetic + 7 public images + bench metadata | 707 rows (689 trained) / 111 | private | No | QWN-010…014 |
| [DS-QWN-06](#ds-qwn-06-v03-targeted-missions) | v0.3 targeted missions | Simulated | 1,048 steps | private | No | QWN-024, 025 |
| [DS-QWN-07](#ds-qwn-07-lidar-01-benchmark-sft-mixture-and-pilot-set) | lidar-0.1 benchmark / SFT mixture / pilot set | Simulated | 270 + 270; 1,932 / 297; 640 | private | No | QWN-022…026 |
| [DS-QWN-08](#ds-qwn-08-lidar-generalization-set) | LiDAR generalization set | Simulated | 44 | private | No | QWN-027 |
| [DS-QWN-09](#ds-qwn-09-delivery-01-frozen-delivery-test-delivery-sft) | delivery-0.1 / frozen delivery test / delivery SFT | Simulated + public | 290; 77; 310/23 | private | No | QWN-019…021, 030 |
| [DS-QWN-10](#ds-qwn-10-rag-corpus) | RAG corpus | Real documents (paraphrased) | 47 docs → 253 chunks | private | **No** (mixed licences) | every RAG configuration |
| [DS-SIM-01](#ds-sim-01-synthetic-trail-graph) | Synthetic trail graph | Synthetic | 26 nodes, 15 edges | public repo | Yes | PLN-01/02, SIM-01, DSH-03, CI |
| [DS-SIM-02](#ds-sim-02-rover-simulator-scenarios-ah) | Rover simulator scenarios A–H | Simulated | 8 | public repo | Yes | SIM-01a/b |
| [DS-SIM-03](#ds-sim-03-unit-test-fixtures-and-synthetic-frames) | Unit-test fixtures and synthetic frames | Synthetic / mocked | generated per test | public repo | Yes | CAM-30/31, MAP-11, ROV-01, BRG-01, DSH-03 |
| [DS-SIM-04](#ds-sim-04-lidar-scenario-fixtures) | LiDAR scenario fixtures | Simulated | 23 scenarios, 76 frames, 37,038 points | public repo | Yes | LDR-SIM-01…04, LDR-HW-01f |
| [DS-SIM-05](#ds-sim-05-run-time-simulator-streams-not-stored) | Run-time simulator streams (Grove sim, LiDAR mock bytes) | Simulated / mocked | generated | not stored | n/a | RNG-SIM-*, LDR-SIM-* |
| [DS-SIM-06](#ds-sim-06-robotics-workspace-simulated-fixtures) | Robotics-workspace simulated fixtures | Simulated | 3–4 files | private | No (private workspace) | 6 dashboard range-panel tests, CI-002 |
| [DS-SIM-07](#ds-sim-07-qwen_advisory-lidar-cases) | `qwen_advisory` LiDAR cases | Simulated | 8 | public repo | Yes | qwen_advisory tests |
| [DS-SIM-08](#ds-sim-08-drone-fleet-results) | Drone-fleet results | Simulated | 80 + 40 rows | public repo | Yes | SIM-02, 03 |
| [DS-SIM-09](#ds-sim-09-sarenv-benchmark-outputs) | SAREnv benchmark outputs | Simulated on external heatmaps | 360 rows per budget | public repo (results only) | Results yes; SAREnv data no | SIM-05, 06 |
| [DS-HW-01](#ds-hw-01-grove-real-diagnose-records) | Grove real diagnose records | Real | 2 × 50 pings | on the Pi | After redaction | RNG-HW-01/02, RNG-PF-08/09, RNG-SIM-04 |
| [DS-HW-02](#ds-hw-02-controller-detection-and-lidar-enumeration-records) | Controller-detection and LiDAR enumeration records | Real (read-only) | 8 + 7 checks | session console logs | No (raw); summaries yes | ROV-02, LDR-HW-01 |
| [DS-HW-03](#ds-hw-03-robot_pi_sim_run-evidence) | `robot_pi_sim_run` evidence | Simulated tests on a real Pi; real power readings | 2,700 tests; 17 + 35 power samples | private | No (raw) | ROV-04, CAM-21 |
| [DS-CI-01](#ds-ci-01-github-actions-run-records) | GitHub Actions run records | Real (metadata) | 184 runs | GitHub | private repo | CI-001, CI-003 |
| [DS-EXT-01](#ds-ext-01-third-party-models-coco-depth-anything-qwen) | Third-party models (COCO weights, Depth-Anything, Qwen base) | External | — | caches, outside Git | per licence | all detection, MAP-03/04, all Qwen |
| [DS-SYN-01](#ds-syn-01-synthetic-micro-benchmark-input) | Synthetic micro-benchmark tensor | Synthetic | 1 | not stored | n/a | CAM-01 |
| [Missing](#missing-datasets) | Tape calibration samples, real Grove distances, real LiDAR scans, real RoverC logs | — | **0** | — | — | MAP-09, RNG-HW-CAL, LDR-HW-SCAN |

Merged duplicates: the trail graph was described by three audits (mapping, rover, CI), the LiDAR fixtures by three (sensors, rover, CI), the recorded Pi frame by three (camera, mapping, CI), the camera-mapping state logs by two (mapping, CI), and the robotics simulated fixtures by two (sensors, CI). `TOOL_CALL_TRAINING_SET.jsonl` and `TRAINING_EXAMPLES.jsonl` are **views** of the v0.2 SFT train file, not extra data (DS-QWN-05).

---

## 3. Camera datasets (real, private)

None of the camera data has bounding-box ground truth. "Ground truth" is the operator's declared scene label (for example `standing`, `empty60d`), plus, in DS-CAM-04, a typed consent and scene annotation.

### DS-CAM-01 Mac bench camera runs

- **Purpose:** choose a detector, test poses, test false alerts on empty scenes.
- **Source / collection:** MacBook Pro built-in camera (1920×1080), `perception.live_camera`, an open office, 2026-11-07 18:46–20:34 UTC.
- **Real / synthetic:** Real.
- **N:** 15 runs (CAM-02 to CAM-14, CAM-22); ≈7,100 frame-log lines; 13 evidence PNGs + 13 annotated JPEGs.
- **Annotation:** none. Per-frame detector boxes are logged from CAM-08 onwards; earlier runs log only counts and the best box. The run name carries the scene label.
- **Class distribution:** no labels. Scenes: 5 person, 6 "empty" (5 of them contaminated by real people), 1 smoke, 1 long demo, 1 Haar.
- **Splits:** none.
- **Storage:** `$TEAM15_EVIDENCE/camera/` and an earlier private camera folder. Private.
- **Processing:** frame JSONL; lossless PNG of the evidence frame with its SHA-256.
- **Licensing / publication:** **do not publish or train on.** Frames include non-consenting bystanders and window reflections of people.
- **Biases:** one room, one viewpoint per run, windows, office lighting, one participant.
- **Limitations:** no ground-truth boxes; some runs used uncommitted code.
- **Experiments:** CAM-02…14, CAM-22; reports [CAM-03](reports/CAM-03-mac-bench-person-poses.md), [CAM-09](reports/CAM-09-mac-empty-scene-60s.md).

### DS-CAM-02 First Pi validation and e2e runs

- **Purpose:** check transport and ingest; later reused as the **replay input** for camera mapping.
- **Source / collection:** Pi 5 IMX708 via SSH, 2026-11-07 22:28 UTC (CAM-18) and 22:42 UTC (CAM-17).
- **Real / synthetic:** Real.
- **N:** 2 runs (448 + 3 frame-log lines); 1 PNG + 1 JPEG. The PNG `D1-b1794091323-000001.png` (sha256 5a22e84b…67d55, 1280×720) is the frame that every camera-mapping replay uses.
- **Annotation:** none. The operator stated there was one consenting person (CAM-17). The detector output on the replay frame is person 0.87, box [22, 1, 739, 627]; the top of the box is cut. No ground-truth distance.
- **Class distribution / splits:** — / none.
- **Storage:** `$TEAM15_EVIDENCE/camera_pi_validation/`, `$TEAM15_EVIDENCE/camera/`. Private.
- **Processing:** as DS-CAM-01, plus `evidence.camera` provenance.
- **Licensing / publication:** **never publish**: the frame shows a person, and it is upside down because it was taken on the bench mount. Keep it unmodified, because PR #3 references its checksums. `scripts/camera_demo.sh --replay` uses this folder by default (`REPLAY_GLOB`), so a replay demo **displays this person's image** on the local dashboard. Do not show it publicly without consent.
- **Biases / limitations:** close-up framing; one scene; one frame repeated in every replay. CAM-17 processed only 3 frames.
- **Experiments:** CAM-17, CAM-18, MAP-03, MAP-04, MAP-05, MAP-07, MAP-08, MAP-10 (the test skips when the frame is absent, which happens in CI).

### DS-CAM-03 Orientation check

- **Purpose:** choose the receiver rotation for the robot mount.
- **Source:** `perception.orientation_check`, robot mount, 2026-11-07 23:50 UTC. **Real.**
- **N:** 1 frame (rotation-0 PNG, rotation-180 PNG, comparison JPEG) + report JSON.
- **Annotation:** a human upright judgement (rotation 180).
- **Storage:** `$TEAM15_EVIDENCE/orientation_checks/`. Private.
- **Processing:** exposure and sharpness statistics; SHA-256 per file.
- **Licensing / publication:** **DO_NOT_TRAIN_OR_DISTRIBUTE**. Part of a person whose consent was not recorded is visible. A notice file in the folder is the only safeguard; no manifest enforces it. No Qwen dataset references it (Qwen audit).
- **Limitations:** a single frame. The report JSON still holds a stale double-rotation warning.
- **Experiments:** CAM-20.

### DS-CAM-04 Pi live test series

- **Purpose:** pose recall, empty-scene false alerts, behaviour on objects, latency.
- **Source / collection:** a consent-gated countdown runner (on the **unmerged** branch `test/camera-live-countdown`) + `perception.live_camera --source pi`, robot mount, 2026-11-08 07:08–08:07 UTC.
- **Real / synthetic:** Real.
- **N:** 7 runs: 4 person runs (96 + 94 + 94 + 94 frames), 1 empty (96), 2 object (101 + 100); 4 consented person image pairs; 1 chair reference image pair; `pi_health.jsonl` (11 samples per run).
- **Annotation:** operator-declared scene + typed consent (`run_annotation.json`, `object_test.json`); no boxes; no distances.
- **Class distribution:** person scenes: standing 1, seated 1, lying feet-first 1, lying side view 1 (all the same participant, inferred from the session). Empty 1, chair 1, drone 1.
- **Splits:** none.
- **Storage:** `$TEAM15_EVIDENCE/camera_live_test/<scene>-<local time>/`. Private.
- **Processing:** per-frame boxes and `detect_s` timing; run-report JSON with SHA-256 cross-references.
- **Licensing / publication:** consent covers capture, local dashboard display and storage, with `public_sharing: false`. **Do not publish or train on** without new consent.
- **Biases:** one participant, one room and viewpoint, indoor daylight, about 1.5–2 m.
- **Limitations:** 20 s per scene; the "ground truth" is a statement; the drone run had people in the background.
- **Experiments:** CAM-23…29; reports [CAM-23](reports/CAM-23-pi-live-person-poses.md), [CAM-24](reports/CAM-24-pi-live-empty-and-object.md).

### DS-MAP-01 Camera-mapping state logs

- **Purpose:** evidence of latency, throughput, distance refusal and staleness for `camera_mapping`.
- **Source / collection:**
  - (a) `$TEAM15_EVIDENCE/camera_mapping/<YYYYMMDD-HHMMSS>/{perception.jsonl, camera.log, dashboard.log}`, written by `scripts/camera_demo.sh` between 11:41 and 12:16 UTC on 2026-11-08. There are seven folders, and one of them (064602) holds only `dashboard.log`.
  - (b) The two build-session logs, `live_pi1.jsonl` (sha256 a4c2a8e4…e6cb63) and `replay1.jsonl` (c0ea733c…851efc). The audit recovered them into `$TEAM15_EVIDENCE/camera_mapping/eval_run1_recovered/`, together with a `PROVENANCE.txt`.
- **Real / synthetic:** REAL HARDWARE (065157 and `live_pi1`) and RECORDED HARDWARE (the replays).
- **N:** (a) 434 + 46 + 486 + 266 + 50 + 10 = **1,292 states**; (b) 117 + 41 states.
- **Annotation:** none. These are machine outputs with no ground truth.
- **Class distribution:** the replays in (a) contain `person` only (one frame). The live run had person 10 and chair 14 detections. `replay1` (b) is multi-class: chair 288, person 155, tv 117, dining table 80, others 26.
- **Splits:** none.
- **Storage:** private. The JSONL holds state only (boxes, scores, distances), no images. The `camera.log` files contain a local path and, in 065157, a network address: **redact them before any sharing**.
- **Processing:** summarised with Python `statistics` during the audit.
- **Licensing / publication:** private; the logs may describe people. Publish aggregate numbers only.
- **Biases:** the replays repeat one frame. `replay1` includes MacBook frames, for which the IMX708 intrinsics are meaningless.
- **Limitations:** the mount was unmeasured in every run, so the distance and FREE-space paths were never exercised on real data. During the live run a second producer was sharing the GPU.
- **Experiments:** MAP-01, MAP-02, MAP-04…08, DSH-02.

---

## 4. Qwen datasets (private workspace)

Every file lives in `$QWEN_WORKSPACE`, a private Git repository that is not part of Team-15 and is not published. Counts were verified by parsing every JSONL line (0 parse errors). Label vocabulary: **SIMULATED** = generated by team simulators and code teachers. **SYNTHETIC** = hand-written or generated text. **PUBLIC** = Co-GLANCE (CC BY 4.0, revision `3182801c`). **REAL_BENCH_META** = metadata only (no pixels) of real sightings from the MacBook bench camera, not robot evidence. Human review is **PENDING** on every dataset card, and the "Fable review" was **NOT PERFORMED**. None of these sets contains a team photo or a bystander photo: the validator rejects local image paths.

### DS-QWN-01 v0.1 seed and v0.1 SFT

- **Purpose:** the first advisory SFT and development set.
- **Source:** `build_seed.py`: hand-written scenarios, Co-GLANCE items and bench metadata.
- **Real / synthetic:** SYNTHETIC 20 + REAL_BENCH_META 7 + PUBLIC 18.
- **N:** 45 (`seed_v0.1_train.jsonl`; `sft_train_v0.1.jsonl` is built from it).
- **Annotation:** HAND_WRITTEN_TEACHER (written by an AI assistant, not verified), POLICY_DERIVED, DATASET_BOXES.
- **Class distribution:** 20 categories (public person presence 15, multiple people 6, …).
- **Splits:** train only.
- **Processing:** validator 91/91, 0 leakage findings.
- **Licensing / publication:** Co-GLANCE CC BY 4.0; not published.
- **Biases:** one author. The policy-derived labels are circular with config A.
- **Limitations:** about one example per category. The v0.1 SFT was **never trained on** (QWN-009).
- **Experiments:** QWN-009 (NOT RUN). These rows are also the v01 rows inside the v0.2 SFT.

### DS-QWN-02 v0.1 frozen eval

- **Purpose:** frozen benchmark for advisories. `frozen_v0.1_eval.jsonl`, sha d75268e9…67bab1.
- **Source:** as DS-QWN-01, with different templates and wording; bench items alternate by line (different boot ids).
- **Real / synthetic:** SYNTHETIC + REAL_BENCH_META + PUBLIC 18.
- **N:** 46 (18 public, 1 unsafe item, 1 detector miss).
- **Annotation:** as DS-QWN-01. **Splits:** test, frozen before any B/C run and enforced by hash.
- **Publication:** not published.
- **Biases:** for the synthetic items, the gold is the policy that config A implements, so config A is advantaged by construction.
- **Limitations:** n = 46.
- **Experiments:** QWN-001.

### DS-QWN-03 Co-GLANCE public items

- **Purpose:** real ground-robot frames for multimodal rows.
- **Source:** `fetch_coglance.py` at a pinned revision; the team ran its Faster R-CNN on them locally.
- **Real / synthetic:** PUBLIC real images.
- **N:** 36 (dev 18 / test 18).
- **Annotation:** dataset boxes: human-drawn, gdino auto-label, or unspecified (recorded per item).
- **Class distribution:** Clean 12, Filteredout 6, Multiperson 6, PartialOcclusion 6, FullOcclusion 6.
- **Storage:** images in a gitignored `data/` folder (referenced by sha256). Private copy.
- **Licensing / publication:** CC BY 4.0 with attribution. A NOTICE is in the Hugging Face adapter repo. We do not redistribute the images.
- **Biases:** folder categories are unreliable; gdino labels are auto-generated; the scenes are construction sites and camouflage only.
- **Limitations:** no lying people, no low light, no motion blur.
- **Experiments:** QWN-001; the multimodal rows of v0.1 and v0.2.

### DS-QWN-04 v0.2 ground-rescue curriculum and frozen v0.2 test

- **Purpose:** the mission tool-step protocol and fusion advisories; a frozen in-domain benchmark.
- **Source:** `build_v02.py` (seed 20261107): planner, safety gate, mock world, and a code teacher (`mission_policy`).
- **Real / synthetic:** SIMULATED (+ PUBLIC multimodal).
- **N:** missions 178, tool steps 1,012, advisories 70, multimodal 36. The frozen test (`frozen_test_v0.2/`) holds tool steps **230** (973ca8cf…5e1659), missions 40, advisories 14, multimodal 18.
- **Annotation:** CODE_VERIFIED; `acceptable_tools` lists order-free alternatives.
- **Class distribution:** 15 categories; moving obstacles are thin. The frozen test has 88 safety-variant steps and 40 missions with a stop condition.
- **Splits:** missions 118/20/40; tool steps 680/102/230; advisories 48/8/14; multimodal 16/2/18. The test was frozen on 2026-11-07 before any v0.2 model run, and re-verified.
- **Processing:** validator `validate_v02`: 0 failed, 0 test-prompt leaks.
- **Publication:** not published.
- **Biases:** a single teacher; gold = config A by construction; **the test has the same distribution as training**. Four frozen labels turned out not to be identifiable from the prompt (a hidden flag).
- **Limitations:** no real Grove or RoverC data.
- **Experiments:** QWN-008, 015, 016, 017, 026.

### DS-QWN-05 v0.2 SFT train and val

- **Purpose:** LoRA run2 training (train) and checkpoint selection (validation).
- **Source:** `build_sft_v02.py`, from the v0.2 curriculum and the v0.1 seed.
- **N, train** (`lora/data/v0.2/train.jsonl`, sha 1cb395d2…2ff7b): **707 rows** in the file (691 text, 16 image+text): tool step 617, fusion 47, image 16, v01 27. **689 rows were actually trained**, because 18 were longer than `--max-len 2400` and skipped. The 689 are 617 SIMULATED tool steps + 41 SIMULATED fusion + 20 SYNTHETIC hand-written + **4 REAL_BENCH_META** (metadata only) + **7 PUBLIC Co-GLANCE images**. The trained set is therefore *not* 100 % synthetic.
- **N, validation** (`lora/data/v0.2/val.jsonl`): 111 (101 tool steps, 8 fusion, 2 image).
- **Duplicate views:** `TOOL_CALL_TRAINING_SET.jsonl` (617 rows) and `TRAINING_EXAMPLES.jsonl` (90 rows) at the workspace root are record-for-record identical to the 617 tool-step rows and the 90 non-tool rows of the train file. They are not extra data.
- **Annotation / splits:** as the sources / train, validation.
- **Processing:** the prompts include RAG chunks from the private corpus.
- **Publication:** not published. The Hugging Face repo excludes all training data.
- **Biases:** all 6 camera–range disagreement rows and 9 of the 16 images were lost to the length filter, so only 7 images were trained.
- **Limitations:** **1 validation advisory is a byte-identical copy of a training row** (`adv02-0031` = `adv02-0051`, found 2026-11-08). It did not change the selection: every candidate scored 9/10 on advisories.
- **Experiments:** QWN-010…014.

### DS-QWN-06 v0.3 targeted missions

- **Purpose:** fix the error categories found in the frozen v0.2 failure analysis.
- **Source:** `build_targeted.py`; code teacher with the hidden-state-label problem fixed. **SIMULATED.**
- **N:** missions 152, steps 1,048 (train 912 / val 136); 24 timeout-stop steps.
- **Annotation:** the manifest lists the gold tools.
- **Publication:** not published.
- **Biases:** **it was designed from the frozen-test failure analysis**, so any later score on the frozen v0.2 test after training on it is contaminated at design level.
- **Experiments:** LiDAR pilot (150 rows), pilot mission validation (48).

### DS-QWN-07 lidar-0.1 benchmark, SFT mixture and pilot set

- **Purpose:** LiDAR advisories and agent episodes.
- **Source:** `build_lidar.py` (seed 20261108), ray-cast with the LiDAR agent's simulator (a pre-`dd58b80` worktree). **SIMULATED** (`hardware: false` on every row).
- **N:** benchmark: advisories 270, episodes 270 (30 scenario types × 9). SFT mixture: train 1,932, val 297, 0 too long (lidar advisory 210, agent step 1,022, mission v0.3 817, replay 180). **Pilot set** (`pilot_train.jsonl`, sha 329c9897…): **640** rows (agent step 230, advisory 180, mission v0.3 150, replay 80), 0 skipped, maximum 2,638 tokens.
- **Annotation:** CODE_POLICY / CODE_REFERENCE_AGENT.
- **Class distribution (benchmark actions):** FOLLOW_UP 99, NO_FURTHER 72, OPERATOR_REVIEW 54, SENSOR_FAULT 30, REFUSE 9, ABSTAIN 6. Motion: DO_NOT_REQUEST 213, STOP 34, BOUNDED_MOVE 23.
- **Splits:** train 180 / val 30 / **frozen test 60 + 60 episodes**. Test distances and bearings are disjoint from train, with separate phrase banks.
- **Processing:** the validator reported 0 failures, after first catching one geometry leak. `build_sft_lidar.py` asserts that every frozen set is excluded.
- **Publication:** not published; the pilot checkpoints are private.
- **Biases:** the pilot's targeted mission rows come from the frozen-test failure analysis.
- **Limitations:** simulated geometry only. The full mixture was **never trained**.
- **Experiments:** QWN-022, 024, 025, 026.

### DS-QWN-08 LiDAR generalization set

- **Purpose:** an independent generalization test. `generalization.jsonl`, sha 9431a021…f41b5c.
- **Source:** built from the LiDAR workstream's own fixtures at `7e61595`. A different author, so it is more independent than the other sets. **SIMULATED.**
- **N:** 44 (11 stop cases). **Splits:** test only; frozen; never used for training or selection.
- **Publication:** not published.
- **Limitations:** n = 44.
- **Experiments:** QWN-027, QWN-034.

### DS-QWN-09 delivery-0.1, frozen delivery test, delivery SFT

- **Purpose:** decision support for supply delivery.
- **Source:** `build_delivery.py`, using the robotics worker's `team15.qwen_advisory_input/1` schema.
- **Real / synthetic:** SIMULATED 264 + PUBLIC image with SIMULATED context 26; `is_field_evidence: false` on every row.
- **N:** delivery-0.1: 290. Frozen test (`delivery_test.jsonl`, sha b9a70c22…906d86): 77 (3 repetitions, a separate phrase bank, odd cm values, held-out public runs; re-frozen before any model eval; phrase overlap with train 0). Delivery SFT: train 310 (190 delivery + 120 replay; 102 with RAG), val 23.
- **Annotation:** code-policy gold (one author).
- **Publication:** not published.
- **Limitations:** no hardware data. The delivery SFT was **never trained on** (QWN-030). The delivery validation set was used for information only in QWN-014.
- **Experiments:** QWN-019, 020, 021.

### DS-QWN-10 RAG corpus

- **Purpose:** the retrieval knowledge base. `$QWEN_WORKSPACE/corpus/registry.json`, registry version 0.5.0, sha c81e0b9a…41af2.
- **Source:** team paraphrases of external sources, project docs and team guides.
- **Real / synthetic:** real documents, paraphrased.
- **N:** **47 documents → 253 chunks**; 0 rejected, 0 quarantined (rebuilt 2026-11-08). The retriever comparison (QWN-002) ran on an earlier 34-document version with 202 chunks.
- **Annotation:** provenance per chunk (doc and chunk sha256, URL, licence, permission).
- **Class distribution:** categories A 9, B 10, C 8, D 6, E 5, F 9. Permissions: PARAPHRASE_WITH_CITATION 37, PROJECT_OWNED 10.
- **Processing:** cleaning, chunking by heading, quarantine of prompt-injection text.
- **Licensing / publication:** **not publishable.** Licences are mixed and include CC BY-NC-ND 3.0, CC BY-ND 4.0 and CC BY-NC-SA 4.0 (gated), several "copyright — cite only" sources, and 2 "unverified — cite only".
- **Biases:** one author wrote both the guides and the evaluation queries.
- **Experiments:** QWN-001, 002, 003 and every RAG configuration.

---

## 5. Simulated and synthetic data in the repository

### DS-SIM-01 Synthetic trail graph

- `fixtures/trail_graph_synthetic.json`. Source: [build guide](../../TEAM15_DRONE_SEARCH_BUILD.md) §3.2 (per the file's `_note`). Hand-authored. **SYNTHETIC.**
- **N:** 26 nodes (A–Z), 15 undirected edges, weights 10–14 m. Nodes Q–Z have no edges.
- **Annotation:** edge distances. Class distribution and splits: n/a.
- **Storage:** public repo. **Licence:** the project's own.
- **Biases / limitations:** not a real place; the distances are not measured RoverC travel. The `SIM_NODE_XY` coordinates in `rover/sim.py` are an invented layout used only for bearings.
- **Experiments:** PLN-01, PLN-02, SIM-01a/b, DSH-03, and the CI route step in `.github/workflows/ci.yml`.

### DS-SIM-02 Rover simulator scenarios A–H

- Defined in `scenario()` in `rover/simrun.py`. Hand-authored obstacle placements, for example a box on D-E at 5 m, a person on C-D at 6 m, a sensor dropout at 8 s. **SIMULATED.**
- **N:** 8 scenarios (B and C are the same world). **Storage:** public (code).
- **Biases / limitations:** the world has no walls, so the simulator treats NO_ECHO as clear (CLEAR_TO_MAX). That is **not** the hardware policy, which fails closed. Heading and pose are perfect.
- **Experiments:** SIM-01a/b.

### DS-SIM-03 Unit-test fixtures and synthetic frames

- Inline fixtures in `rover/tests/` (RangeReading and PowerReading values, bridge frames, a `VERIFIED_FIXTURE` labelled "TEST FIXTURE - not a real bench result"), 284 rover test cases. Generated NumPy frames in `perception/tests/` and `tests/e2e/` (blank frames, coloured blocks, fake upside-down Pi frames). Synthetic configs with a hypothetical measured mount in `camera_mapping/tests/helpers.py`.
- **SYNTHETIC / MOCKED.** Public. The expected outcomes are coded in the tests.
- **Limitations:** they encode the authors' expectations. They prove plumbing and math, **not** accuracy.
- **Experiments:** CAM-30, CAM-31, MAP-11, ROV-01a/b, BRG-01a/b, DSH-03.

### DS-SIM-04 LiDAR scenario fixtures

- `lidar/fixtures/*.json`, generated by `python -m lidar export-fixtures` from the 2-D ray-caster in `lidar/simulation.py`. Seed 15, `SIM_MOUNT` (sensor 0 = robot rear, clockwise), `SIM_FOOTPRINT` (width 0.20 m, synthetic). Every file carries `"label": "SIMULATED"`, and the tests refuse forged labels.
- **N:** 23 scenario files, **76 frames, 37,038 points** (≈500 points per revolution), plus `index.json` and `dashboard_range_series_approach.json`; 832 KB.
- **Annotation:** each frame carries `expected` values (forward_motion_allowed, forward status, connection, completion, alignment, source mode, 8 sector statuses) computed by `LidarAssessor` at export time. The ground truth is the generator geometry.
- **Class distribution (FRONT status of the last frame, 23 scenarios):** CLEAR 7, CAUTION 4, BLOCKED 3, UNKNOWN 9. forward_motion_allowed is true in 5 of 23.
- **Splits:** none (regression fixtures).
- **Processing:** angles rounded to 3 dp and distances to 4 dp; quality 0–63.
- **Licence / publication:** the repo licence; no personal data.
- **Biases / limitations:** a perfect 2-D world (no beam divergence, no multipath, no motion within a revolution). Mirrors and glass are modelled as weak or missing returns, which may not match real specular behaviour. The footprint and fiducial are placeholders.
- **SHA-256:** `index.json` 7bd67e36…7d24; `dashboard_range_series_approach.json` 14ca7480…0a829; `02_obstacle_ahead.json` 5023b20f…53c6eb.
- **Experiments:** LDR-SIM-01, 03, 04, LDR-HW-01f.

### DS-SIM-05 Run-time simulator streams (not stored)

- **Grove simulator scenes:** `SimulatedDriver` in `ranging/drivers.py`: static, approach (2 m at 0.25 m/s, stopping at 0.2 m), open (nothing in range) and disconnected. Optional seeded Gaussian noise, dropout and spikes. **SIMULATED.** Experiments: RNG-SIM-01…05, ROV-05.
- **LiDAR byte-level mock streams:** `MockLidarDevice` in `lidar/transport.py` generates protocol bytes for scenarios 13 (disconnect), 14 (timeout) and 19 (corrupted packets), with fault injection. **MOCKED.** Experiments: LDR-SIM-01/03.

### DS-SIM-06 Robotics-workspace simulated fixtures

- `$ROBOT_WORKSPACE/fixtures/`: `sim_range_series_approach.json` (120 `team15.range_snapshot/1`-style snapshots, sha256 911e7d4b…e5d4c), `sim_range_snapshots.json` (named scenarios, 72167384…f2ebf310), `sim_robot_status.json`, `sim_delivery_events.json`. **SIMULATED.**
- **Purpose:** developing the dashboard range card (`python3 -m dashboard.serve --range-fixture …`; see the `dashboard/serve.py` docstring).
- **Storage:** private workspace, so they are **absent in CI** and 6 range-panel tests skip there (CI-003).
- **Experiments:** CI-002 (local), the dashboard range-panel tests.

### DS-SIM-07 qwen_advisory LiDAR cases

- `qwen_advisory/fixtures/lidar_advisory_cases.json`: label SIMULATED, `hardware: false`, 8 cases; the expected value is the deterministic policy. Public. It is used by the safety tests in `qwen_advisory/tests`.

### DS-SIM-08 Drone-fleet results

- `team15_starter/results/fleet_eval_fleet.csv` (80 rows, sha256 637794af…f483) and `fleet_eval_emcon.csv` (40 rows, 2dbb5b58…904c). Both hashes were re-computed in this audit.
- **Source:** `team15_starter/fleet_eval.py` → `homebase.simulate` on the grid scenario, seeds 0–19, 3 hidden people. **SIMULATED.**
- **Columns:** config, seed, done, t_done, t_found, vitals, false_contacts, delivered, uplink_loss, emissions, deaths, rtb.
- **Storage / licence:** public repo; the project's own (no LICENSE file for `team15_starter` apart from the vendored Leaflet BSD-2).
- **Biases:** assumed sensor detection probabilities ("demo-calibrated starting points").
- **Limitations:** **generated by older code** (`ea5016f`, `e47c1bf`) and **not reproducible at `d1b607a`** (SIM-07/08 give different numbers). The command lines were not recorded.
- **Experiments:** SIM-02, SIM-03.

### DS-SIM-09 SAREnv benchmark outputs

- `team15_starter/results/sarenv_bench_raw.csv` (360 rows) and `sarenv_bench_summary.csv` (6 rows) for the 10 km budget; the 30 km version exists only in git history (`7ed29a5`).
- **Source:** the external SAREnv repository (heatmaps, evaluator, baselines). It is **not vendored** and its version was not recorded. Victims are sampled synthetically (100 per scenario).
- **Real / synthetic:** SIMULATED on third-party probabilistic heatmaps. **N:** 60 scenarios × 6 planners per budget.
- **Licence:** the results are in the repo. The SAREnv licence is **UNVERIFIED**, and we do not redistribute SAREnv data.
- **Biases:** victims are drawn from the same heatmap the planners optimise against; one drone only.
- **Experiments:** SIM-05, SIM-06.

---

## 6. Real hardware records (not datasets for training)

### DS-HW-01 Grove real diagnose records

- `REAL_HARDWARE_diagnose_20261108T104315Z.json` and `…105024Z.json` (+ `.stdout`), in a private evidence folder on the Pi. **REAL HARDWARE.**
- **N:** 2 × 50 pings, all `NO_ECHO`, `distance_m` null. Each ping record holds status, `release_us`, edges and timestamps. **No distance value exists.**
- The same folder holds the gate outputs (`gate_check_config_*`, `gate_preflight_*`), a PCB photo screenshot (sha256 cd2a6e65…035ad), the config and its PROVENANCE sidecar, and the simulated `sensor_only_SIM/` runs.
- **Storage:** private, on the Pi only. **Not hashed** (the Pi was unreachable).
- **Publication:** never publish the photo. The JSON files could be published after review, but they contain a hostname and a teammate's handle in `wiring_verified_by`, so replace those with roles first.
- **Experiments:** RNG-HW-01, RNG-HW-02, RNG-PF-08, RNG-PF-09, RNG-SIM-04.
- The LiDAR working config and its `EVIDENCE.json` were kept only in a Mac session folder that was not preserved. They are not project evidence.

### DS-HW-02 Controller-detection and LiDAR enumeration records

- Read-only `lsusb`, sysfs, `ioreg` and `system_profiler` outputs from the team Pi and the main Mac, 2026-11-07/08. **REAL HARDWARE (read-only).**
- **N:** 8 controller checks (ROV-02.C1–C8) and 7 LiDAR sub-runs (LDR-HW-01a–g).
- **Storage:** session console logs only (private). Summaries are in [HARDWARE_READINESS](../rover/HARDWARE_READINESS.md) (addresses redacted) and in the `$ROBOT_WORKSPACE` journal.
- **Restrictions:** the raw outputs contain network addresses, hostnames and device serials, so they must not be published.

### DS-HW-03 robot_pi_sim_run evidence

- `$TEAM15_EVIDENCE/robot_pi_sim_run/`: `camera_run.log`, `demo.txt`, `guarded_tests.json/.log`, `monitor_camera.txt`, `monitor_tests.txt`, `pinctrl_before.txt`, `pinctrl_after.txt`.
- **Purpose:** prove that the separate `t15robot` sim suite ran on the Pi with zero hardware access, and record power during tests and during camera streaming.
- **Real / synthetic:** SIMULATED tests on a REAL HARDWARE host; the power figures are REAL HARDWARE.
- **N:** 30 runs × 90 tests; 17 + 35 power samples. Captured 2026-11-08 00:50–00:53 UTC.
- **SHA-256:** `guarded_tests.json` af12bd0b…ac978; `guarded_tests.log` d7d6c6b8…c79a27; `demo.txt` 5a8affa6…26e34; `monitor_tests.txt` dbfab5b5…42fa2; `monitor_camera.txt` 78dbc600…1ed; `camera_run.log` 10c7b769…de28; `pinctrl_*` 0efa17c7…de9da (before and after identical).
- **Restrictions:** `camera_run.log` contains device-tree paths only; no frames were kept. Private.
- **Experiments:** ROV-04 (= CI-006), CAM-21.

### DS-CI-01 GitHub Actions run records

- 184 runs (105 push / 79 pull request), 2026-11-07 18:59 → 2026-11-08 12:14 UTC. Real metadata, with a conclusion per run. Stored on GitHub (private repository); log retention is limited, so the logs will expire. Grouped by workflow path. Experiments: CI-001, CI-003.

---

## 7. Third-party models and synthetic inputs

### DS-EXT-01 Third-party models (COCO, Depth-Anything, Qwen)

- **COCO 2017 via torchvision weights.** `fasterrcnn_resnet50_fpn_v2_coco-dd69338a.pth` and `fasterrcnn_mobilenet_v3_large_fpn-fb6a3cc7.pth`, cached in the user's torch cache. COCO train2017 has ≈118k images (a public figure, not measured by us), 80 classes. torchvision metadata reports val2017 box mAP 46.7 (R50-FPN-v2) and 32.8 (MBv3). The team did no fine-tuning. Bias: web photography with mostly upright people in daylight; few lying or partly covered people; **no drone, box or rubble class**. Scores are not calibrated. Licence: check the COCO terms (annotations CC BY 4.0; images under Flickr terms) and the torchvision weight terms before redistributing. The weights are **not** in the repo. Used by every detection run.
- **Depth-Anything-V2.** `depth-anything/Depth-Anything-V2-Metric-Indoor-Small-hf` (trained on synthetic Hypersim indoor scenes) and `Depth-Anything-V2-Small-hf`, in the Hugging Face cache, not in Git. Licence **UNVERIFIED** in this audit: check each model card before redistributing. Used by MAP-03, MAP-04.
- **Qwen3.5-2B base** (HF revision `15852e8c`; Ollama `qwen3.5:2b-q4_K_M`). Used by every QWN row. The team's LoRA adapter is public on Hugging Face at revision `21013d4` (QWN-031). Its training data is not.

### DS-SYN-01 Synthetic micro-benchmark input

- `torch.rand(3, 720, 1280)`: 1 tensor, not stored. Its content is unrealistic, so it is suitable for timing only. Used by CAM-01.

## Missing datasets

These datasets **do not exist**, and several key claims would need them:

| Needed dataset | Expected location | Blocks |
|---|---|---|
| Tape-measured camera distance samples | `$TEAM15_EVIDENCE/calibration/samples.jsonl` | MAP-09, PLN-03, any camera distance accuracy |
| Real Grove distances (any VALID ping) | on the Pi | RNG-HW-CAL, RNG-HW-FLOOR, Grove accuracy |
| Real RPLIDAR C1 scans | — | LDR-HW-SCAN, LiDAR accuracy |
| Real RoverC motion logs (commands, encoders or measured travel) | — | any claim about real driving |
| Labelled bounding boxes for any team camera frame | — | precision and recall of the detector on our scenes |
| Human-reviewed Qwen gold labels | `$QWEN_WORKSPACE` | an independent check of the code-teacher labels |
