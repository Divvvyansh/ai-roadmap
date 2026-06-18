# Phase 3: AI Support Agent — RAG + Eval Harness

**Roadmap position:** Weeks 8–13 · ~32 hours  
**Status:** In Progress  
**Goal:** Build a support agent that answers grounded questions from a real document corpus, plus a working eval harness that measures whether retrieved chunks actually support the generated answer.
---

## What this project teaches

- Chunking strategy and embedding generation — the mechanics, not just calling an API
- ChromaDB locally → similarity search → relevance thresholds
- Building an eval harness: retrieval precision/recall, groundedness checks, hallucination detection
- Where RAG grounding constraints belong (in tool descriptions and system prompt, close to the decision point)

---

## Tech stack

| Layer | Choice |
|---|---|
| LLM | Claude API (direct calls, no LangChain) |
| Embeddings | `claude-haiku-4-5` or `voyage-3` via Anthropic |
| Vector DB | ChromaDB (local persistence) |
| API server | FastAPI |
| Eval | Custom harness — precision/recall + LLM-as-judge groundedness |
| Optional stretch | Supabase pgvector in place of ChromaDB |

---

## Project layout

```
phase3-rag-support-agent/
├── CLAUDE.md               ← this file
├── requirements.txt
├── .env.example
├── corpus/                 ← raw source documents
├── ingest.py               ← chunk, embed, and load into ChromaDB
├── retriever.py            ← similarity search + relevance threshold logic
├── agent.py                ← Claude-powered support agent (RAG tool loop)
├── api.py                  ← FastAPI server exposing the agent
├── eval/
│   ├── dataset.json        ← question/expected-answer pairs
│   ├── run_eval.py         ← retrieval + groundedness eval runner
│   └── results/            ← eval output logs
└── tests/
    └── test_retriever.py
```

---

## Key design rules

- **No LangChain or framework wrappers.** All retrieval and agent logic is direct API calls.
- **RAG grounding constraint lives in the tool description** (same principle as Phase 2 tool descriptions), not only in the system prompt.
- **Eval is first-class.** The harness runs independently of the agent — retrieval quality is measured separately from end-to-end answer quality.
- **Relevance threshold is explicit.** Chunks below the threshold are dropped before being injected into context, not silently passed through.

---

## Resources

- Claude Cookbook — RAG guide: `github.com/anthropics/claude-cookbooks/.../retrieval_augmented_generation/guide.ipynb`
- Claude Cookbook — Contextual retrieval guide: `platform.claude.com/cookbook/capabilities-contextual-embeddings-guide`
- ChromaDB docs — Getting Started: `docs.trychroma.com`
- Anthropic Academy — AI Fluency / Evaluations track (Skilljar)

---

## Instructions

- Explain most things you implement to the user to ensure they understand how context retreival works and how evaluation pipelines are built.
