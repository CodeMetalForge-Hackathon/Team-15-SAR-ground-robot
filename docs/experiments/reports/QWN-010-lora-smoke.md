# QWN-010: LoRA smoke test (`rescue-lora-v0.2-smoke`)

**Label:** REAL HARDWARE compute (Mac) on SYNTHETIC/SIMULATED data · **Status:** PARTIAL: training completed, but memory was unsafe and the checkpoint was not usable · **Date:** 2026-11-07 19:04:15 → 19:16:05 ET (training); smoke eval started 19:16:26 ET

**In plain words.** Before a real training run we did a tiny 8-step run, to check that the trainer works on this model and this Mac. It ran and the loss went down. But it used almost all of the Mac's memory and pushed the machine into heavy swapping, which would have endangered the live demo. The 8-step adapter also could not yet produce the required output format.

## Objective

Check that LoRA training on `Qwen3_5ForConditionalGeneration` (hybrid DeltaNet, vision frozen) runs end-to-end on MPS, and measure memory.

## Setup

| | |
|---|---|
| Hardware | Mac M4 Pro, 24 GB, MPS, bf16 |
| Software | `$QWEN_WORKSPACE` `$QWEN_WORKSPACE/lora/train_v02.py` (smoke committed in `2531d6d`, 19:19 ET); torch 2.12.0, transformers 5.22.2, peft 0.21.2 |
| Base | `Qwen/Qwen3.5-2B` @ `15852e8c16360a2fea060d615a32b45270f8a8fc` |
| LoRA | r 16, α 32, dropout 0.05; 10 module types; vision/merger excluded; 15.63 M trainable |
| Data | `lora/data/v0.2/train.jsonl`, 707 rows, sha256 `1cb395d2…2ff7b` |
| Args | `--exp smoke --max-steps 8 --save-every 8 --max-len 3072 --min-free-pct 20`, grad-accum 8, lr 1e-4, seed 7 |

## Results

| Step | Loss | MPS GB | Free % |
|---|---|---|---|
| 1 | 1.5756 | 21.73 | 54 |
| 2 | 1.4444 | 22.26 | 25 |
| 3 | 1.4506 | 22.49 | 26 |
| 4 | 1.5974 | 23.88 | 48 |
| 5 | 1.4023 | 24.35 | 34 |
| 6 | 0.7470 | 23.50 | 44 |
| 7 | 0.7120 | 24.43 | 40 |
| 8 | 0.6351 | 22.29 | 43 |

- Wall time 707 s; 64 micro-steps; 0 skipped; checkpoint `ckpt-0008`.
- Swap reached 7.6/8 GB (`LORA_TRAINING_REPORT.md` §3).
- **Smoke checkpoint on 20 val tool steps (HF, RAG, unconstrained): 0/20 parseable, 0/20 correct** (`$QWEN_WORKSPACE/results/v02_tools_summary_smoke_ckpt8_val.json`).

## Failure and root cause

Memory: full-vocabulary logits (248,320 vocabulary × about 2k tokens) are materialised for the loss. This was fixed later by computing logits only for assistant tokens (`logits_to_keep`), which brought training memory to about 7–8 GB ([QWN-013](QWN-013-lora-run2.md)). Eight steps were too few to learn the format.

## Evidence

`$QWEN_WORKSPACE/lora/out/rescue-lora-v0.2-smoke/config.json` (sha256 `4aee32e2…35b840`), `train_log.jsonl` (`b00b5bcb…f37c46`), `$QWEN_WORKSPACE/results/v02_tools_summary_smoke_ckpt8_val.json` (`026265e3…7db452f`). The checkpoint is backed up at `$ADAPTER_BACKUPS/rescue-lora-v0.2-smoke/ckpt-0008/` (weights not copied).

## Limitations

The 8-step schedule is not comparable to run2's: the lr peaked at about 2.8e-5 because the warmup and cosine were compressed. Val n = 20.

## What it proves / does not prove

- **Proves:** the pipeline runs on this architecture with the vision tower frozen, and the loss decreases.
- **Does not prove:** any behavioural improvement.

## Next time

Measure memory with the logits fix before the first full run, and smoke-test with the demo guard active.
