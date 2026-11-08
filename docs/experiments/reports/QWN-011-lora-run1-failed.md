# QWN-011: LoRA run1 (`rescue-lora-v0.2-run1`): failed at start-up

**Label:** REAL HARDWARE compute (Mac) · **Status:** FAILED · **Date:** 2026-11-07 19:19:02 ET

**In plain words.** The first full training attempt crashed before it took a single step, because one memory setting was given without its required partner setting.

## Objective

Run one epoch over v0.2 with an MPS memory cap, to protect the demo.

## Setup

| | |
|---|---|
| Hardware / software | as [QWN-010](QWN-010-lora-smoke.md) |
| Args | `--exp run1 --epochs 1 --save-every 22 --max-len 2400 --min-free-pct 15`; env `PYTORCH_MPS_HIGH_WATERMARK_RATIO=0.7` only |
| Data | v0.2 train, 707 rows, sha256 `1cb395d2…` |

## Result

`RuntimeError: invalid low watermark ratio 1.4`. No training steps and no checkpoints.

## Root cause

When only the high watermark is set, PyTorch MPS derives a default low watermark that is invalid relative to it. The traceback's 1.4 is that derived value. **Fix:** set both `PYTORCH_MPS_HIGH_WATERMARK_RATIO=0.7` and `PYTORCH_MPS_LOW_WATERMARK_RATIO=0.5`.

## Evidence

`$QWEN_WORKSPACE/logs/train_run1.log` (sha256 `87fb71e0…d4bf60`), `$QWEN_WORKSPACE/lora/out/rescue-lora-v0.2-run1/FAILED.json` (`46274a5e…2cefdb`): "failed at startup … no training steps, no checkpoints. Superseded by run1b."

## What it proves / does not prove

It proves only a configuration error. Nothing about the model.

## Next time

Validate the environment variables in a pre-flight check before loading the model.
