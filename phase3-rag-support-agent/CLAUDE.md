# Phase 3: AI Support Agent — RAG + Eval Harness

**Roadmap position:** Weeks 8–13 · ~32 hours  
**Status:** In Progress — Steps 1–5 done, Step 6 smoke-test in progress, Steps 7–10 (eval harness) next  
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
| Embeddings | Voyage AI (`voyage-3.5`, `input_type="query"` / `"document"`) |
| Vector DB | ChromaDB (local persistence at `chroma_store/`) |
| API server | FastAPI + uvicorn |
| Eval | Custom harness — precision/recall + LLM-as-judge groundedness |
| Optional stretch | Contextual embeddings (Step 11) |

---

## Project layout

```
phase3-rag-support-agent/
├── CLAUDE.md
├── requirements.txt
├── .env.example
├── corpus/                     ← FastAPI docs (40 markdown files)
├── ingest.py                   ← fixed-size chunking + Voyage embed → ChromaDB
├── ingest_semantic.py          ← semantic chunking variant
├── retriever.py                ← similarity search, threshold filter, retry logic
├── tool_schemas.py             ← search_docs tool definition
├── agent.py                    ← Claude tool-use loop, grounding, top_doc_ids
├── api.py                      ← FastAPI server: POST /ask → {answer, docs_source}
├── smoke_test_questions.txt    ← 10 manual smoke-test questions for Step 6
├── handoff.md                  ← session-to-session context and progress notes
├── eval/
│   ├── dataset.json            ← question/expected-answer pairs (Step 7, not started)
│   ├── run_eval.py             ← retrieval + groundedness eval runner (Step 8–9, not started)
│   └── results/                ← eval output logs
└── tests/
    └── test_retriever.py
```

---

## Key design rules

- **No LangChain or framework wrappers.** All retrieval and agent logic is direct API calls.
- **RAG grounding constraint lives in the tool description**, not only in the system prompt — close to the decision point where Claude decides what to assert.
- **Eval is first-class.** The harness runs independently of the agent — retrieval quality is measured separately from end-to-end answer quality. Never blend precision/recall and groundedness into one score.
- **Relevance threshold is explicit.** Chunks below the threshold are dropped before being injected into context, not silently passed through.
- **"I improved it" is a claim that needs a before/after number.** Commit `eval/results/baseline.json` before any tuning, `eval/results/final.json` after.

---

## How to coach Divyansh on this project

Divyansh is learning RAG and eval mechanics from first principles — the goal is for him to be able to explain every part of this system without notes. This means:

- **Scaffold functions with TODOs, don't write core logic.** Leave the algorithm parts (embedding calls, metric calculations, judge prompt logic) as `...` with guiding questions. He should write the non-trivial parts himself.
- **Distinguish coaching targets from reference knowledge.** Don't make him grep SDK source to find exception class names or Pydantic field types — that's API documentation, just give it. The coaching constraint applies to algorithm logic (the tool loop, the eval metrics, the chunking strategy), not to "what does this library raise."
- **Flag type mismatches at scaffold time**, not after. When scaffolding response models, prompt him to think about what type each field actually holds before he fills in the logic ("what type does `chunks_used` contain — is that directly Pydantic-serializable?").
- **Steps 7–10 are the core learning target of Phase 3.** The eval harness (precision@k, recall@k, LLM-as-judge groundedness) is where understanding matters most. Don't rush or hand-wave these.

---

## Environment

- Venv: `source /Users/divyansh/repos/ai-roadmap/.venv/bin/activate`
- Run server: `uvicorn api:app --reload` (from this directory)
- Pydantic version: v2.13.4

---

## Resources

- Claude Cookbook — RAG guide: `github.com/anthropics/claude-cookbooks/.../retrieval_augmented_generation/guide.ipynb`
- Claude Cookbook — Contextual retrieval guide: `platform.claude.com/cookbook/capabilities-contextual-embeddings-guide`
- ChromaDB docs — Getting Started: `docs.trychroma.com`
- Anthropic Academy — AI Fluency / Evaluations track (Skilljar)
