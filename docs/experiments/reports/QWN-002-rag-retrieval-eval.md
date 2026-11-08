# QWN-002 / QWN-003: RAG retrieval evaluations (general, LiDAR, delivery)

**Label:** SYNTHETIC queries over the real corpus · **Status:** COMPLETE · **Dates (ET):** general 2026-11-07 18:15; delivery 19:39; LiDAR 23:00 (result-file times)

**In plain words.** Before letting the model read reference text, we checked that the search engine finds the right documents. For 20 hand-written questions, SQLite's built-in full-text search found a relevant document in the top 4 for 18 of them. It did as well as or better than a neural embedding model, and it needs nothing installed.

## Objective

Choose a retriever (H: lexical BM25 is at least as good as embeddings on this corpus), then check retrieval on the LiDAR and delivery collections.

## Setup

| | |
|---|---|
| Hardware | Mac M4 Pro |
| Software | `$QWEN_WORKSPACE` `$QWEN_WORKSPACE/eval/rag_eval.py`; corpus v0.2.0 (34 docs, 202 chunks) for the comparison; later collections for LiDAR (corpus 47/253) and delivery (43/233) |
| Retrievers | SQLite FTS5 BM25 (porter unicode61); `rank_bm25`; MiniLM-L6-v2 embeddings; hybrid RRF |
| Data | 20 general queries (the 7 from the project brief + 13 ground-robot/sensor questions); 12 LiDAR; 12 delivery. Gold `doc_id`s labelled by hand **before** the run |
| Ground truth | Hand labels (single author) |

## Metrics

- **hit@4**: does the model see at least one relevant document, given the 4-chunk context budget?
- **recall@4**: the fraction of relevant documents retrieved.
- **MRR@10**: how high the first relevant document ranks.
- Build and query time.

## Results

| Retriever (general, n=20) | hit@4 | recall@4 | MRR@10 | Build | Query median |
|---|---|---|---|---|---|
| **FTS5 BM25** | **18/20** | **0.762** | **0.852** | 2.9 ms | 0.17 ms |
| rank_bm25 | 18/20 | 0.721 | 0.758 | 4.2 ms | 0.25 ms |
| MiniLM-L6-v2 | 18/20 | 0.729 | 0.771 | 1,095 ms (+237 ms load) | 7.1 ms |
| Hybrid RRF | 18/20 | 0.750 | 0.762 | — | — |

| Collection | n | hit@4 | Notes |
|---|---|---|---|
| LiDAR | 12 | **11/12** | The camera–LiDAR *conflict* query missed |
| Delivery | 12 | **11/12** | |

## Evidence

`$QWEN_WORKSPACE/results/rag_eval.json` (sha256 `f518a5b9…5f1aeab`), `rag_eval_lidar.json` (`8ca7824b…7ef23d`), `rag_eval_delivery.json` (`770213d1…a5d02`); `$QWEN_WORKSPACE/docs/RAG_EVALUATION.md`, `LIDAR_RAG_SOURCES.md`, `SUPPLY_DELIVERY_RAG.md`.

## Limitations and confounders

- Small n.
- The same author wrote the labels and the team UGV guide, so lexical overlap may favour BM25.
- The comparison was run on 34 documents. The corpus is now 47 and has not been re-compared.

## Reproducibility

`python3 -B -m eval.rag_eval` in the private workspace. The output is deterministic, with no model involved.

## What it proves / does not prove

- **Proves:** on this corpus and these queries, a stdlib lexical retriever is adequate and fast enough for the Pi.
- **Does not prove:** retrieval quality on real operator questions, or that retrieved text improves answers. See [QWN-001](QWN-001-v01-frozen-eval-ollama.md) and [QWN-019](QWN-019-delivery-frozen-eval.md); for delivery, RAG made claims worse.

## Next time

Use an independent query author, re-run on the 47-document corpus, and add a per-query failure analysis.
