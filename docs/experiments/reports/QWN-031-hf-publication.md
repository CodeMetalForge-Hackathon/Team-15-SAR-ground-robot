# QWN-031: Hugging Face publication and verification of the ckpt-0088 adapter

**Label:** Publication / integrity check (no model evaluation) · **Status:** COMPLETE · **Dates (ET):** 2026-11-08: private upload by 04:41 (Qwen-workspace commit `345f427`); pre-public review 04:52 (`df42fe8`); made public 04:56 (`1dc877a`)

**In plain words.** We uploaded the one adapter that passed selection to Hugging Face. We checked that the uploaded file is byte-for-byte the one we tested, and that loading it produces the expected first step. The owner then made it public. Nothing else was uploaded: no base model, no training data, no private checkpoints.

## What was published

| | |
|---|---|
| Repository | `huggingface.co/MOHDMUBASHIR/team15-qwen3.5-2b-rescue-mission-lora` |
| Revisions | `3019854048623a7f686828358e743d2a30d2f1f2` (first private upload) → **`21013d45c591616089dd10685268495388cf412a`** (after model-card fixes; made PUBLIC) |
| Adapter | `rescue-lora-v0.2-run2/ckpt-0088`; `adapter_model.safetensors` 62,566,192 bytes, SHA-256 `a76f837183bdeb9059c74a1d92e38fe485c7e13e5dc05c4cf5ca6c375eb7ba2b` |
| Other files | `adapter_config.json` (1,309 B, `d7939afc…a048ea`), README.md, LICENSE, NOTICE (credits Qwen3.5-2B, Apache-2.0, and Co-GLANCE, CC BY 4.0), `load_example.py`, SHA256SUMS, `prompts/` (3 files) |
| Not uploaded | base weights, training data, the RAG corpus, benchmarks, LiDAR pilot checkpoints, other run2 checkpoints, credentials, camera evidence |

## Verification steps (as recorded in `$QWEN_WORKSPACE/docs/PUBLICATION_RECORD.md`)

1. The remote LFS SHA-256 equals the local value.
2. A fresh snapshot download passes `shasum -c SHA256SUMS`: 8/8 at the first revision, 9/9 after the review.
3. Loading by repo ID + revision returns `{"step":"TOOL_CALL","tool":"get_robot_state","args":{}}`.
4. After it was made public: the anonymous model page returns 200, the API reports `private: false`, and an anonymous download passes 9/9 checksums and returns the same step.

The local staging copy's `SHA256SUMS` has sha256 `d515292a…b68871` (`$ADAPTER_BACKUPS/../hf-staging/…`). The local backups passed 20/20 checksums (`SHA256SUMS-originals.txt`).

## Model-card fixes in the pre-public review

- the error breakdown (3 reasoning + 2 procedure + 2 timeout-stop + 4 non-identifiable + 1 scorer);
- the RAG reproducibility note ("every mission result was measured with RAG; without RAG it was not measured; the corpus is not included");
- the delivery result with RAG (12/77).

## Repository side

[docs/qwen/MODEL.md](../../qwen/MODEL.md) links the public adapter (revision `21013d4`). It was merged in PR #13 at 2026-11-08 12:10:57 UTC (author `machackgo`). `.gitignore` excludes `*.safetensors`, `*.gguf` and `lora/out/`.

## Limitations

The published score (218/230) depends on the private RAG corpus and on synthetic benchmarks. A reader cannot reproduce it from the HF repository alone, and the model card says so.

## What it proves / does not prove

- **Proves:** the published artifact is exactly the evaluated checkpoint and loads correctly.
- **Does not prove:** that the adapter is fit for deployment. It is **not deployed** ([08 §5](../../08_QWEN_MODEL.md#5-why-the-live-demo-uses-base-qwen--rag)).
