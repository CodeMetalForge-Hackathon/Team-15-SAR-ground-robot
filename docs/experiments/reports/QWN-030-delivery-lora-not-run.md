# QWN-030: Delivery LoRA experiment (`rescue-delivery-lora-v0.1`): NOT RUN

**Label:** SIMULATED data prepared; no compute · **Status:** NOT RUN · **Date prepared:** 2026-11-07 (data built with the delivery dataset, commit `62d657f`, 19:39 ET)

**In plain words.** We prepared a training set and a command to teach the model supply-delivery advice, but we never ran it. It had to wait for the main training run, and after that the team chose to review results first. No delivery adapter exists.

## What was prepared

| | |
|---|---|
| Base | `Qwen/Qwen3.5-2B` @ `15852e8c`, PEFT 0.21.2, MPS bf16 |
| Train | `lora/data/delivery_v0.1/train.jsonl`, **310** rows (sha256 `0d96281f…`): 190 delivery advisories (102 with RAG sources, 15 image+text) + 120 replay rows from v0.2 to limit forgetting |
| Val | 23 delivery rows (`d527d91d…`) |
| Test | frozen delivery test, 77 (`b9a70c22…906d86`), never used for training or selection |
| Planned command | `HF_HUB_OFFLINE=1 PYTORCH_MPS_HIGH_WATERMARK_RATIO=0.7 PYTORCH_MPS_LOW_WATERMARK_RATIO=0.5 nice -n 10 .venv-lora/bin/python -B -m lora.train_v02 --prefix rescue-delivery-lora-v0.1 --exp run1 --data lora/data/delivery_v0.1/train.jsonl --epochs 1 --save-every 13 --max-len 2400 --min-free-pct 15` (about 39 steps) |
| Promotion rule | use the adapter only if LORA_RAG beats RAG on frozen recommendation accuracy **and** shows zero increase in raw unsafe delivery suggestions, forbidden claims and schema failures |

## Evidence that it did not run

- `$QWEN_WORKSPACE/docs/DELIVERY_LORA_EXPERIMENT.md`, whose status is "data and configuration ready … Results are filled in below only once they are measured". The results section only points to the transfer test.
- No `lora/out/rescue-delivery-*` directory exists, and no delivery training log is in `logs/`.
- `$QWEN_WORKSPACE/docs/BASE_VS_RAG_VS_LORA.md`: "Training a delivery adapter was deliberately not started, per your instruction to review first."

## What exists instead

The **transfer** test of the mission adapter on delivery ([QWN-019](QWN-019-delivery-frozen-eval.md)): 15/77 raw-correct, with collapse to conservative answers.

## Next time

If it is run, follow the pre-declared rule. Delivery decisions stay deterministic regardless.
