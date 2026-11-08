# QWN-012: LoRA run1b (`rescue-lora-v0.2-run1b`): out of memory at the first step

**Label:** REAL HARDWARE compute (Mac) · **Status:** FAILED · **Date:** 2026-11-07 19:19:18 ET

**In plain words.** With the memory cap fixed, the second attempt ran out of the memory it was allowed, at the very first training step. Computing the loss over the whole 248k-word vocabulary for every token was too big.

## Setup

As [QWN-011](QWN-011-lora-run1-failed.md), with both watermark ratios set (cap 12.43 GiB). Args: `--exp run1b --epochs 1 --save-every 22 --max-len 2400 --min-free-pct 15`.

## Result

`RuntimeError: MPS backend out of memory (MPS allocated: 9.04 GiB, other allocations: 1.85 GiB, max allowed: 12.43 GiB). Tried to allocate 1.69 GiB on shared pool.` This was raised in the backward pass. No checkpoints were written.

## Root cause

Full-vocabulary logits. For a sequence of length *L* the logits tensor is *L × 248,320*. At about 2k tokens in bf16 that is about 1 GB, plus its gradient and the softmax intermediates. **Fix (run2):** compute logits only for the *n* assistant positions (`logits_to_keep = n + 1`). The loss was verified equal to the Hugging Face masked loss (1.782 vs 1.782), and memory fell to about 7–8 GB.

## Evidence

`$QWEN_WORKSPACE/logs/train_run1b.log` (sha256 `389b64dd…5c32a8`), `$QWEN_WORKSPACE/lora/out/rescue-lora-v0.2-run1b/FAILED.json` (`423ade3a…741a02`).

## What it proves / does not prove

The memory model was wrong. Nothing about model quality.

## Next time

Estimate the logits memory, `L × V × bytes × (1 + grad)`, before choosing the cap.
