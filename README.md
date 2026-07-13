# AI Engineering Roadmap

A self-directed, ~28-week path into an entry-level AI engineering role: real projects, each one building a production AI engineering skill — agents, RAG, evals, MLOps, orchestration — from mechanical first principles before reaching for the framework that normally hides them.

The bet: understanding a pattern by hand-building it once (the Claude tool-use loop, query/document embedding asymmetry, chunking tradeoffs) is worth more than learning a framework's abstraction over it first. LangChain, LlamaIndex, and n8n are deliberately deferred until Phase 6, so they can be evaluated against something real instead of taken on faith.

## Phases

| Phase | Project | Status | Branch |
|---|---|---|---|
| 1 | [Expense Tracker](https://github.com/divvvyansh/ai-roadmap/tree/ph1-expense_tracker/expense%20tracker) — LLM-powered CLI that extracts structured expense data from natural language and answers queries over it | Done | `ph1-expense_tracker` |
| 2 | [Calendar Agent](./calendar_agent) — natural-language Google Calendar assistant on a hand-rolled Claude tool-use loop | Done | `phase2_agents` |
| 3 | RAG Support Agent — chunking, Voyage embeddings, ChromaDB retrieval, grounded generation, and an eval harness (recall@k, groundedness, refusal correctness tracked separately) | Done | `ph3-RAG` |
| 4 | MLOps / AWS — ECS Fargate, Secrets Manager, CloudWatch, IAM | Not started | — |
| 5 | Multi-agent orchestration | Not started | — |
| 6 | MCP capstone + framework evaluation (LangChain/LangGraph/n8n) | Not started | — |

Each phase lives on its own branch while in progress; finished phases get merged in as folders. `calendar_agent/` is the only phase currently merged into this branch.

## Why hand-built, not framework-first

Every phase targets one specific mechanical thing a framework would otherwise hide:

- **Phase 2** — the tool-use loop itself: send messages + tool schemas to Claude, execute locally on `stop_reason == "tool_use"`, append the result, loop until `end_turn`. No agent framework, so the control flow is fully visible.
- **Phase 3** — the asymmetry between query and document embeddings, chunking strategy tradeoffs, and why retrieval quality needs its own eval metric instead of being folded into a single "accuracy" number.

The success bar for each phase isn't "does it run" — it's being able to explain *why* it works, without notes.

## Stack

Anthropic Claude API and Voyage AI direct via SDK (no LangChain/LlamaIndex), ChromaDB for vector storage, FastAPI for serving. AWS (ECS Fargate, Secrets Manager, CloudWatch, IAM) enters in Phase 4.