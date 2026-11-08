# QWN-013 / QWN-014: LoRA run2 (`rescue-lora-v0.2-run2`): training and checkpoint selection

**Label:** REAL HARDWARE compute (Mac) on SYNTHETIC/SIMULATED data + 7 PUBLIC images · **Status:** COMPLETE · **Dates (ET):** training 2026-11-07 19:20:00 → 20:38:47; selection about 20:40 → 21:31 (`select_run2.log` mtime)

**In plain words.** This is the training run that worked. In 79 minutes on the Mac, the model was taught Team-15's step-by-step mission protocol using about 700 generated examples. We saved five snapshots and picked the best one, **ckpt-0088**, using only validation data and a rule written down before training. That snapshot later scored 218/230 on the frozen test ([QWN-017](QWN-017-frozen-mission-230.md)).

## Objective and hypothesis

- **H:** LoRA on the v0.2 curriculum teaches the tool-step protocol and safe ordering without increasing unsafe motion requests or unsupported claims relative to base.
- **Pre-declared selection** (`LORA_EXPERIMENT_CONFIG.yaml`, committed 18:59 ET): "best validated checkpoint, not the last; reject if raw unsupported claims or unsafe motion requests increase vs base".

## Setup

| | |
|---|---|
| Hardware | Mac M4 Pro, 24 GB unified memory, MPS, bf16 |
| Software | `$QWEN_WORKSPACE` `$QWEN_WORKSPACE/lora/train_v02.py` (run recorded in commit `1b57993`, 20:40 ET); Python 3.13.5, torch 2.12.0, transformers 5.22.2, peft 0.21.2 |
| Base | `Qwen/Qwen3.5-2B` @ `15852e8c16360a2fea060d615a32b45270f8a8fc` |
| LoRA | r 16, α 32 (scale 2), dropout 0.05; regex `^(?!.*(visual\|vision\|merger)).*\.(q_proj\|k_proj\|v_proj\|o_proj\|in_proj_qkv\|in_proj_z\|out_proj\|gate_proj\|up_proj\|down_proj)$` → 150 modules, **15.63 M** trainable (0.7 % of 2,213 M); vision tower, merger, embeddings, lm_head and `in_proj_a/b` frozen |
| Optimiser | AdamW lr 1e-4, wd 0, clip 1.0; 10-step warmup, cosine to 5 %; batch 1 × grad-accum 8; seed 7; gradient checkpointing; loss on assistant tokens only (`logits_to_keep`) |
| Command | `PYTORCH_MPS_HIGH_WATERMARK_RATIO=0.7 PYTORCH_MPS_LOW_WATERMARK_RATIO=0.5 nice -n 10 .venv-lora/bin/python -B -m lora.train_v02 --exp run2 --epochs 1 --save-every 22 --max-len 2400 --min-free-pct 15` |
| Data | `lora/data/v0.2/train.jsonl`, 707 rows, sha256 `1cb395d2…2ff7b`; val `lora/data/v0.2/val.jsonl`, 111 rows. Frozen test untouched (`frozen_test_untouched: true` in the manifest) |
| N trained | **689 unique records**: 617 tool steps, 41 fusion, 20 synthetic v0.1, 4 real-bench metadata, 7 Co-GLANCE images. 18 overlength records skipped, including **all 6 camera–range disagreement examples** |

## Training results

- 89 optimizer steps, 712 micro-steps, wall 4,725.9 s (78.8 min).
- Peak MPS 8.54 GB; lowest system free memory 23 % (threshold 15 %); the watchdog and demo guard never triggered.
- **Loss:** step 1 1.5756 → step 10 0.1814 → step 20 0.0096, then 0.004–0.40 noise. Quartile means 0.636 → 0.220 → 0.094 → 0.050. Mean of the last 10 steps 0.046.
- Weights changed: 150/150 LoRA B matrices non-zero. Σ‖B‖ = 20.73 (ckpt-0022), 27.33 (0044), 28.97 (0066), 29.14 (0088), 29.14 (0089).

## Selection results (validation only; HF bf16, RAG, unconstrained)

| | Tool step correct (102) | Parse | Unsafe motion | Adv. both (10) | Adv. unsupported | Final claims | Delivery val (info only, 23) | Score | Eligible |
|---|---|---|---|---|---|---|---|---|---|
| base | 0 | 0 | 0/0 | 9 | 1 | — | 18 | 0.900 | ref |
| 0022 | 71 | 98 | 2/98 | 9 | 0 | 0/0 | 23 | 1.596 | no |
| 0044 | 81 | 102 | 3/100 | 8 | 1 | 0/2 | 10 | 1.594 | no |
| 0066 | 87 | 102 | 1/95 | 9 | 0 | 0/7 | 4 | 1.753 | no |
| **0088** | **97** | 101 | **0/79** | 9 | 0 | 0/22 | 4 | **1.851** | **selected** |
| 0089 | 97 | 102 | 0/81 | 9 | 0 | 1/21 | 7 | 1.851 | yes |

Score = tool-step rate + advisory both-correct rate. A checkpoint is ineligible if unsafe motion or advisory unsupported claims exceed base's (`$QWEN_WORKSPACE/lora/select_checkpoint.py`).

## Failures and audit findings

1. **Tie broken by order.** 0088 and 0089 tied. `max()` returned the first-listed (0088). This tie-break was not pre-declared.
2. **Validation duplicate.** `adv02-0031` (val) is byte-identical to `adv02-0051` (train), found during this documentation audit. It cannot have changed the outcome: every candidate scored 9/10 on advisories.
3. **Coverage gap.** The adapter never saw camera–range disagreement, and only 7 images.
4. **Over-conservative drift** on the delivery task: val accuracy fell from 23/23 (0022) to 4/23 (0088). It was recorded but did not count in the score.

## Evidence

- `$ADAPTER_BACKUPS/rescue-lora-v0.2-run2/config.json` (sha256 `17fa5a81…6130f5`)
- `train_log.jsonl` (`6733c06a…0d1701`)
- `selection.json` (`8e3e11a0…c466f2`)
- `$QWEN_WORKSPACE/logs/train_run2.log` (`9a12e5fb…4f0cf4`)
- `logs/select_run2.log` (`ae14efad…fd9923`)
- `$QWEN_WORKSPACE/results/run2_skipped_overlength.json` (`4f683e35…f4a2f0`)
- `$QWEN_WORKSPACE/docs/LORA_TRAINING_REPORT.md`

Checkpoint weights (about 60 MB each) are backed up but **not** copied here.

## Limitations and confounders

- One seed.
- Validation n is small for advisories (10).
- Validation comes from the same generator as training.
- The loss on near-template JSON targets is not a quality signal.
- Delivery val was information only.

## Reproducibility

Exact command and data hash above. Results also depend on MPS kernel determinism (not verified) and on the private RAG corpus, which is used in val prompts.

## What it proves / does not prove

- **Proves:** LoRA on a laptop changed the model's behaviour on held-out *validation* steps from the same generator (0 → 97/102) with 0 unsafe motion requests on validation.
- **Does not prove:** performance on real data, on other task families (see [QWN-022](QWN-022-lidar-frozen-eval.md) and [QWN-019](QWN-019-delivery-frozen-eval.md)), or without RAG.

## Next time

Raise `--max-len` to 2700 (or shorten the RAG context) to keep all categories, declare the tie-break, de-duplicate val against train, and use 3 seeds.
