# QWN-018: Runtime comparison audit: why base Qwen scored 0/230 on HF but 39–56/230 on Ollama

**Label:** SIMULATED/SYNTHETIC prompts (REAL HARDWARE compute on the Mac) · **Status:** COMPLETE (E6 not possible) · **Date:** 2026-11-07, about 22:42–22:50 ET (`runtime_audit.json`, `v02_tools_summary_audit_prefix_*` mtimes; commit `96c20cd`)

**In plain words.** The same base model looked useless in one runtime (0/230) and partly competent in another (39–56/230). We tested why. The difference is almost entirely Ollama's grammar, which forces the output into the right shape. Without it, the base model does not produce our format in either runtime. The fine-tuned adapter does not need the grammar.

## Objective

Explain the cross-runtime gap and define a fair comparison rule.

## What was identical and what differed

- **Identical:** `TOOL_SYSTEM` and `render_tool_user` byte-for-byte, the RAG context, the scorer (real safety gate), thinking off, the 200-token output limit, and the parser.
- **Different:**

| Factor | Ollama | HF |
|---|---|---|
| Weights | Q4_K_M GGUF | bf16 safetensors (`15852e8c`) |
| Chat template | Ollama's built-in Qwen3.5 renderer | the model's `chat_template.jinja` |
| Decoding | temperature 0, seed 7, **JSON-schema grammar**, model defaults (`presence_penalty 1.5`, `top_k 20`, `top_p 0.95`) | greedy, no penalties, **no grammar** |

## Experiments and results

| ID | Experiment | n | Result |
|---|---|---|---|
| E1 | What HF base emitted | 230 | 97 valid JSON objects, all keyed `final_recommended_action` (65 with `reason`); never a `step` key; 133 invalid or truncated. (Raw outputs were saved truncated to 400 characters, so some long outputs may be miscounted as invalid) |
| E2 | Ollama base **with vs without** the grammar | first 60 frozen steps | **Without: 0/60 parseable, 0/60 correct**; with: 60/60 parseable, **11/60 correct** |
| E3 | Lenient key-mapping re-score of HF base | 230 | **6/230** correct |
| E5 | HF with a forced prefix `{"step":"` | 60 | base **0/60** (put an action name in `step`); ckpt-0088 **60/60** (also 60/60 without the prefix) |
| E6 | Load ckpt-0088 into Ollama | — | **Not possible**: Ollama 0.40.2 says "LoRA adapters are no longer supported". Needs merge + GGUF conversion (llama.cpp tooling not installed on the Mac) |

## Conclusions

1. The grammar accounts for the whole format gap. Ollama's 39–56/230 is **grammar-assisted**.
2. The base model's *decisions* are also weak (6/230 with lenient mapping).
3. The adapter does not depend on output forcing.
4. The fairest available comparison, adapter without grammar vs base with grammar, favours the base model, and the adapter still leads 218 vs 56.
5. Quantization and sampler defaults were **not isolated**.

**Normalization rule adopted:** report `runtime`, `weights`, `grammar` and `sampler` for every number; never compare a grammar-constrained number with an unconstrained one silently; keep the original numbers.

## Evidence

`$QWEN_WORKSPACE/results/runtime_audit.json` (sha256 `6f483e35…fbcaed`), `results/v02_tools_C_audit_prefix_{base,lora}_test.jsonl`, `$QWEN_WORKSPACE/docs/RUNTIME_COMPARISON_AUDIT.md`.

## Limitations

E2 and E5 used the first 60 steps only. E1's truncation caveat applies.

## What it proves / does not prove

- **Proves:** constrained decoding explains the base model's apparent format competence. It also identifies the concrete blocker to serving the adapter in production.
- **Does not prove:** the adapter's score *with* a grammar, or the quantization cost.

## Next time

Merge the adapter, convert it to GGUF, and run all configurations in one runtime with the same grammar and sampler, or add a JSON-grammar decoder to HF (for example `outlines`). Both require approved external installs.
