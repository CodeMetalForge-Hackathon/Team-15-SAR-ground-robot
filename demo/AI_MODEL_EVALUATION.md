# AI model evaluation: Qwen3.5-2B + LoRA + RAG

**Evidence type for everything on this page:** real model inference on a Mac (M4 Pro, 24 GB), plus one
Raspberry Pi 5 latency test, run over **simulated / synthetic frozen test sets**. Gold labels come from
code policy. **No evaluation used real robot data.**

Every run used a single seed and ran once. The raw outputs live in the team's private Qwen workspace,
so the numbers below come from the team's experiment reports. Only the advisory contract tests
(`qwen_advisory/tests`) can be reproduced from this repository.

Sources: [`docs/experiments/BENCHMARK_RESULTS.md`](../docs/experiments/BENCHMARK_RESULTS.md),
[`docs/experiments/EXPERIMENT_REGISTRY.md`](../docs/experiments/EXPERIMENT_REGISTRY.md), the QWN-* reports in
[`docs/experiments/reports/`](../docs/experiments/reports/), [`docs/qwen/MODEL.md`](../docs/qwen/MODEL.md),
[`docs/09_LORA_TRAINING.md`](../docs/09_LORA_TRAINING.md) and [`docs/10_RAG_PIPELINE.md`](../docs/10_RAG_PIPELINE.md).
The docs came from PRs #12, #13 and #18.

## Headline

| Result | Value | Conditions | Source |
|---|---|---|---|
| **Trained adapter ckpt-0088 + RAG**, frozen mission steps | **218 / 230 correct (94.8 %, 95 % CI 91.1–97.0 %)**; 230/230 parseable; **0 / 182 unsafe motion requests**; 40/40 stops when evidence was sufficient | HF bf16 on MPS, no grammar. 230 steps from 40 simulated missions | [QWN-017](../docs/experiments/reports/QWN-017-frozen-mission-230.md) |
| Base model + RAG, same runtime and scorer | **0 / 230** (0/230 parseable) | HF bf16, no grammar | QWN-017 |
| Base model + RAG on Ollama with a JSON grammar | 56 / 230; 2 / 230 unsafe requests, both blocked by the gate | Ollama Q4_K_M + grammar | QWN-017 |

How to read this:

* The fair comparison, with the same runtime and no grammar, is **base 0/230 against ckpt-0088
  218/230**. That gap is "mostly about following the output format" (BENCHMARK_RESULTS).
* The mission test set comes from the **same generator and teacher as the training data**, so 218/230
  is an in-distribution result.
* There were 2 missed `request_stop` steps after a range timeout.

## Checkpoint 0088

| | |
|---|---|
| What | `rescue-lora-v0.2-run2/ckpt-0088`. LoRA r 16, α 32, 150 modules, 15.63 M trainable parameters. Vision tower frozen; base `Qwen/Qwen3.5-2B@15852e8c` |
| Training run | run2: 89 steps, 4,725.9 s, peak MPS memory 8.54 GB. 689 records used (18 over-length rows skipped). Checkpoints 0022 / 0044 / 0066 / 0088 / 0089 ([QWN-013](../docs/experiments/reports/QWN-013-lora-run2.md)) |
| Selection | **Validation data only.** The rule was declared before evaluation: score = tool-step rate + advisory both-correct rate, and a checkpoint is ineligible if it is less safe than base. ckpt-0088: 97/102 tool steps, 0/79 unsafe, 9/10 advisories, score 1.851 |
| Caveat | ckpt-0088 **tied** with 0089 (1.851). `max()` took the first-listed one, a tie-break that was **not declared beforehand**. One validation advisory duplicates a training row. Delivery validation accuracy fell from 23/23 (0022) to 4/23 (0088) |

## Was the LoRA adapter actually active?

