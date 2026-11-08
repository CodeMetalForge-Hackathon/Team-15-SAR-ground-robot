# QWN-015 / QWN-016 / QWN-017: Frozen v0.2 mission tool-step benchmark (230 steps)

**Label:** SIMULATED missions / SYNTHETIC prompts (REAL HARDWARE compute on the Mac) · **Status:** COMPLETE · **Dates (ET):** Ollama B/C 2026-11-07 18:56 (summary `started`); HF base + RAG 22:01:38; HF ckpt-0088 + RAG 22:17:21

**In plain words.** We gave each model 230 "what is the next step?" questions taken from 40 simulated rescue missions that were locked away before any training. The untuned model could not even produce the answer format on its own (0/230). With a format-forcing grammar it got 39–56 right. The fine-tuned adapter got **218** right and never asked for an unsafe movement. All of this is in simulation, using the same mission generator the adapter learned from.

## Objective and hypothesis

- **H:** ckpt-0088 + RAG follows the mission tool protocol far better than base, with no increase in unsafe motion requests.

## Setup

| Row | ID | Model | Runtime | Grammar | RAG | Date |
|---|---|---|---|---|---|---|
| Base (B) | QWN-015 | `qwen3.5:2b-q4_K_M` | Ollama 0.40.2 | **JSON schema** | no | 2026-11-07 18:56 |
| Base + RAG (C) | QWN-015 | same | Ollama | **JSON schema** | ≤ 3 chunks / 1,800 chars | same session |
| Base + RAG (C) | QWN-016 | `Qwen/Qwen3.5-2B` @ `15852e8c` | HF transformers 5.22.2 bf16, MPS | **none** | yes | 22:01 |
| **ckpt-0088 + RAG (D)** | QWN-017 | base + `rescue-lora-v0.2-run2/ckpt-0088` | HF bf16, MPS | **none** | yes | 22:17 |

- Common to all rows: the same `TOOL_SYSTEM` and `render_tool_user` prompts byte-for-byte, thinking off, greedy / temperature 0, 200 output tokens, and the same scorer (`eval/run_eval_tools.score`, which uses the **real** `safety_gate`).
- **Data:** `rescue_datasets/v0.2/frozen_test_v0.2/tool_steps.jsonl`, **n = 230** steps from 40 missions, sha256 `973ca8cf…5e1659` (re-verified unchanged on 2026-11-08). Frozen 2026-11-07, "before any v0.2 model evaluation and any LoRA training". Held-out route pairs, odd sensor values and separate phrasing, from the **same** generator and teacher as training.
- **Ground truth:** the code-verified teacher policy (`mission_policy.next_step`). `acceptable_tools` allows order-free alternatives.

## Metrics and why

- **Step correct:** the primary measure of protocol following.
- **Parseable:** format.
- **Unsafe motion requests:** gate-judged, on **raw** output. This is the safety metric.
- **Gate-rejected calls**, **stops when sufficient**, **safety-variant steps**, **final action**, **route explanation**, **latency**.

Proportions carry Wilson 95 % intervals.

## Results

| Config | Steps correct | Parseable | Unsafe motion | Gate-rejected | Stops when sufficient | Safety-variant | Final action | Latency median / p90 |
|---|---|---|---|---|---|---|---|---|
| Base (Ollama, grammar) | 39/230 | 230/230 | 0/230 | 107/230 | 0/40 | 12/88 | never finishes | 0.83 / 1.09 s |
| Base + RAG (Ollama, grammar) | 56/230 | 230/230 | **2/230** (gate blocked) | 78/230 | 0/40 | 21/88 | never finishes | 1.00 / 1.49 s |
| Base + RAG (HF, no grammar) | **0/230** | **0/230** | — | — | 0/40 | 0/88 | — | 4.14 / 5.64 s |
| **ckpt-0088 + RAG (HF, no grammar)** | **218/230 (94.8 %, CI 91.1–97.0 %)** | 230/230 | **0/182** (CI 0–2.1 %) | 2/182 | **40/40** | 84/88 | 37/48 | 2.27 / 3.71 s |

Memory: HF base peak RSS 3.6 GB / MPS 6.2 GB; LoRA 3.0 / 6.1 GB.

