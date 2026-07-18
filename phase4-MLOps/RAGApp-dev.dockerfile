# Phase 4, Week 1, Step 1 — containerize the Phase 3 RAG agent.

FROM python:3.9-slim

WORKDIR /app
RUN mkdir -p chroma_store


COPY phase3-rag-support-agent/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt


COPY phase3-rag-support-agent/RAG/* ./RAG/
COPY phase3-rag-support-agent/Agent/* ./Agent/
COPY phase3-rag-support-agent/fastAPI/* ./fastAPI/


WORKDIR /app/fastAPI
EXPOSE 5000
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "5000"]
