"""
Ingest pipeline: load corpus -> chunk -> embed -> store in ChromaDB.

"""
import os
import time
from pathlib import Path

import chromadb
import voyageai
import voyageai.error
from dotenv import load_dotenv

load_dotenv()

CORPUS_DIR = Path(__file__).parent / "corpus"
CHROMA_PATH = Path(__file__).parent / "chroma_store"
COLLECTION_NAME = "support_docs"
 
vo = voyageai.Client()  
chroma_client = chromadb.PersistentClient(path=str(CHROMA_PATH))


def load_corpus(corpus_dir: Path) -> list[dict]:
    """Read every .md file in corpus_dir into {doc_id, text} dicts."""
    documents = []
    for path in sorted(corpus_dir.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        documents.append({"doc_id": path.stem, "text": text})
    return documents


def chunk_document(doc_id: str, text: str, max_chars: int = 1000, overlap: int = 150) -> list[dict]:
    
    chunks =[]
    start = 0
    position = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        chunk_text = text[start:end]
        chunks.append({
            "id": f"{doc_id}_{position}",
            "doc_id": doc_id,
            "position": position,
            "text": chunk_text,
        })
        position += 1
        if end == len(text):
            break
        start += max_chars - overlap
    return chunks


def embed_with_retry(texts: list[str], max_retries: int = 5) -> list[list[float]]:
    """Call Voyage's embed API, retrying with exponential backoff on rate limits."""
    for attempt in range(max_retries):
        try:
            return vo.embed(texts, model="voyage-3.5", input_type="document").embeddings
        except voyageai.error.RateLimitError:
            wait = 20 * (attempt + 1)  # 20s, 40s, 60s, ...
            print(f"  rate limited, waiting {wait}s (attempt {attempt + 1}/{max_retries})")
            time.sleep(wait)
    raise RuntimeError("Exceeded max retries on Voyage rate limit")


def embed_and_store(chunks: list[dict], batch_size: int = 10, seconds_between_batches: int = 20) -> None:
    """
    Embed chunks in small batches and upsert them into the Chroma collection.

    batch_size and seconds_between_batches are tuned for Voyage's no-payment-method
    tier: 3 requests/min, 10K tokens/min. A small batch keeps each request's token
    count well under the per-minute budget, and the sleep keeps us under 3 req/min.
    """
    collection = chroma_client.create_collection(name=COLLECTION_NAME, metadata={"hnsw:space": "cosine"})

    for i in range(0, len(chunks), batch_size):
        batch = chunks[i : i + batch_size]
        texts = [c["text"] for c in batch]
        embeddings = embed_with_retry(texts)

        collection.add(
            ids=[c["id"] for c in batch],
            embeddings=embeddings,
            documents=texts,
            metadatas=[{"doc_id": c["doc_id"], "position": c["position"]} for c in batch],
        )
        print(f"  embedded + stored chunks {i}-{i + len(batch)}")

        if i + batch_size < len(chunks):
            time.sleep(seconds_between_batches)


def main():
    print(f"Loading corpus from {CORPUS_DIR} ...")
    documents = load_corpus(CORPUS_DIR)
    print(f"found {len(documents)} documents")

    all_chunks = []
    for doc in documents:
        chunks = chunk_document(doc["doc_id"], doc["text"])
        all_chunks.extend(chunks)
    print(f"  produced {len(all_chunks)} chunks")

    print("Embedding + storing in ChromaDB ...")
    embed_and_store(all_chunks)
    print("Done.")


if __name__ == "__main__":
    main()
