# Phase 4 — MLOps Sprint

Taking the [Phase 3 RAG agent](../phase3-rag-support-agent) from a script you run locally to a monitored service. Same principle as every other phase: containerization, deployment, logging, and eval-drift tracking are done directly against Docker/AWS primitives — no Terraform, no managed PaaS abstraction — so the mechanics are understood before anything wraps them.

## What this covers right now

`RAGApp.dockerfile` packages the Phase 3 agent (`fastAPI/api.py`, `Agent/`, `RAG/`) into a container that serves `POST /ask` via `uvicorn`, with:

- Secrets injected at container **runtime** (`--env-file`), never baked into an image layer
- `chroma_store/` (the embedded index) **mounted from the host**, not copied into the image — so re-ingesting the corpus doesn't require a rebuild, and a rebuild never silently serves stale embeddings
- A build context scoped to the **repo root**, with a `.dockerignore` that keeps `.venv/`, `.git/`, and unrelated secrets (e.g. `calendar-agent/credentials.json`) out of what gets sent to the Docker daemon

## Prerequisites

- Docker Desktop installed and running (`docker info` should succeed, not just `docker --version`)
- The Phase 3 project present at `../phase3-rag-support-agent` relative to this folder, with:
  - `.env` populated with `ANTHROPIC_API_KEY` and `VOYAGE_API_KEY` (copy `.env.example` if you haven't)
  - `chroma_store/` already built by running `python RAG/ingest_semantic.py` from that project — the container reads this, it doesn't generate it

## Why the build context is the repo root, not this folder

The Dockerfile lives at `phase4-MLOps/RAGApp.dockerfile`, but it `COPY`s files from `../phase3-rag-support-agent/`. Docker's `COPY` can only reach files *inside* the build context — it can't follow `../` out of it. Rather than moving the Dockerfile to the repo root (which would break the phase-by-phase folder layout), the build context is set to the repo root explicitly, and the Dockerfile's location is passed separately via `-f`:

```bash
# run from the repo root
docker build -f phase4-MLOps/RAGApp.dockerfile -t rag-agent .
```

The trailing `.` is the context (repo root); `-f` just tells Docker where the Dockerfile file itself sits. This is also why `.dockerignore` lives at the **repo root**, not in `phase4-MLOps/` — Docker only reads a `.dockerignore` at the root of the build context.

## Build and run

From the repo root:

```bash
# 1. Build the image
docker build -f phase4-MLOps/RAGApp.dockerfile -t rag-agent .

# 2. Run it — secrets via --env-file, chroma_store mounted from the host
docker run -d --name rag-agent \
  --env-file phase3-rag-support-agent/.env \
  -v "$(pwd)/phase3-rag-support-agent/chroma_store:/app/chroma_store" \
  -p 8000:5000 \
  rag-agent

# 3. Confirm it's up
docker logs rag-agent
```

Then hit it like any other instance of the Phase 3 API:

```bash
curl -X POST http://localhost:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "How do I define a path parameter with type validation in FastAPI?"}'
```

You should get back a grounded answer with `docs_source` citations — same behavior as running `api.py` directly with `uvicorn`, just containerized. An out-of-scope question should get a clean refusal (`"No results found in the documentation."`), not a hallucinated answer.

Tear down:

```bash
docker rm -f rag-agent
```

## Verifying secrets never leaked into the image

`docker history` alone isn't sufficient proof — it only shows each layer's *instruction text*, not file contents, so it wouldn't catch a secret file that got `COPY`'d in some other way. Check both:

```bash
# No ENV instruction should reference the keys directly
docker history rag-agent

# No .env file should exist anywhere in the running container's filesystem
docker exec rag-agent find / -maxdepth 4 -iname "*.env"

# The keys SHOULD be present as runtime env vars (this is expected — they got
# in via --env-file at `docker run`, not baked into a layer)
docker exec rag-agent env | grep -E "ANTHROPIC|VOYAGE"
```

## Design notes

- **`chroma_store/` is mounted, not `COPY`'d.** If it were baked into the image, re-running `ingest_semantic.py` on the host would leave any already-running container serving the old embeddings — no error, no warning, just quietly stale answers on the next rebuild's absence. Mounting means the container always reads whatever's on disk right now.
- **Dependency install is a separate, earlier layer from the code copy.** `COPY requirements.txt .` + `pip install` happens before `COPY` of `RAG/`/`Agent/`/`fastAPI/`, so editing application code doesn't invalidate (and re-run) the dependency install layer on every rebuild.
- **`.dockerignore` excludes by reason.** Each entry maps to a concrete concern: `.env`/`*.json` are real secrets (the latter because `calendar-agent/credentials.json` and `token.json` live elsewhere in this monorepo and would otherwise ride along in the build context sent to the Docker daemon); `.venv/` (455MB) and `.git/` are excluded for context-transfer size/hygiene, not because they're sensitive.
