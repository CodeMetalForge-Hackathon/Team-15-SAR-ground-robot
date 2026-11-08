# Experiment summary

This page answers ten questions about Team-15's experimental record: how many experiments there were, how many touched real hardware, how many trained or evaluated a model, which failed, how good the evidence is, what is strongly supported, and what remains to be done. It also audits data quality and explains how to read the experiments without over-reading them. Every count is derived from the [experiment registry](EXPERIMENT_REGISTRY.md) using the rules in §2, so you can reproduce it.

**Status:** Reference (audit of 2026-11-08 at `d1b607a`).

**Related:** [Experiment registry](EXPERIMENT_REGISTRY.md) · [Benchmark results](BENCHMARK_RESULTS.md) · [Dataset inventory](DATASET_INVENTORY.md) · [22 Experiments and failures](../22_EXPERIMENTS_AND_FAILURES.md) · [19 Testing and benchmarks](../19_TESTING_AND_BENCHMARKS.md) · [25 Limitations and future work](../25_LIMITATIONS_AND_FUTURE_WORK.md)

---

## 1. The ten answers

| # | Question | Answer |
|---|---|---|
| 1 | Total experiments discovered (with identifiable records) | **141** executed experiments. The registry has 157 rows: 141 executed, 4 duplicate rows of runs counted elsewhere, and 12 NOT RUN |
| 2 | Real-hardware experiments | **61**. Of these, 33 produced sensor or perception data (28 camera, 3 camera-mapping or dashboard, 2 Grove), 27 were read-only inspections or availability checks, and 1 is an unverified firmware upload (EXT-01). **0 moved a wheel; 0 measured a distance against ground truth** |
| 3 | Simulated / mocked / synthetic experiments | **71**, plus **7** RECORDED HARDWARE replays and **2** N/A (an integrity check and a service failure with unrecorded input). 3 of the 71 are synthetic workloads timed on real hardware (CAM-01, QWN-004, QWN-005) |
| 4 | Model-training experiments | **5 attempted** LoRA runs: run2 (QWN-013) and the LiDAR pilot (QWN-024) completed; the smoke run (QWN-010) is partial; run1 (QWN-011) and run1b (QWN-012) failed. Also 1 feasibility pass (QWN-006) and 2 NOT RUN (QWN-009, QWN-030). No detector or depth model was trained |
| 5 | Model-evaluation experiments | **26**: 22 Qwen/RAG quality evaluations (including 3 failed attempts: QWN-007, 023, 034), 2 Qwen runtime benchmarks (QWN-004/005), 1 detector latency benchmark (CAM-01), 1 depth-model check (MAP-03). Every quality evaluation used SIMULATED or SYNTHETIC test sets. **0 used labelled real-world ground truth** |
| 6 | Failed or inconclusive | **27**: 14 FAILED + 13 INCONCLUSIVE. Another 10 are PARTIAL. Separately, 8 controller checks (ROV-02.C1–C8) completed with a negative result (NOT DETECTED) |
| 7 | Experiments with complete evidence | **89**: a retained, machine-generated artefact exists that someone with access can re-check (a hashed evidence file, a committed file, a CI run, a Qwen results file, or an in-repo test re-run at a known commit) |
| 8 | Experiments with missing or weak evidence | **52**: the only record is a session console log, a PR or doc description, or a file on the unreachable Pi that was never hashed. The list is in §3 |
| 9 | Strongest empirically supported achievements | See §4 |
| 10 | Remaining experimental work | See §6 |

## 2. How we counted

