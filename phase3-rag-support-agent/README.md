# RAG Support Agent

A retrieval-augmented support agent over FastAPI's documentation, built with direct API calls — no LangChain, no LlamaIndex. Chunking, embedding, retrieval thresholding, the tool-use loop, and the eval harness are all hand-rolled, on the same principle as [Phase 2](../calendar_agent): understand the mechanics before adopting the framework that hides them.

Phase 3 of a self-directed AI engineering roadmap. The deliverable isn't just an agent that answers questions — it's an eval harness that proves, with numbers, whether the answers are actually grounded in the retrieved documents.

## What it does

- **Answers FastAPI questions grounded in the actual docs** — the agent must call `search_docs` before answering, and its tool description carries the grounding constraint ("only assert facts present in the retrieved chunks; if none support the answer, say so")
- **Declines out-of-scope questions** instead of hallucinating an answer when nothing relevant is retrieved
- **Serves over HTTP** — `POST /ask` via FastAPI, returning the answer plus which source docs it drew from
- **Measures retrieval and groundedness separately** — precision@k / recall@k are computed independently from an LLM-as-judge groundedness check, never blended into one score

## Architecture

```text
┌──────────────┐      ┌────────────────┐      ┌──────────────────┐
│ RAG/ingest*.py│─────▶│  ChromaDB       │◀────│ RAG/retriever.py  │
│ chunk + embed │      │ (chroma_store/) │      │ embed query,      │
│ (Voyage AI)   │      │  local persist  │      │ threshold filter  │
└──────────────┘      └────────────────┘      └─────────┬─────────┘
                                                          │
┌──────────────┐      ┌────────────────┐                │
│ fastAPI/api.py│─────▶│ Agent/agent.py  │────────────────┘
│ POST /ask     │◀─────│ Claude tool loop │
└──────────────┘      └────────────────┘
                                │
                        ┌───────▼────────┐
                        │ eval/run_eval.py │
                        │ eval/run_ground- │
                        │ ness_eval.py     │
                        │ precision/recall │
                        │ + LLM-as-judge   │
                        └────────────────┘
```

| Path | Responsibility |
| --- | --- |
| `RAG/ingest.py` | Fixed-size chunking (with overlap) → Voyage embeddings → ChromaDB |
| `RAG/ingest_semantic.py` | Semantic chunking variant, stored in a separate collection for side-by-side comparison |
| `RAG/retriever.py` | Embeds the query with `input_type="query"` (documents were embedded with `input_type="document"` — Voyage prepends different instructions per side, so getting this backwards degrades relevance silently), runs ChromaDB similarity search, drops chunks below the distance threshold |
| `Agent/tool_schemas.py` | `search_docs` tool definition — the grounding constraint lives here, not just in the system prompt |
| `Agent/agent.py` | The tool-use loop: forces a `search_docs` call on the first turn, injects retrieved chunks as `tool_result`, tracks which chunks/docs contributed to the final answer |
| `fastAPI/api.py` | `POST /ask` → `{answer, docs_source}` |
| `eval/run_eval.py` | Retrieval metrics: precision@k, recall@k against hand-labeled relevant chunks |
| `eval/run_groundedness_eval.py` | LLM-as-judge: does the answer assert anything not supported by the retrieved chunks? |

## Eval results

Retrieval quality and groundedness are tracked as separate numbers, not one blended score — a change that improves one can regress the other, and collapsing them would hide that.

| Run | k | threshold | mean precision | mean recall | groundedness |
| --- | --- | --- | --- | --- | --- |
| Baseline | 5 | 0.50 | 0.611 | 0.599 | 1.00 |
| Final | 8 | 0.50 | 0.528 | 0.703 | 1.00 |

Raising `k` from 5→8 traded precision for recall (fewer of the retrieved chunks are relevant, but a higher share of the relevant chunks get retrieved at all) while groundedness held at 100% — the agent never asserted anything the retrieved chunks didn't support, across both configurations. Full per-question results are in `eval/results/`.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env   # fill in ANTHROPIC_API_KEY and VOYAGE_API_KEY
```

`corpus/` (39 FastAPI doc pages, ~300KB) is committed, so the vector store is reproducible straight from a clone — build it, then run the server:

```bash
python RAG/ingest_semantic.py     # chunk + embed corpus/ into chroma_store/
cd fastAPI && uvicorn api:app --reload
```

```bash
curl -X POST http://localhost:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "How do I add a background task to a path operation?"}'
```

Run the eval harness:

```bash
python eval/run_eval.py               # retrieval precision/recall
python eval/run_groundedness_eval.py  # LLM-as-judge groundedness
```

> `chroma_store/` (the embedded index) is gitignored — it's a derived artifact of `corpus/` + `ingest_semantic.py`, regenerate it locally rather than committing binary index files.

## Design notes

- **Grounding constraint lives in the tool description, close to the decision point** — where Claude decides what to assert — rather than only in the system prompt.
- **Relevance threshold is explicit and applied before injection**: chunks below the cosine-similarity threshold are dropped in `retriever.py`, not passed through and left for the model to ignore.
- **Query vs. document embedding asymmetry**: `ingest_semantic.py` embeds chunks with `input_type="document"`, `retriever.py` embeds the query with `input_type="query"` — Voyage optimizes each differently, and this is easy to get backwards without any error being raised.
- **"Improved" is a before/after number**: `eval/results/baseline.json` was committed before tuning `k`/threshold, `final_groundedness.json` after — see the table above.
