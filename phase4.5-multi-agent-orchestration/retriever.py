
"""
Retriever for the docs sub-agent: embed a query -> similarity search in
ChromaDB -> filter by threshold.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import hashlib
import json
import time

import chromadb
import voyageai
import voyageai.error
from dotenv import load_dotenv

load_dotenv()

CHROMA_PATH = Path(__file__).parent / "chroma_store"
COLLECTION_NAME = "pydantic_docs"

# Voyage's free tier is 3 req/min, and the eval sweep re-asks the same 19
# questions against every (collection, k, threshold) combination. Cache query
# embeddings on disk so a sweep costs 19 API calls instead of several hundred.
QUERY_CACHE_PATH = Path(__file__).parent / "eval" / ".query_cache.json"

vo = voyageai.Client()
chroma_client = chromadb.PersistentClient(path=str(CHROMA_PATH))

_query_cache: dict[str, list[float]] | None = None


def _cache_key(query: str) -> str:
    return hashlib.sha256(query.encode()).hexdigest()[:16]


def embed_query(query: str, use_cache: bool = True) -> list[float]:
    """Embed a query with input_type='query', memoised on disk."""
    global _query_cache
    if _query_cache is None:
        try:
            _query_cache = json.loads(QUERY_CACHE_PATH.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            _query_cache = {}

    key = _cache_key(query)
    if use_cache and key in _query_cache:
        return _query_cache[key]

    for attempt in range(3):
        try:
            embedding = vo.embed([query], model="voyage-3.5", input_type="query").embeddings[0]
            break
        except voyageai.error.RateLimitError:
            wait = 20 * (attempt + 1)
            print(f"rate limited, waiting {wait}s (attempt {attempt + 1}/3)")
            time.sleep(wait)
    else:
        raise RuntimeError("Voyage embedding failed after 3 rate-limit retries")

    _query_cache[key] = embedding
    QUERY_CACHE_PATH.parent.mkdir(exist_ok=True)
    QUERY_CACHE_PATH.write_text(json.dumps(_query_cache))
    return embedding


@dataclass
class Chunk:
    id: str
    doc_id: str
    position: int
    text: str
    distance: float


def retrieve(query: str, k: int = 5, threshold: float = 0.5,
             collection_name: str = COLLECTION_NAME) -> list[Chunk]:
    # 1. get the collection

    # 2. embed the query — wrap in a retry loop for RateLimitError, same
    #    backoff shape as ingest_docs.py. Note vo.embed takes a *list* and
    #    returns .embeddings, so you want element [0].

    # 3. collection.query(query_embeddings=[...], n_results=k,
    #    include=["documents", "metadatas", "distances"])

    # 4. zip documents/metadatas/distances/ids together and build Chunks,
    #    dropping anything below `threshold`.
    #
    #    Chroma gives you a *distance*, and you're storing with
    #    {"hnsw:space": "cosine"}. Your threshold is expressed as a
    #    similarity. What's the conversion, and — worth pausing on —
    #    which direction does the comparison go? Getting this inverted
    #    returns the k *worst* matches without raising anything.

    collection = chroma_client.get_collection(collection_name)
    query_embedding = embed_query(query)

    results = collection.query(query_embeddings=[query_embedding],
                               n_results=k,
                               include=["documents", "metadatas", "distances"])

    chunks = []
    for document,metadata, distance, _id in zip(results["documents"][0], results["metadatas"][0], results["distances"][0], results["ids"][0]):
        similarity = 1 - distance  
        if similarity >= threshold:
            chunk = Chunk(
                id=_id,
                doc_id=metadata["doc_id"],
                position=metadata["position"],
                text=document,
                distance=distance
            )
            chunks.append(chunk)

    return chunks


def main():
    test_queries = [
        "How do I stop a model from accepting extra fields?",
        "before validator vs after validator?",
        "What's the capital of France?",  # out-of-scope, should return little/nothing
    ]
    for query in test_queries:
        print(f"\nQuery: {query!r}")
        chunks = retrieve(query, k=5, threshold=0.3)
        if not chunks:
            print("  (no chunks passed the threshold)")
        for c in chunks:
            print(f"  [{c.distance:.3f}] {c.doc_id}#{c.position}: {c.text[:80]!r}")


if __name__ == "__main__":
    main()
