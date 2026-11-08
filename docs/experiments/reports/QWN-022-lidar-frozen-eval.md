# QWN-022 / QWN-023: Frozen LiDAR benchmark (lidar-0.1): base, base + RAG, ckpt-0088, ckpt-0088 + RAG, Ollama

**Label:** SIMULATED scans (LiDAR agent's simulator); REAL HARDWARE compute on the Mac · **Status:** COMPLETE (re-run); first run FAILED/superseded (QWN-023) · **Dates (ET):** QWN-023 superseded run before 2026-11-07 23:45; re-run 23:46 (HF base) → 2026-11-08 00:39 (Ollama + RAG)

**In plain words.** We asked each model to read a simulated LiDAR summary and recommend what to do, and also to run a small read-only "agent" that gathers evidence with tools. No model could do this reliably. The mission-trained adapter was the worst on safety: in 14 of 60 cases it suggested motion that the rules would not allow. Our guard caught every case, and the operator display always showed the correct, cautious rule-based answer.

## Objective

Establish the LiDAR baseline that any LiDAR adapter must beat, and test whether ckpt-0088 transfers.

## Setup

| | |
|---|---|
| Data | `rescue_datasets/lidar_v0.1/frozen_test/advisory.jsonl` (60, sha256 `32e330a6…b90058`) and `episodes.jsonl` (60, `7d163513…2209d0`; every 3rd episode evaluated, so **20** per configuration). Frozen before any model run. Test distances {0.3, 0.55, 0.8, 1.1, 1.6, 2.1} m and bearings are disjoint from train/val |
| Ground truth | `lidar_policy.reference_policy` (CODE_POLICY) and `agent.reference_agent_step` |
| Configs | A HF base, B HF base + LiDAR RAG, C ckpt-0088, D ckpt-0088 + RAG (all HF bf16, no grammar); Ollama base / + RAG (Q4, JSON grammar) |
| Decoding | Greedy / temperature 0, thinking off, **max 600 tokens for every configuration** |
| Script | `eval/run_eval_lidar.py --backend {hf,ollama} [--adapter] --rag {0,1} --tag … --episode-stride 3` |

## Metrics

- Raw schema-valid; field accuracies (action, motion recommendation, LiDAR status, next observation, person evidence); **all four** correct.
- **Over-permissive motion** and **unsupported claims**: the safety metrics, counted on raw output.
- Stop recall (8 stop cases); latency.
- Episodes: completed with own advisory, invalid tool calls, **forbidden-tool attempts**, step agreement, displayed-correct.

## Results: single-shot advisory (n = 60 each)

| Config | Schema-valid | All four | Over-permissive | Unsupported | Stop recall (8) | Latency median |
|---|---|---|---|---|---|---|
| A base (HF) | 0/60 | 0 | 0 | 0 | 8/8 | 7.4 s |
| B base + RAG (HF) | 0/60 | 0 | 0 | 0 | 8/8 | 9.0 s |
| C ckpt-0088 (HF) | 0/60 | 4 | **14** | 0 | 5/8 | 5.1 s |
| D ckpt-0088 + RAG (HF) | 0/60 | 4 | **9** | 0 | 6/8 | 6.8 s |
| Ollama base (grammar) | 60/60 | 6 | 2 | **19** | 6/8 | 2.6 s |
| Ollama base + RAG (grammar) | 60/60 | 3 | 0 | **35** | 8/8 | 3.1 s |
| Deterministic policy | 60/60 | 60 | 0 | 0 | 8/8 | ≈0 |

Why HF schema-valid is 0/60: the base model emits list-typed fields (`["UNCERTAIN"]`), and ckpt-0088 emits its v0.2 field `suggested_next_observation` instead of `next_observation`. Base's "0 over-permissive" and 8/8 stop recall come from invalid or default outputs, not from reasoning.

## Results: agent episodes (n = 20 each, 10-call budget)

| Config | Completed with own advisory | Invalid tool calls / total | Forbidden-tool attempts | Displayed correct (fixed fallback) |
|---|---|---|---|---|
| A | 0/20 | 36/108 | 0 | 20/20 |
| B | 0/20 | 34/106 | 0 | 20/20 |
| C | 0/20 | 40/123 | 0 | 20/20 |
| D | 0/20 | 40/121 | 0 | 20/20 |
| Ollama | 0/20 | 25/118 | 0 | 20/20 |
| Ollama + RAG | 0/20 | 22/89 | 0 | 20/20 |

Total: **0/120** completed with the model's own advisory; **0 forbidden-tool attempts in 665 calls**. Under the *original* fallback, displayed-correct was 13, 13, 19, 19, 14 and 10 of 20. It became 20/20 everywhere after the orchestrator fix (offline re-score, `$QWEN_WORKSPACE/results/lidar_episode_fallback_rescore.json`, sha256 `2de4eb71…ba22b4`).

## Failures

- **QWN-023 (superseded run 1):** the harness crashed on list-typed fields, raw outputs were truncated at 600 characters, and `max_tokens` was 420. It was archived in `results/superseded_lidar_run1/` (with `WHY.txt`) and re-run with the fixed harness at 23:45 ET.
- **Orchestrator safety gap:** the fallback was built only from model-fetched tools and understated a hazard. Fixed with `minimum_evidence` ([11 §12](../../11_AI_AGENT_AND_TOOLS.md#12-error-handling-the-fallback-and-a-safety-bug-we-found)).
- The simulated environment crashed on candidate tools without a candidate. Fixed to return NOT_FOUND.

## Evidence

- `$QWEN_WORKSPACE/results/lidar_summary_{hf_base_norag,hf_base_rag,hf_lora0088_norag,hf_lora0088_rag,ollama_base_norag,ollama_base_rag}.json`, for example `lidar_summary_hf_lora0088_norag.json` (`80db0fcf…5c55ef`)
- logs `lidar_hf_lora_norag.log` (`c966ec50…5d9f7b`), `lidar_hf_lora_rag.log` (`9208d86c…28da79`), `lidar_ollama_rag.log` (`c7498d81…abe43f`)
- `$QWEN_WORKSPACE/docs/NEW_LIDAR_EVALUATION.md`, `$QWEN_WORKSPACE/docs/ADAPTER_COMPARISON.md`

## Limitations

- SIMULATED only: no real RPLIDAR scan has been verified.
- Only 1 of the 20 sampled episodes is a stop case.
- The LiDAR scenes come from a pre-`dd58b80` LiDAR-agent simulator worktree.
- The episodes are a stride-3 subsample.

## What it proves / does not prove

- **Proves:** no Qwen configuration is usable for LiDAR advice. ckpt-0088 is a **safety regression** on this task. The guard and fixed fallback displayed a never-more-permissive advisory in every evaluated case.
- **Does not prove:** anything about real LiDAR data, or about a LiDAR-trained adapter (see [QWN-026](QWN-026-lidar-pilot-frozen-and-generalization.md)).
