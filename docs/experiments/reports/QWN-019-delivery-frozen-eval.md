# QWN-019 / QWN-020 / QWN-021: Frozen delivery test (77 cases): BASE / RAG / LORA / LORA_RAG and Ollama

**Label:** SIMULATED contexts (+ PUBLIC Co-GLANCE frames on public rows); REAL HARDWARE compute on the Mac · **Status:** COMPLETE · **Dates (ET):** HF base B/C 2026-11-07 21:32–21:49; HF ckpt-0088 B/C 21:49–22:01; Ollama B/C 22:26

**In plain words.** We tested whether any Qwen variant can decide supply-delivery steps (for example "the gripper is not ready, do not deliver"). None can. The best model was right 17 times out of 77. No model ever suggested an unsafe delivery, but the untuned models often added forbidden content such as distances or medical words. Our guard removed all of it. Delivery decisions therefore stay with deterministic code.

## Objective

Measure transfer of ckpt-0088 (trained on missions, **not** delivery) to delivery advice, and the effect of RAG.

## Setup

| | |
|---|---|
| Data | `rescue_datasets/delivery_v0.1/frozen_test/delivery_test.jsonl`, **n = 77**, sha256 `b9a70c22…906d86`. 3 repetitions with a separate phrase bank and odd centimetre values, plus public images from held-out runs. Re-frozen before any model eval (commit `af155f2`). Test/train phrasing overlap 0 |
| Ground truth | Code-policy gold (`$QWEN_WORKSPACE/rescue_qwen/delivery.py`), single policy author |
| Configs | BASE (HF bf16 base, facts), RAG (+ delivery sources), LORA (ckpt-0088, facts), LORA_RAG; plus Ollama Q4 + grammar B/C |
| Runtime | HF transformers 5.22.2 bf16 MPS, greedy, thinking off, no grammar; Ollama 0.40.2 with the JSON grammar |
| Script | `$QWEN_WORKSPACE/eval/run_eval_delivery.py` (`--backend`, `--adapter`, `--configs`, `--split`, `--tag`); comparison built by `$QWEN_WORKSPACE/eval/report_delivery_compare.py` |

## Metrics and why

- **Raw recommendation correct** measures model quality.
- **Pipeline correct** includes the fallback, which *is* the gold, so it is not a model-quality measure.
- Safety, counted on raw output: unsafe delivery suggestions, forbidden claims, schema-invalid outputs, invalid citations.
- Integration: robotics validator OK, and `delivery_authorized` equal to control state.

## Results

| Config | Raw correct | Pipeline correct | Guard fallback | Schema invalid | Forbidden/unsupported claims | Unsafe delivery | Robotics validator OK | Latency median / p90 |
|---|---|---|---|---|---|---|---|---|
| BASE (HF) | 7/77 | 53/77 | 46 | 22 | 24 | 0 | 69 | 5.46 / 6.08 s |
| RAG (HF) | 15/77 | 58/77 | 54 | 20 | **34** | 0 | 69 | 7.68 / 9.19 s |
| LORA (HF) | 15/77 | 25/77 | 8 | **1** | **7** | 0 | **76** | **3.58 / 4.34 s** |
| LORA_RAG (HF) | 12/77 | 32/77 | 18 | 4 | 14 | 0 | 75 | 5.23 / 6.65 s |
| Ollama base (grammar) | 10/77 | 55/77 | — | 0 | **49** | 0 | 69 | 1.92 / 2.18 s |
| Ollama base + RAG (grammar) | 17/77 | 55/77 | — | 0 | **45** | 0 | 76 | 2.62 / 2.96 s |
| Deterministic policy (= gold) | 77/77 | 77/77 | 0 | 0 | 0 | 0 | 77 | ≈0 |

`delivery_authorized` matched the control service in 77/77 for every configuration. Raw-correct Wilson 95 % CIs: BASE 4.5–17.6 %, RAG 12.2–29.7 %, LORA 12.2–29.7 %, LORA_RAG 9.1–25.3 %. These overlap, so none of the differences is established at n = 77. Ollama base cited non-retrieved IDs in 26/77; with RAG, 0/77.

## Failures

- **ckpt-0088 collapses to conservative defaults** (REQUEST_OPERATOR_REVIEW / ABSTAIN in 60 and 62 of its errors) and ignores gripper, e-stop and authorization facts. Because valid-but-wrong conservative answers are not caught by the guard, its *pipeline* score (25) is lower than BASE's (53).
- **RAG increased forbidden claims** for the untuned model (24 → 34 on HF). Retrieved text appears to invite quoting numbers and medical vocabulary.

## Evidence

- `$QWEN_WORKSPACE/results/delivery_compare.json` (sha256 `be430eeb…9f2365`)
- `delivery_summary_hf_base_test.json` (`2245cf1f…cf7daf`)
- `delivery_summary_hf_lora_run2_ckpt0088_test.json` (`b65e0ffe…b614ed`)
- `delivery_summary_ollama_qwen3.5_2b-q4_K_M_test.json` (`9e03baf6…c637f5`)
- logs `dlv_test_base.log` (`351e49fd…0fffae`), `dlv_test_lora.log` (`e3208735…d80f33`), `dlv_test_ollama.log` (`5cb9cfa4…c4ef73`)
- `$QWEN_WORKSPACE/docs/BASE_VS_RAG_VS_LORA.md` §1 and §3, `$QWEN_WORKSPACE/docs/DELIVERY_SAFETY_EVALUATION.md`

## Limitations and confounders

- All contexts are SIMULATED. No delivery hardware was exercised.
- There is a single policy author.
- The forbidden-claim metric is regex-based and can miss paraphrases.
- BASE and RAG breakdowns were marked "raw truncated" (their metrics were computed in memory before the evaluator stored the parsed value).
- Adversarial injection in delivery scene notes was not tested at scale.

## What it proves / does not prove

- **Proves:** no Qwen configuration is accurate enough to decide delivery steps. The guard and control-copied authorization held in 308 model calls (0 unsafe delivery suggestions, 0 forbidden claims displayed).
- **Does not prove:** delivery safety on hardware, or what a *delivery-trained* adapter would do (never trained, [QWN-030](QWN-030-delivery-lora-not-run.md)).

## Decision

Delivery recommendations come from the deterministic policy. Qwen may only add explanation text through the robotics validator.
