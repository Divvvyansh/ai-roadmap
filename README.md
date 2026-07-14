# AI Engineering Roadmap

A self-directed, seven-phase, ~28-week (~190-hour) path into an entry-level AI engineering role — built on direct API calls and mechanical understanding rather than framework abstractions.

> "Skip premature abstractions. Learn the mechanics by building with direct API calls — frameworks come later, once the patterns underneath them are already understood."

The bet: understanding a pattern by hand-building it once (the Claude tool-use loop, query/document embedding asymmetry, chunking tradeoffs, sub-agent context isolation) is worth more than learning a framework's abstraction over it first. LangChain, LangGraph, and n8n are deliberately deferred until Phase 6, so they can be evaluated against something real instead of taken on faith.

## Roadmap at a glance

| Phase | Weeks | Hours | Project | Status |
| --- | --- | --- | --- | --- |
| [1 — Smart Expense Tracker](./phase1-expense-tracker) | 1–3 | ~18h | LLM-parsed expenses over FastAPI + Gunicorn | Done |
| [2 — NL Calendar Agent](./phase2-calendar-agent) | 4–7 | ~22h | Hand-rolled Claude tool-use loop over Google Calendar | Done |
| [3 — RAG Support Agent](./phase3-rag-support-agent) | 8–13 | ~32h | Chunking, retrieval, grounded generation + eval harness | Done |
| [4 — MLOps Sprint](./phase4-MLOps) | 14–17 | ~24h | Deploy & monitor the Phase 3 agent as a service | In progress |
| 4.5 — Multi-Agent Orchestration | 18–20 | ~16h | Orchestrator nesting the calendar + RAG agents as sub-agents | Not started |
| 5 — MCP Capstone: Life Admin Hub | 21–25 | ~30h | Calendar + RAG + expense tracker unified via MCP | Not started |
| 6 — Frameworks: LangGraph & n8n | 26–28 | ~14h | Re-implement one agent in LangGraph; wire it into n8n | Not started |

Each phase lives on its own branch while in progress; finished phases get merged into this branch as folders.

## Phase objectives

### Phase 1 — Smart Expense Tracker

**Closing API foundation gaps: auth, request/response handling, error states, persistence.**

- Structuring a FastAPI app with proper request/response models
- Serving with Gunicorn — process management basics
- Designing clean error states instead of raw stack traces
- First contact with the Claude API for unstructured-to-structured parsing

### Phase 2 — Natural Language Calendar Agent

**Agentic tool loops, built with direct Anthropic API calls — no LangChain.**

- Mechanical understanding of the tool-use loop: `tool_use` → execute → `tool_result` → continue
- Writing tool descriptions as prompts, not documentation
- Chaining as an emergent model decision, not explicit orchestration code
- Correct placement of human-in-the-loop confirmation (system prompt *and* tool description)
- Safe conversation-history trimming — avoiding the 400 Bad Request from orphaned `tool_result` blocks

### Phase 3 — AI Support Agent: RAG + Eval Harness

**Vector databases introduced contextually, exactly when the project needs them.**

- Chunking strategy and embedding generation — the mechanics, not just calling an API
- ChromaDB locally → similarity search → relevance thresholds
- Building an eval harness: retrieval precision/recall, groundedness checks, hallucination detection
- Where RAG grounding constraints belong — the same "close to the decision point" principle as tool descriptions

### Phase 4 — MLOps Sprint

**Deploy and monitor the Phase 3 RAG agent — taking it from script to service.**

- Containerizing the RAG agent for deployment
- Basic monitoring: latency, error rates, eval-score drift over time
- Logging tool calls and retrieval results for post-hoc debugging
- What "production-ready" actually requires beyond a working notebook

### Phase 4.5 — Multi-Agent Orchestration

**Sub-agent delegation and context management — via direct API calls, before any framework.**

- Orchestrator/worker pattern: a "delegate" tool whose implementation is itself a full nested agent loop
- Context isolation vs. sharing: does a sub-agent get full parent history, or a scoped summary?
- Result surfacing: collapsing a sub-agent's internal multi-turn loop into a single `tool_result` block
- Failure propagation: what the orchestrator sees when a sub-agent errors several levels deep

### Phase 5 — MCP Capstone: Life Admin Hub

**Connecting all prior projects through the Model Context Protocol.**

- Exposing the calendar agent, RAG agent, and expense tracker as MCP servers
- Composing them into one coherent assistant via MCP rather than ad-hoc glue code
- Applying Phase 4.5's orchestration patterns to a real multi-project system
- End-to-end integration testing across services with different deployment states

### Phase 6 — Frameworks: LangGraph & n8n

**Now that the mechanics are second nature, learn the abstractions that wrap them.**

- Mapping LangGraph's graph/state/node abstractions onto the tool loop already built by hand
- Recognizing what LangGraph buys you (state persistence, visualization, checkpointing) versus what it hides
- n8n as a visual automation layer — connecting existing agents into workflows without glue code
- Judging, case by case, when a framework is worth the abstraction cost in real projects

## Guiding principles

What carries through every phase:

- **Mechanics before abstraction.** Every pattern (tool loops, RAG, orchestration) is built once with direct API calls before any framework is introduced. Frameworks are learned last, in Phase 6, once there's a hand-built mental model to compare them against.
- **Contextual introduction.** Tools like vector databases are introduced exactly when a project needs them, not front-loaded — this is why ChromaDB lives in Phase 3, not Phase 1.
- **Confirmation at the decision point.** Constraints (human-in-the-loop confirmation, RAG grounding rules) belong as close to the model's decision point as possible — in tool descriptions, not just system prompts.
- **Credentials vs. self-direction.** Paid courses are skipped in favor of free, high-quality resources unless a specific credential has clear employer value.

The success bar for each phase isn't "does it run" — it's being able to explain *why* it works, without notes.

## Skip / defer / learn decisions

| Topic | Decision |
| --- | --- |
| LangChain / LangGraph | Deferred to Phase 6 — abstracts away the tool-loop mechanics Phases 2–4.5 are designed to teach directly |
| n8n | Deferred to Phase 6 — a productivity multiplier for someone who already has working agents to connect, not a foundational tool |
| Vector databases | Learned in Phase 3 — introduced contextually when the RAG project creates a real need for similarity search |
| Multi-agent orchestration | Learned in Phase 4.5 — mechanical, hand-built sub-agent delegation and context management, before any orchestration framework |

## Stack

Anthropic Claude API and Voyage AI direct via SDK (no LangChain/LlamaIndex), ChromaDB for vector storage, FastAPI for serving. AWS (ECS Fargate, Secrets Manager, CloudWatch, IAM) enters in Phase 4; Bedrock is read-about-only, not built-with.
