# Phase 4, Week 1, Step 1 — containerize the Phase 3 RAG agent.
#
# Build context should be the repo root (or wherever lets you COPY from
# ../phase3-rag-support-agent) — check how you invoke `docker build` against
# that when you get to Step 3.

# 1. Base image — pick a slim Python image matching the version you've been
#    developing against (check your venv: `python --version`).
FROM python:3.9.6-slim

WORKDIR /app
RUN mkdir -p chroma_store

# 2. Copy ONLY the dependency manifest first, install, THEN copy the rest.
#    Why this order, given what Docker layer caching does with unchanged files?
COPY phase3-rag-support-agent/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 3. Copy the actual project code.
#    Which directories does the running service need? (fastAPI/, Agent/, RAG/...)
#    Which one — chroma_store/ — do you NOT want silently baked in, per the
#    framing above? Decide, and either COPY it or leave it out on purpose
COPY phase3-rag-support-agent/RAG/* ./RAG/
COPY phase3-rag-support-agent/Agent/* ./Agent/
COPY phase3-rag-support-agent/fastAPI/* ./fastAPI/


# 4. Run the server.
#    api.py lives in fastAPI/ and does a sys.path.insert to reach Agent/ —
#    given that, what's the right WORKDIR / module path for the uvicorn
#    invocation, and what port does the container need to EXPOSE?
WORKDIR /app/fastAPI
EXPOSE 5000
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "5000"]
