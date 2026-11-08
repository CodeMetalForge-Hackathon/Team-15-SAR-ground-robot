# QWN-026 / QWN-027: LiDAR pilot ckpt-0080: frozen LiDAR (E/F), frozen mission, and the independent generalization set

**Label:** SIMULATED; REAL HARDWARE compute on the Mac · **Status:** COMPLETE (assessment of record only; the checkpoint was already excluded); one crashed attempt (QWN-034, FAILED) · **Dates (ET):** 2026-11-08 E 02:34–02:43, F 02:44–02:55, mission 02:55–03:05, generalization 03:05–03:38

**In plain words.** Although no pilot snapshot passed selection, we tested the highest-scoring one, for the record, on the locked test sets and on a fresh set built from the LiDAR team's own fixtures. It produced the right format and many more correct answers. But it still suggested unsafe motion in several cases, missed stops, and became worse at the mission task it had previously learned.

## Setup

| | |
|---|---|
| Model | `rescue-lidar-lora-v0.1-pilot/ckpt-0080` on `Qwen/Qwen3.5-2B` @ `15852e8c`, HF bf16, greedy, max 600 tokens (same as [QWN-022](QWN-022-lidar-frozen-eval.md)) |
| E / F | frozen lidar-0.1, 60 advisories + 20 episodes; E = no RAG, F = RAG |
| Mission | frozen v0.2 tool steps, n = 230 (config D, RAG) |
| Generalization | `rescue_datasets/lidar_fixture_gen_v0.1/generalization.jsonl`, **n = 44**, sha256 `9431a021…f41b5c`, built from LiDAR agent fixtures @ `7e61595`, frozen and **never used for training or selection** |
| Chain | `$QWEN_WORKSPACE/logs/post_pilot_chain.sh` (E, F, mission), then individual `gen_*` runs |

## Results: frozen LiDAR (n = 60)

| Config | Schema | Action | Motion | Status | All four | Over-permissive | Unsupported | Stop recall (8) | Episodes completed by model | Median latency |
|---|---|---|---|---|---|---|---|---|---|---|
| E pilot, no RAG | 60 | 38 | 51 | 60 | 31 | 0 | 0 | 8/8 | 4/20 | 4.0 s |
| F pilot + RAG | 60 | 43 | 48 | 60 | 32 | **4** | 2 | **4/8** | 10/20 (1 over-permissive submission) | 5.8 s |

## Results: frozen mission (n = 230)

| | ckpt-0088 | pilot 0080 |
|---|---|---|
| Steps correct | 218 | **182** |
| Unsafe motion requests | 0/182 | **13/225** (gate rejected 15) |

This is a catastrophic-forgetting signal.

## Results: generalization set (n = 44)

| Config | Schema | All four | Over-permissive | Unsupported | Stop recall (11) | Median latency |
|---|---|---|---|---|---|---|
| HF base | 0 | 0 | 0 | 0 | 11 | 7.5 s |
| HF base + RAG | 0 | 0 | 0 | 0 | 9 | 9.2 s |
| ckpt-0088 | 0 | 0 | **10** | 0 | 6 | 5.4 s |
| ckpt-0088 + RAG | 0 | 0 | **4** | 0 | 10 | 7.0 s |
| **pilot 0080** | 40 | 32 | **5** | 0 | **6** | 4.1 s |
| **pilot 0080 + RAG** | 43 | 31 | **6** | 2 | **4** | 6.0 s |
| Ollama base (grammar) | 44 | 0 | 0 | 16 | 11 | 2.8 s |

The pilot's over-permissive cases were fixtures 15 (incorrect orientation), 17 (reflective/transparent), 22 (edge obstacle), 25 (mirror), 12 (stale timestamps) and 20 (unsafe forward clearance), which are exactly the cases it was meant to learn. The guard and the deterministic fallback replaced every one.

## Failures

**QWN-034 (FAILED attempt):** `logs/gen_ollama.log` (sha256 `0942e145…8aae27`, 02:55 ET) ends in `KeyError: 'scenario_id'` in `$QWEN_WORKSPACE/eval/run_eval_lidar.py` `advisory_eval`. The generalization rows have no `scenario_id`. A later run (`gen_ollama_base_norag.log`, 03:38) produced the Ollama row above. The Ollama + RAG generalization row is **NOT RUN**.

## Contamination statement

- The pilot's 150 targeted mission steps (dataset v0.3) were designed from `FAILURE_ANALYSIS_230.md`, an error analysis **of the frozen v0.2 test**.
- No test row was copied (0 ID and 0 prompt overlap, re-checked), but the failure categories informed training.
- This biases the pilot's 182/230 **upwards**, so the regression against 218 is if anything understated.
- The generalization set is independent: a different author (the LiDAR agent's fixtures), frozen, and unused for training or selection.

## Evidence

- `$QWEN_WORKSPACE/logs/lidar_E.log` (`e052d202…a1e69c`), `lidar_F.log` (`d0648bda…22f0bb`), `tools_test_lidarpilot.log` (`05e5c1cf…7f87c1`), `post_pilot_chain.log` (`35cf5be2…e7c15f`)
- `gen_hf_lidarpilot_ckpt-0080_norag.log` (`1a2c262e…431123`), `gen_hf_lidarpilot_ckpt-0080_rag.log` (`84980511…52ac37`)
- `$QWEN_WORKSPACE/results/v02_tools_summary_hf_lidarpilot_ckpt-0080_test.json` (`8b35a0ee…a357f9`)
- `$QWEN_WORKSPACE/docs/ADAPTER_COMPARISON.md` (update 03:50), `$QWEN_WORKSPACE/docs/SAFETY_REGRESSION.md`

## What it proves / does not prove

- **Proves:** a 640-example pilot teaches the format and the frequent cases, but not the safety rules on unseen geometry, and it damages the earlier task.
- **Does not prove:** anything on real LiDAR. All scans are simulated.

## Next time

Use per-task adapters, rehearsal with a mission regression gate, more geometry-failure coverage, and an Ollama + RAG generalization row.
