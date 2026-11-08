# QWN-024 / QWN-025: LiDAR LoRA pilot (`rescue-lidar-lora-v0.1-pilot`): training and pre-declared selection

**Label:** REAL HARDWARE compute (Mac) on SIMULATED data · **Status:** training COMPLETE; selection excluded every checkpoint, so the adapter was **NOT PROMOTED** · **Dates (ET):** training 2026-11-08 00:49:39 → 01:52:33; selection finished by 02:34 (`select_lidar_pilot.log`)

**In plain words.** We tried a second, smaller training run to teach the model the LiDAR advisory format and agent steps. It learned the format. But every saved snapshot broke at least one safety rule we had written down in advance, so we did not use any of them.

## Objective and hypothesis

- **H:** 640 targeted examples (LiDAR advisories, agent steps, targeted mission steps, replay) fix the LiDAR serialization failure (0/60 schema-valid) without safety regressions.
- **Stop rule, declared before results:** if no eligible checkpoint beats base + RAG on validation, no adapter is used.

## Setup

| | |
|---|---|
| Hardware / software | Mac M4 Pro 24 GB, MPS bf16; torch 2.12.0, transformers 5.22.2, peft 0.21.2 |
| Base / LoRA | `Qwen/Qwen3.5-2B` @ `15852e8c`; r 16, α 32, dropout 0.05, same 10 module types, vision frozen, 15.63 M trainable |
| Data | `lora/data/lidar_v0.1/pilot_train.jsonl`, **640** records, sha256 `329c9897…`: 230 LiDAR agent steps, 180 LiDAR advisories, 150 v0.3 targeted mission steps, 80 replay (v0.2 tool/fusion/v0.1/image and delivery). 0 frozen-ID overlap (asserted by `build_sft_lidar.py`, re-checked for this report); max 2,638 tokens; 0 skipped |
| Args | `--exp pilot --prefix rescue-lidar-lora-v0.1 --data lora/data/lidar_v0.1/pilot_train.jsonl --epochs 1 --save-every 20 --max-len 3072 --min-free-pct 15`; lr 1e-4, accumulation 8, seed 7 |
| Selection | `$QWEN_WORKSPACE/lora/select_lidar_ckpt.py` (committed `ae21dae`, 00:52 ET, before any checkpoint existed): LiDAR **val** (30 advisories, 10 episodes) + targeted mission val (48 steps), all with RAG |

## Training results

- 80 optimizer steps, 640 micro-steps, wall 3,770.1 s (63 min).
- MPS ≤ 9.55 GB; free ≥ 23 %. Watchdog and demo guard never triggered.
- **Loss:** 1.29 (step 1) → 0.42 (10) → 0.32 (20) → 0.23 (40) → 0.013 (60) → 0.059 (80). Quartile means 0.757 → 0.260 → 0.183 → 0.139.

## Selection results (validation only)

| | LiDAR val all-four (30) | Schema-valid | Mission val (48) | Over-permissive | Stop recall (3) | Unsafe mission motion | Episodes completed (10) | Score | Excluded because |
|---|---|---|---|---|---|---|---|---|---|
| base + RAG | 0 | 0 | 0 | 0 | 2 | 0 | 0 | 0 | — |
| 0020 | 8 | 30 | 32 | **3** | **0** | 0 | 0 | 0.934 | over-permissive; lower stop recall |
| 0040 | 19 | 30 | 39 | **1** | 2 | **4** | 0 | 1.445 | over-permissive; unsafe mission motion |
| 0060 | 20 | 30 | 39 | 0 | 3 | **4** | 2 | 1.479 | unsafe mission motion |
| 0080 | 20 | 30 | 40 | 0 | 3 | **4** | 5 | 1.500 | unsafe mission motion |

`best: null`, `beats_base_rag: false`.

**Audit note.** The "more unsafe mission motion requests than base" exclusion is in the code committed at 00:52 (`select_lidar_ckpt.py`) but not in its docstring's rule list. It was pre-declared in code, but the documentation is incomplete.

## Evidence

`$ADAPTER_BACKUPS/rescue-lidar-lora-v0.1-pilot/config.json` (sha256 `fd0db9ac…ea3038`), `train_log.jsonl` (`d1b74d24…5f4283`), `selection.json` (`9c2db32b…5f5b50`); `$QWEN_WORKSPACE/logs/train_lidar_pilot.log` (`63ef68fc…f6e27c`), `select_lidar_pilot.log` (`c35875e3…374c1a`); `$QWEN_WORKSPACE/docs/LIDAR_LORA_TRAINING_REPORT.md`. The checkpoints are private and **not published**.

## Limitations and confounders

- Small validation sets (3 stop cases).
- The targeted mission steps were designed from the frozen-test failure analysis: design-level contamination of the later mission test ([QWN-026](QWN-026-lidar-pilot-frozen-and-generalization.md)).
- One seed.

## What it proves / does not prove

- **Proves:** the format failure was serialization, and training on the exact schema fixes it (30/30 val valid). It also shows the pre-declared gate working as intended: it rejected a higher-scoring but less safe adapter.
- **Does not prove:** that a larger or differently designed LiDAR adapter would fail.

## Next time

Use separate adapters per task, more geometric and sensor-failure coverage, and a mission rehearsal mix with a regression gate. No further training without approval (as recorded).