* **Offline evaluation (HF/PEFT): yes, shown by behaviour.**
  * Same runtime, prompts and scorer: base + RAG parsed 0/230, ckpt-0088 parsed 230/230.
  * At weight level, 150/150 LoRA B matrices are non-zero (Σ‖B‖ = 29.14).
  * No doc records an explicit adapter-listing or logit-difference check.
* **Robot-path check on an unmerged branch: logged (boolean only), not on `main`.** The closed PR #20 branch contains
  `scripts/qwen_rover_advisor.py`. At startup it compares next-token logits with the adapter on and off,
  and refuses to serve unless they differ (and LoRA modules are present). A team session reported this
  check passing with ckpt-0088. The private evidence store holds 14 advice records and 13 session logs
  (2026-11-08 09:20–10:01 ET) that record `adapter_active_verified: true` and the ckpt-0088 SHA-256; motors
  were MOCKED, and no numeric logit value was logged. The final audit then ran the logit check itself from
  the public adapter: max next-token logit difference 15.03, 150 LoRA modules
  ([FINAL_GITHUB_AUDIT](../docs/FINAL_GITHUB_AUDIT.md)).
* **Live demo service: NO.**
  * The running service is **base Qwen3.5-2B (Ollama `qwen3.5:2b-q4_K_M`) + RAG + guard**
    (`C_QWEN_RAG`).
  * Ollama 0.40.2 rejects LoRA adapters ([QWN-018](../docs/experiments/reports/QWN-018-runtime-comparison-audit.md),
    E6), and the launcher builds only an Ollama backend.
  * The 3D simulation video's Qwen panel and the camera dashboard's live advisory therefore use the
    **base model**, not ckpt-0088.

## Retrieval (RAG)

| Item | Result | Source |
|---|---|---|
| Corpus | 47 documents → 253 chunks; 0 rejected or quarantined; 2 marked "cite only" | `docs/10_RAG_PIPELINE.md`, `docs/experiments/DATASET_INVENTORY.md` |
| Retriever comparison (20 hand-labelled queries, earlier 34-doc / 202-chunk corpus) | FTS5 BM25: hit@4 18/20, recall@4 0.762, MRR@10 0.852, query 0.17 ms (chosen). MiniLM: recall 0.729, query 7.1 ms | [QWN-002](../docs/experiments/reports/QWN-002-rag-retrieval-eval.md) |
| Effect in the advisory loop | invented citations fell **16/46 → 3/46**. RAG **increased** forbidden or unsupported claims on delivery (24→34) and LiDAR (19→35) | [QWN-001](../docs/experiments/reports/QWN-001-v01-frozen-eval-ollama.md), [QWN-019](../docs/experiments/reports/QWN-019-delivery-frozen-eval.md), [QWN-022](../docs/experiments/reports/QWN-022-lidar-frozen-eval.md) |

Limits: one author wrote both the queries and the guides, and the comparison was not re-run on the
47-document corpus.

## Correctness and format on other frozen sets

| Set (n) | Base / base + RAG | ckpt-0088 / + RAG | Note | Source |
|---|---|---|---|---|
| v0.1 advisory (46) | Ollama: 28 / 28 | not run | a reworded unsafe request was refused **0/1** in every config, including deterministic | QWN-001 |
| Delivery (77), raw correct | 7 / 15 (HF) | 15 / 12 | schema-invalid: base 22, RAG 20, LoRA 1, LoRA+RAG 4 | QWN-019 |
| LiDAR (60), fully correct; over-permissive | 0; 0 (HF, 0/60 schema-valid) | 4; **14** / 4; **9** | adapter not trained for LiDAR | QWN-022 |
| Generalization (44), over-permissive | 0 / 0 | 10 / 4 | | [QWN-026](../docs/experiments/reports/QWN-026-lidar-pilot-frozen-and-generalization.md) |

## Latency