1. **Unit of counting = one registry row**, which is one run at one revision. Runs at different commits (SIM-01a vs SIM-01b) count separately, as the [brief's](EXPERIMENT_REGISTRY.md#how-to-read-this-registry) "do not merge runs" rule requires. The eight controller checks ROV-02.C1–C8 count as eight, and the seven LiDAR sub-runs LDR-HW-01a–g count as seven.
2. **Duplicates removed (4 rows):**
   - DSH-01 is the same 90 s run as CAM-18 (counted under CAM-18).
   - CI-006 is the same 2,700-test Pi run as ROV-04 (counted under ROV-04). The mapping audit also mentioned it as "examined".
   - CI-004 (30 link checks) is part of the CI-002 local run.
   - QWN-032 (live camera-demo Qwen calls) is the same runs as MAP-04 and DSH-04 after the workaround.
   - Also merged without removing a row: the sensor-only simulator rehearsal inside ROV-05's report is counted once, as RNG-SIM-05.
3. **NOT RUN rows (12) are excluded** from "experiments": MAP-09, PLN-03, QWN-009, QWN-030, ROV-03a, ROV-03b, SIM-04, RNG-HW-FLOOR, RNG-HW-CAL, RNG-HW-T2, LDR-HW-INFO, LDR-HW-SCAN.
4. **Label = provenance of the input data.** A row labelled "SIMULATED + MOCKED" counts once under simulated/mocked/synthetic. DSH-02 ("REAL HARDWARE + RECORDED") counts as real hardware because a live runner was involved.
5. **EXT-01/EXT-02** (unmerged PR #6) are included because a written record exists on that branch. Both are flagged as having weak evidence.
6. The tally was produced by parsing the registry's Status and Label columns. Result: 157 rows → 141 executed; labels REAL 61 / RECORDED 7 / SIM-MOCK-SYNTH 71 / N/A 2; statuses COMPLETE 104 / FAILED 14 / INCONCLUSIVE 13 / PARTIAL 10.

### Breakdown by domain (executed, de-duplicated)

| Domain | Executed | Real HW | Recorded | Sim/mock/synth | N/A | FAILED | INCONCL. | PARTIAL |
|---|---|---|---|---|---|---|---|---|
| Camera (CAM) | 34 | 30 | 0 | 4 | 0 | 3 | 8 | 3 |
| Mapping/planning/dashboard (MAP, PLN, DSH) | 16 | 3 | 7 | 5 | 1 | 2 | 1 | 2 |
| Qwen (QWN) | 31 | 0 | 0 | 30 | 1 | 5 | 0 | 2 |
| Rover / bridge / sim (SIM, ROV, BRG, EXT) | 25 | 9 | 0 | 16 | 0 | 0 | 0 | 1 |
| Sensors (RNG, LDR) | 31 | 19 | 0 | 12 | 0 | 4 | 4 | 1 |
| CI | 4 | 0 | 0 | 4 | 0 | 0 | 0 | 1 |
| **Total** | **141** | **61** | **7** | **71** | **2** | **14** | **13** | **10** |

FAILED rows: CAM-12, CAM-32, CAM-33, DSH-02, DSH-04, QWN-007, QWN-011, QWN-012, QWN-023, QWN-034, RNG-HW-01, RNG-HW-02, LDR-HW-01b, LDR-HW-01d. INCONCLUSIVE rows: CAM-04, 05, 09, 10, 11, 13, 14, 26, MAP-03, RNG-WIR-01, LDR-HW-01a, 01e, 01g. PARTIAL rows: CAM-07, 17, 22, MAP-06, MAP-07, QWN-008, QWN-010, EXT-01, LDR-HW-01c, CI-005.

## 3. Evidence quality: the 52 weak-evidence experiments

These experiments probably happened as described, but the only record is narrative or unhashed. Treat their numbers as reported, not verified.

| Domain | Rows | Why the evidence is weak |
|---|---|---|
| Camera (7) | CAM-01, CAM-15, CAM-16, CAM-19, CAM-32, CAM-33, CAM-34 | session console log only (CAM-19's frame files were never found) |
| Mapping (2) | MAP-03, DSH-04 | console log; the DSH-04 failure is documented only in a console log and a code docstring |
| Qwen (1) | QWN-007 | the invalid run was discarded; only described in docs |
| Rover (14) | SIM-01a, ROV-01a, BRG-01a, ROV-02.C1–C8, ROV-05, EXT-01, EXT-02 | PR descriptions, console logs, a human-written test report, or an unmerged branch's README |
| Sensors (27) | RNG-HW-01, RNG-HW-02, RNG-PF-01…10, RNG-WIR-01, RNG-SIM-01, 03, 04, 05, LDR-SIM-01, 02, 05a, LDR-HW-01a–g | the Grove JSON files are on the Pi and **unhashed**; the gate and LiDAR runs are in console logs; the earlier simulation counts come from docs |
| CI (1) | CI-005 | test counts as claimed in PR bodies |

The two most important results in the project, the Grove 0/50 runs (RNG-HW-01/02), sit in the weak-evidence group only because the Pi was unreachable. Hashing those two JSON files is the cheapest evidence improvement available. MAP-01 and MAP-02 were weak until the coordinator recovered their logs into `$TEAM15_EVIDENCE/camera_mapping/eval_run1_recovered/`; their hashes (a4c2a8e4…, c0ea733c…) were re-checked in this audit.

## 4. Strongest empirically supported achievements

Ordered by strength of evidence. Each comes with its limit.

1. **The Pi→Mac→dashboard perception pipeline works live on the robot-mounted camera.** The live Pi runs ran at 4.68–5.17 fps (CAM-16, CAM-18, CAM-23, CAM-25, MAP-01), with capture→dashboard latency of about 0.5–0.6 s (CAM-27/28/29) and an end-to-end median of 479.8 ms (MAP-01). The Pi was not throttled during streaming (CAM-21). *Limit:* a relayed SSH link over an overlay network. The direct path and endurance on battery are untested.
2. **Faster R-CNN found the person in every frame across standing, seated and two lying poses** on the Pi (378/378 frames, CAM-23/27/28/29), and the genuinely empty room produced 0/96 person frames and 0 alerts (CAM-25). HOG failed on every seated and lying pose (0/94 ×3, 0/98), which justified the detector choice. *Limit:* one participant, one room, about 20 s per pose, no labelled boxes. This is an existence proof, not a recall rate.
3. **Fail-closed behaviour was observed on real hardware, not only in tests.** The Grove NO_ECHO runs ended in health FAULT, `NO_RESPONSE_EVER` and a STOP motion verdict (RNG-HW-01/02). The hardware gates refused incomplete configs 8 times before opening (RNG-PF-01…09). `camera_mapping` refused to give any distance, corridor verdict or route with an unmeasured mount in all 1,292 demo states (MAP-04…08). Camera loss reached STALE/UNKNOWN within 2 s (MAP-05).
4. **The LoRA adapter learned the mission tool protocol in distribution.** It scored 218/230 (94.8 %, 95 % interval 91.1–97.0 %) on the frozen simulated mission set with 0/182 unsafe calls (QWN-017), compared with 0/230 for the same runtime without the adapter (QWN-016). It is published with checksums verified (QWN-031). *Limit:* the test comes from the same generator as the training data. The adapter is **not served in the demo**, and it transfers badly to LiDAR (over-permissive 14/60, QWN-022).
5. **RAG measurably reduces invented citations** (16 → 3 of 46, QWN-001), and FTS5 retrieval is accurate and fast (18/20 hit@4, 0.17 ms, QWN-002). *Limit:* the same RAG **increased** forbidden claims on delivery (24 → 34) and LiDAR (19 → 35) for the untuned model (QWN-019, QWN-022).
6. **The safety logic is thoroughly regression-tested.** 818 pytest tests and 30 protocol checks pass at `d1b607a` (CI-002), and 181 of 184 CI runs were green, each failure fixed within 15 minutes (CI-001). The firmware model's watchdog trips in 0.251 s and the host latches in 0.05 s after a cable cut (BRG-01b). Rover scenarios A–H reach their expected end states with 0 collisions (SIM-01b). *Limit:* everything here is MOCKED or SIMULATED (see the warning in [Benchmark results](BENCHMARK_RESULTS.md)).
7. **Useful negative findings with clear causes:** window reflections produced a false person alert at 0.991 (CAM-12). The first warm-up call on MPS takes 3.7 s (CAM-19). Size-based ranging on a side-cut box overestimates distance, 7.91 m for a nearby chair (MAP-06). All three led to code fixes.

## 5. Inconsistencies resolved between the domain audits

| # | Inconsistency | Resolution |
|---|---|---|
| 1 | The camera audit labelled the synthetic-tensor benchmark (CAM-01) SYNTHETIC, while the Qwen audit labelled its fixed-prompt benchmarks (QWN-004/005) REAL HARDWARE | Harmonised: the label describes the input data, so all three are SYNTHETIC "timed on real hardware" |
| 2 | The Qwen audit wrote "6 training attempts" but listed 5 (QWN-010, 011, 012, 013, 024) | 5 attempts |
| 3 | The Qwen audit wrote "21 evaluation rows", and its list resolves to 20 | 22 Qwen quality evaluations when the failed attempts QWN-007 and QWN-034 are included (QWN-023 was already in the list) |
| 4 | The same runs were registered by two audits: DSH-01/CAM-18, CI-006/ROV-04 (also noted by the mapping audit), QWN-032/MAP-04+DSH-04, CI-004/CI-002, RNG-SIM-05 inside ROV-05 | Counted once (§2) |
| 5 | "Not detected" hardware checks: the rover audit marked them COMPLETE (NOT DETECTED), the sensors audit marked LDR-HW-01b/d FAILED | Kept as each audit wrote them, so the linked reports stay consistent. The 8 negative controller checks are reported separately in §1 row 6 |
| 6 | QWN-032 was labelled "REAL HARDWARE inference on RECORDED input" | RECORDED HARDWARE (input) and marked as a duplicate |
| 7 | DSH-04 was labelled REAL HARDWARE (Mac inference) | N/A: a software-service failure whose input was not recorded |
| 8 | The mapping audit counted 4 real-hardware rows (including DSH-04) | 3 |
| 9 | The brief said "CI all green on `d1b607a`" | Only `ci` and `perception` ran on `d1b607a`; lidar, ranging and qwen were last green on `159c678` (CI-003) |
| 10 | The brief said the training data was "689 synthetic + 7 Co-GLANCE" | 707 rows in the file; 689 trained, **including** 7 Co-GLANCE frames and 4 bench-camera metadata-only rows (DS-QWN-05) |
| 11 | The mapping audit called the MAP-01/02 logs "temporary, at risk" | Recovered into `$TEAM15_EVIDENCE/camera_mapping/eval_run1_recovered/`; hashes match |
| 12 | "M5StickC NOT DETECTED" vs PR #6's claim that a StickC Plus was flashed | Both stand: NOT DETECTED **on the team Pi and the main Mac in the reported checks**; the PR #6 upload happened from a teammate's Mac and is unverified (EXT-01). Wheel movement is NOT VERIFIED in either case |
| 13 | QWN-031 "9–10 files" | 9 files in SHA256SUMS, all passing |
| 14 | The Pi offline times differ (06:37 local in the camera failures list, 06:55 ET in the timeline) | Two separate drops, at about 11:38 and about 11:55 UTC (session log, MAP-06 `camera.log`) |
| 15 | Pi temperatures for 2026-11-08 00:50 differ (41.7–46.1 °C vs 43.3–46.6 °C) | Not a contradiction: different monitor files, one for the test run (ROV-04) and one for the camera run (CAM-21) |

Spot checks made against the underlying evidence for this page: the CAM-12 summary (294 frames, `min_box_frac` 0.15, PERSON in 294/294 frames); the SHA-256 of both committed fleet CSVs (match SIM-02/03); the Qwen mission summaries (39/230 and 0/230 for the base model, 218/230 with interval [0.911, 0.970] for the LoRA, 2/182 calls rejected by the gate); and the recovered MAP-01/02 log hashes.

## 6. Remaining experimental work

In rough priority order. Each item names the experiment it would unblock.

| # | Work | Unblocks |
|---|---|---|
| 1 | Hash and copy the two Grove diagnose JSONs off the Pi; enable a persistent journal on the Pi | evidence for RNG-HW-01/02; root cause of the Pi reboots |
| 2 | Verify the Grove wiring **at the sensor connector** (photo + meter readings: VCC, SIG idle, series resistance), then rerun `diagnose`, `floor-check` and `calibrate` | RNG-HW-FLOOR, RNG-HW-CAL, any real ultrasonic distance |
| 3 | Measure the camera mount; collect tape samples; run the calibration | MAP-09, PLN-03, every camera distance and corridor verdict |
| 4 | Complete the LiDAR physical checklist; run GET_INFO/HEALTH, then one stationary scan | LDR-HW-INFO, LDR-HW-SCAN |
| 5 | Get the controller to enumerate on the Pi (data cable, port, 5 A wall power); reconcile the two firmware efforts (PR #15 draft and PR #6 `roverc_usb`); compile, flash and run the watchdog test wheels-off | ROV-03a/b; a real watchdog latency |
| 6 | Build a small labelled frame set (with consent) and measure detector precision and recall; add a glass ignore mask and re-test empty scenes | a real recall and false-positive rate |
| 7 | Evaluate the LoRA **without** RAG and on the v0.2 advisory set; find a serving path (merge + GGUF); score live advisories against ground truth | QWN-008 model rows; deployment of the adapter |
| 8 | Human review of the Qwen datasets; de-duplicate the validation set; build a test set from a different author or a real log | independent Qwen evaluation |
| 9 | Re-run and commit the fleet studies with argv and the commit SHA stored in the output | reproducible SIM-02/03 |
| 10 | Add CI for `team15_starter`; ship public simulated stand-ins for the private fixtures (8 CI skips); verify interactive Ctrl-C | CI coverage; MAP-07 |

## 7. Data-quality audit

| Problem | Where it occurs | How it affects interpretation |
|---|---|---|
| **Missing ground truth** | Every camera run (CAM-02…29) has only operator-declared scene labels, no boxes. MAP-03 depth has no reference distance. All Qwen gold labels come from code policy or code teachers. The Grove and LiDAR hardware produced no measurements at all | No precision, recall or distance error can be computed. "94/94 frames" means "the detector fired while a person was said to be there", not "the box was correct" |
| **Duplicates** | DSH-01 = CAM-18; ROV-04 = CI-006; QWN-032 = MAP-04 + DSH-04; CI-004 ⊂ CI-002. Validation advisory `adv02-0031` is byte-identical to training row `adv02-0051`. Every replay repeats **one** recorded frame (MAP-04's 434 states, MAP-05's 532). Rover scenarios B and C are the same world | Without de-duplication the totals would be inflated by 4. Replay "samples" are not independent: 434 states from one frame are effectively n = 1 for perception. The validation duplicate did not change the checkpoint choice (all candidates scored 9/10), but it should be removed |
| **Synthetic mixed with real** | The v0.2 SFT train set mixes simulated tool steps with 7 public real images and 4 bench-camera metadata rows (QWN-013). MAP-02 ran Mac frames through IMX708 intrinsics. DSH-02 showed live and replayed producers on one dashboard. ROV-04 ran simulated tests on a real Pi. CI-002 includes one recorded frame | Reporting "trained on synthetic data" is not accurate. "Ran on the Pi" (ROV-04) does not mean "exercised Pi hardware". MAP-02 geometry is meaningless; only its detection counts are usable |
| **Uncalibrated distances** | Every camera distance (MAP-01…08, JUDGE_DEMO steps 2–4); MAP-03's 0.41 m; MAP-06's 7.91 m (a bug); the Grove simulator's 99.9 cm | No real-world distance claim is supported. The simulator's "accuracy" reproduces its own noise model |
| **Inconsistent timestamps** | Qwen records in ET and the other domains in UTC. Run folder names use local time (`empty-20261108T020800` = 07:08 UTC). Run ids are boot-based. SIM-01a and RNG-PF-01 have only a date. The Pi and Mac clocks were not cross-checked for the capture→Mac delays | Ordering across domains needs conversion (this registry marks ET). Absolute latency figures that cross machines may include clock offset |
| **Leakage / contamination** | The v0.3 targeted set and the LiDAR pilot's mission rows were **designed from the frozen v0.2 failure analysis**, so QWN-026's 182/230 is not a clean held-out score. The frozen v0.2 test has the same generator as training. Config A's policy is also the gold for synthetic v0.1 items. One author wrote both the RAG guides and the retrieval queries. MAP-10 tests on the same frame used for the replay demos | Only QWN-027 (the generalization set from a different author) is reasonably independent. Treat QWN-017's 218/230 as in-distribution performance |
| **Missing baselines** | No labelled detection baseline; MobileNet-V3 accuracy never compared with R50; no LoRA-without-RAG mission score; no same-runtime base vs LoRA comparison with a grammar (Ollama rejects the adapter); no Qwen rows on the v0.2 advisory set (QWN-008); no tape baseline for any distance | Improvement claims are relative to whatever baseline exists. For example, "base 0/230 vs LoRA 218/230" is a **format-following** gap (QWN-018), not a reasoning gap |
| **Small samples** | One participant in every person test; about 20 s per Pi scene; 1 depth frame; 2 Grove runs; 3 Pi Qwen advisories; 46 / 32 / 44 item test sets; 1 drone scene | The results are existence proofs or smoke tests. Intervals are wide (QWN-017's ±3 points comes from n = 230; the person tests have effectively n = 1) |
| **Unsupported claims** | 40 items in the registry's [claimed but no evidence found](EXPERIMENT_REGISTRY.md#claimed-but-no-evidence-found) list, for example real wheel movement, the wiring "fix", "about 5 fps", "Ctrl-C stops everything", "all empty runs used `--min-box-frac 0.15`" | Do not repeat these claims as results. Several are contradicted by measurements (3.76–4.68 fps) |
| **Non-reproducible** | The committed fleet CSVs do not match re-runs at `d1b607a` (SIM-02/03 vs SIM-07/08). CAM-19's files are missing. Console-log-only rows (§3). Pi files unhashed. Results depend on unmerged branches (`test/camera-live-countdown`, PR #6, the Qwen-workspace `fix/rag-index-threading`). Fleet argv and the SAREnv version were not recorded | Quote SIM-02/03 only together with their generating commit. Anything that exists only in a console log cannot be re-checked |
| **Mismatched versions** | MAP-01 ran on pre-commit code. CAM-09/10/11 predate the `--min-box-frac` commit. The RAG evaluation used the 34-doc corpus (now 47). The LiDAR dataset came from a pre-`dd58b80` simulator. The PR #8 tree carried an old ranging copy (RNG-SIM-03, 118 tests). CI's lidar, ranging and qwen results are from `159c678`, not `d1b607a`. Qwen rows mix Ollama Q4 with a grammar and HF bf16 without one | Every comparison must be within one revision and one runtime. The registry keeps separate rows for that reason |

## 8. How to read these experiments (a learning guide)

If you are new to experimental evaluation, these five questions will protect you from most mistakes. Ask them of every number in the registry.

1. **What was the input: real, recorded, simulated, mocked or synthetic?** The label column answers this. A simulator can only confirm what its model already assumes. For example, the rover simulator treats NO_ECHO as "clear" because its world has no walls, which is the *opposite* of the hardware policy. A simulated pass therefore tests the logic, never the physics.
2. **What was the ground truth, and who produced it?** If the answer is "the operator said so" (camera) or "the code policy says so" (Qwen), then the metric measures agreement with that statement, not truth. When the gold comes from the same policy as a baseline (config A), that baseline is advantaged by construction.
3. **How many *independent* samples are there?** 434 replayed states of one frame is one sample. 94 frames of one person in one pose in 20 s is close to one sample. The half-width of a 95 % interval on a proportion is at most about ±6.5 percentage points for n = 230 (about ±3 near 95 %, as in QWN-017) and up to about ±14 for n = 46.
4. **Is the comparison like-for-like?** Same revision, same runtime, same decoding constraints, same test set. The Qwen results are the textbook case: Ollama with a JSON grammar gets 39–56/230, while HF without a grammar gets 0/230, from the *same base model*. The gap is caused by the decoder, not by the weights.
5. **Is the claim stronger than the experiment?** "The gate opened" (RNG-PF-09) is not "the wiring is correct". "The watchdog model trips at 0.251 s" (BRG-01b) is not "the robot stops in 0.251 s". "Tests pass" is not "the robot is safe". Write the narrower statement that the evidence actually supports.

A practical reading order: start with the [benchmark results](BENCHMARK_RESULTS.md) warning box, then the REAL HARDWARE rows in the [registry](EXPERIMENT_REGISTRY.md), then the failures narrative in [22](../22_EXPERIMENTS_AND_FAILURES.md). Read the simulation rows last, as evidence that the software logic is coherent.