**What "0/230" means.** The HF base model with RAG and no grammar did not produce a single output that parsed as a step object. The runtime audit ([QWN-018](QWN-018-runtime-comparison-audit.md)) found 97 valid JSON objects with the wrong key (`final_recommended_action`) and 133 invalid or truncated outputs. A lenient re-score gives 6/230. It is a **format and protocol failure**, not 230 unsafe acts.

**What "0 unsafe" means.** 0 of the 182 *tool calls* ckpt-0088 predicted were unsafe motion requests. The other 48 steps were FINAL answers.

## Failures: the 12 ckpt-0088 errors (`$QWEN_WORKSPACE/docs/FAILURE_ANALYSIS_230.md`)

| Class | n | Example |
|---|---|---|
| Label not identifiable (teacher used a hidden flag) | 4 | `sighting_confirmed` step 5 |
| Reasoning (ignored an operator decision or rejected motion in the history) | 3 | asked for review after CONFIRMED |
| Procedure (stopped after the first blocked scan) | 2 | did not request the RIGHT scan |
| Scorer false positive ("No person is confirmed") | 1 | fixed with `affirmative_search` |
| **Missed `request_stop` after a range TIMEOUT** (1 MOVING, 1 IDLE) | **2** | went straight to operator review |

Excluding the non-identifiable and scorer items: 7 of 225 answerable steps wrong. The two missed stops are mitigated **by design**: the rover's `SafetySupervisor` treats non-OK or stale readings as UNKNOWN and refuses forward motion independently of Qwen.

A guard false positive was also found: the 2 "unsupported claims" counted for LoRA final summaries were negations. With the fixed rule the count is 0/48. The measured numbers (37/48 final, 2/48 claims) are kept as recorded.

## Evidence

- `$QWEN_WORKSPACE/results/v02_tools_D_hf_lora_run2_ckpt0088_test.jsonl` (sha256 `a1fbe39c…7a61a5`)
- `v02_tools_summary_hf_lora_run2_ckpt0088_test.json` (`0f6b46d4…d3c262`)
- `v02_tools_summary_hf_base_test.json` (`c68bfd83…6c9364`)
- `v02_tools_summary_ollama_qwen3.5_2b-q4_K_M_test.json` (`6f48217a…1184ce`)
- logs `tools_test_hf_lora.log` (`ce6c2ae2…3eb025`), `tools_test_hf_base.log` (`eddd8ef4…b3c646`), `v02_tools_ollama.log` (`46dc84f5…c36b53`)
- `$QWEN_WORKSPACE/docs/BASE_VS_RAG_VS_LORA.md` §2

## Limitations and confounders

- **In-distribution:** same simulator, teacher and tool contract as training. This is the main confounder.
- **Cross-runtime:** the Ollama rows differ in quantization (Q4 vs bf16), sampler defaults (`presence_penalty 1.5`, `top_k 20`, `top_p 0.95`) and grammar. Only the grammar effect was isolated.
- **No no-RAG LoRA row:** accuracy without RAG is **NOT MEASURED**.
- **Single run, single seed.**
- **Teacher defects:** 4 gold labels are not identifiable from the prompt.

## Reproducibility

From the private workspace: `.venv-lora/bin/python -B -m eval.run_eval_tools --backend hf --adapter lora/out/rescue-lora-v0.2-run2/ckpt-0088 --configs D` and `--backend hf --configs C` for base. Ollama: `python3 -B -m eval.run_eval_tools --backend ollama --model qwen3.5:2b-q4_K_M --configs B C`. The published adapter on HF is byte-identical to ckpt-0088 ([QWN-031](QWN-031-hf-publication.md)). The corpus and frozen set are private.

## What it proves / does not prove

- **Proves:** the adapter learned the mission tool protocol on **held-out scenarios from the same generator**, without unsafe motion requests in 182 calls. It also shows that untuned 2B Qwen does not follow this protocol without a grammar.
- **Does not prove:** performance on real robot data (none exists), robustness to procedures the generator does not produce, or safety on other tasks. The same adapter is over-permissive on LiDAR ([QWN-022](QWN-022-lidar-frozen-eval.md)).

## Next time

Make the generator and teacher independent of the training generator (a second author or real logs), fix the hidden-flag labels, run a no-RAG ablation, and do a same-runtime grammar comparison ([QWN-018](QWN-018-runtime-comparison-audit.md)).
