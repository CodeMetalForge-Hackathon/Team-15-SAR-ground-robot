# QWN-004 / QWN-005: Qwen runtime benchmarks (Mac Ollama; Raspberry Pi 5 llama.cpp)

**Label:** REAL HARDWARE (inference only; the inputs were fixed benchmark prompts, not robot sensors) · **Status:** COMPLETE · **Dates (ET):** Mac 2026-11-07 17:45–17:48; Pi 2026-11-07 18:46

**In plain words.** We timed how long one rescue advisory takes. On the Mac it takes about 1.7 seconds. On the Raspberry Pi it takes about 48 seconds, so the Mac runs Qwen.

## Objective

Choose the host and runtime for interactive advisories (H: the Pi is too slow for interactive use).

## Setup

| | Mac | Pi |
|---|---|---|
| Hardware | M4 Pro, 24 GB, 14 cores | Raspberry Pi 5, 16 GB |
| Runtime | Ollama 0.40.2 (Metal) | llama.cpp v0.9.0 (`cd959ba`, built on the Pi), CPU, 3 threads, `-c 8192`, `nice` |
| Models | `qwen3.5:2b-q4_K_M`, `qwen3.5:2b` (mxfp8), `qwen3.5:0.8b` (mxfp8) | `Qwen3.5-2B-Q4_K_M.gguf` (unsloth @ `f6d5376b`) + `mmproj-F16.gguf` |
| Procedure | `$QWEN_WORKSPACE/bench/bench_model.py`; other models unloaded first; 10 advisory runs; sustained 20 | 3 speed runs + 3 advisory runs (config C, about 1,965 prompt tokens); thermal read before and after |
| Conditions | Camera stream idle | Camera stream idle; server stopped afterwards |

## Results

| Host / model | Advisory latency (each run) | Valid | Resident memory | Other |
|---|---|---|---|---|
| Mac 2B Q4_K_M | 2.56, 1.65, 1.73, 1.66, 1.67, 1.83, 1.67, 1.67, 1.70, 1.72 s | 10/10 | 2,231 MiB | decode 123–126 tok/s (doc); no thermal warning |
| Mac 2B mxfp8 | 3.07, then ≈2.27 s ×9 | 10/10 | 2,848 MiB | |
| Mac 0.8B mxfp8 | 1.20–2.88 s | 10/10 | 1,194 MiB | |
| **Pi 5, 2B Q4_K_M** | **97.8 s (cold), 47.6 s, 46.8 s** | 3/3 | 3,420–3,645 MiB | decode 7.6–8.1 tok/s; 55.4 → 70.3 °C; `throttled=0x0`; 0 thinking leaks |

Sustained Mac run: the last-5 median was 1.65 s (2B Q4). The first-5 median was higher (4.55 s) in runs started right after the image test, cause not confirmed (`MODEL_SELECTION.md`).

## Evidence

`$QWEN_WORKSPACE/results/bench_mac-m4pro_qwen3.5_2b-q4_K_M.json` (sha256 `acb0c604…4cb49`), `bench_mac-m4pro_qwen3.5_2b.json`, `bench_mac-m4pro_qwen3.5_0.8b.json`, `bench_pi5_qwen3.5-2b-q4_k_m.json` (`4464cdaa…62275`); `$QWEN_WORKSPACE/docs/QWEN_DEPLOYMENT.md`, `$QWEN_WORKSPACE/docs/MODEL_SELECTION.md`.

## Limitations

- Small n: 10 Mac runs, 3 Pi runs.
- Ollama prompt caching makes Mac prefill numbers unreliable.
- `MODEL_SELECTION.md` §4 still says "Pi benchmark: not measured". It was written before the 18:46 run and is superseded by `QWEN_DEPLOYMENT.md`.
- The Pi was not running the camera at the same time.

## What it proves / does not prove

- **Proves:** the Mac is about 28× faster per advisory than the Pi CPU for this model. The Pi *can* run it correctly.
- **Does not prove:** accuracy (latency only), or behaviour under concurrent camera load on the Pi.

## Next time

Measure the Pi under camera load and with shorter prompts (config B, estimated 25–30 s but not measured), and add the 0.8B model to a frozen accuracy set.