| Host / runtime | Result | Source |
|---|---|---|
| Mac, Ollama 0.40.2 (Metal), 2B Q4_K_M, 10 fixed prompts | 1.65–2.56 s each; 10/10 valid; 2,231 MiB | [QWN-004](../docs/experiments/reports/QWN-004-runtime-benchmarks-mac-pi.md) |
| Raspberry Pi 5 (16 GB), llama.cpp CPU, 3 threads | **97.8 s cold, then 47.6 and 46.8 s**; 7.6–8.1 tok/s; 55.4→70.3 °C | QWN-004 |
| Mac HF bf16, mission steps (median / p90) | base + RAG 4.14 / 5.64 s; ckpt-0088 + RAG **2.27 / 3.71 s** | QWN-017 |
| Live service with the camera detector running | 5.18–5.67 s (content not scored) | BENCHMARK_RESULTS (MAP-04) |
| 3D simulation demo video (this package) | the Qwen report took 2.3 s; status `QWEN_GUARDED (RAG)` | [VIDEO_INDEX.md](VIDEO_INDEX.md) |

## Tool calls, unsafe requests and fallback

| Item | Result | Source |
|---|---|---|
| ckpt-0088 structured tool calls (missions) | 182/182 arguments valid; **0/182 unsafe**; 2/182 rejected by the deterministic gate | QWN-017 |
| LiDAR agent episodes | 0 forbidden-tool attempts in 665 calls; 0/120 completed with the model's own advisory | QWN-022 |
| Ollama agentic demo traces (6 simulated episodes) | every episode ended `INVALID_OR_REPEATED` and **fell back to deterministic** | [QWN-028](../docs/experiments/reports/QWN-028-agentic-tool-traces.md) |
| Safety regression gate | **FAILED for every model**. ckpt-0088 was over-permissive 14 / 9 times on LiDAR, but the guard blocked every one before display | [QWN-029](../docs/experiments/reports/QWN-029-safety-regression.md) |
| Fallback behaviour | no model → `DETERMINISTIC`; timeout, exception or critical guard finding → `DETERMINISTIC_FALLBACK`; otherwise `QWEN_GUARDED`. Never raises; `authority: "NONE"` always | `docs/qwen/QWEN_ADVISORY_CONTRACT.md`, `docs/11_AI_AGENT_AND_TOOLS.md` |
| Measured fallbacks, delivery (77) | base 46, RAG 54, LoRA 8, LoRA+RAG 18 | QWN-019 |
| Reproducible here | `python3 -m pytest -q qwen_advisory/tests`: **23 passed** (re-run for this package; see [TEST_RESULTS.md](TEST_RESULTS.md)) | `qwen_advisory/tests` |

## Failed or not-run experiments (kept on purpose)

* **QWN-007 discarded.** The Ollama app quit mid-run.
* **QWN-009 not run.** Its dry run reported `ready_to_train: false`.
* **QWN-010 smoke run partial.** ckpt-0008 parsed 0/20.
* **QWN-011 run1 failed** before any training step (invalid watermark ratio).
* **QWN-012 run1b failed** with an MPS out-of-memory error.
* **QWN-023 and QWN-034 harness crashes.**
* **LiDAR pilot not promoted.** Selection returned `best: null`, and its ckpt-0080 regressed to 182/230.
* **Delivery LoRA (QWN-030) not run.**

Sources: [registry](../docs/experiments/EXPERIMENT_REGISTRY.md) and the QWN reports.

## Hugging Face

The adapter is public at revision `21013d4`: 62,566,192 bytes; checksums 9/9 verified, including an
anonymous download ([QWN-031](../docs/experiments/reports/QWN-031-hf-publication.md)). Base weights,
training data and the RAG corpus are **not** published, so 218/230 cannot be reproduced from the
Hugging Face repo alone.

## Where the docs disagree

* Training attempts: "six" (`docs/09_LORA_TRAINING.md`) against "5" (EXPERIMENT_SUMMARY).
* Why the delivery LoRA was not run: "out of time" against "review first".
* Live latency with the detector running: 5.18–5.67 s against 5.2–5.7 s.

All are reported here as they appear in the sources.
