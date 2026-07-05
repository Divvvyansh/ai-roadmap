"""
Ingest pipeline (semantic chunking variant): load corpus -> split into sentences ->
embed sentences -> find breakpoints -> group into chunks -> embed chunks -> store in ChromaDB.

Stores into a separate collection (support_docs_semantic) so it can be compared
side-by-side against the fixed-size chunking collection (support_docs) from ingest.py.
"""
import os
import re
import time
from pathlib import Path
import numpy as np

import chromadb
import voyageai
import voyageai.error
from dotenv import load_dotenv

load_dotenv()

CORPUS_DIR = Path(__file__).parent / "corpus"
CHROMA_PATH = Path(__file__).parent / "chroma_store"
COLLECTION_NAME = "support_docs_semantic"

vo = voyageai.Client()
chroma_client = chromadb.PersistentClient(path=str(CHROMA_PATH))


def load_corpus(corpus_dir: Path) -> list[dict]:
    """Read every .md file in corpus_dir into {doc_id, text} dicts."""
    documents = []
    for path in sorted(corpus_dir.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        documents.append({"doc_id": path.stem, "text": text})
    return documents


def split_into_sentences(text: str) -> list[str]:
    """
    Split text into sentence-ish units.

    A regex split on '. '/'\n' is good enough here — we're not aiming for
    linguistic correctness, just small units small enough to compare
    consecutive embeddings on. Filter out empties from the split.
    """
    sentences = re.split(r"(?<=[.?!])\s+|\n+", text)
    return [s.strip() for s in sentences if s.strip()]


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


def find_breakpoints(sentences: list[str], sentence_embeddings: list[list[float]]) -> list[int]:
    """
    Decide which gaps between consecutive sentences are "topic breaks."

    Return a list of sentence indices i such that there should be a chunk
    boundary between sentence i and sentence i+1.

    Simple starter algorithm: for every consecutive pair of sentences, look at
    how dissimilar their embeddings are, then call a gap a "breakpoint" if
    it's unusually large *relative to the other gaps in this document* —
    not against some fixed global number.
    """
    distances = []
    for i in range(len(sentences)-1):
        denom = ((np.linalg.norm(sentence_embeddings[i])) * (np.linalg.norm(sentence_embeddings[i+1])))
        numerator = np.dot(sentence_embeddings[i], sentence_embeddings[i+1])
        sim = numerator / denom            ## cosine similarity b/w two vectors
        dist = 1 - sim
        distances.append(dist)
    
    breakpoints = []
    threshold = 0.65
    x = 1
    for j in range(len(distances)):
        if distances[j] > threshold:
            breakpoints.append(j)
        else:
            threshold = ((threshold*(x)) + distances[j])/(x+1)
            x = x + 1
    
    return breakpoints


def group_into_chunks(doc_id: str, sentences: list[str], breakpoints: list[int]) -> list[dict]:
    """
    Use the breakpoints to slice `sentences` into contiguous groups, and turn
    each group into the same {id, doc_id, position, text} shape ingest.py uses.
    """
    chunks = []
    start = 0
    position = 0
    boundaries = sorted(breakpoints) + [len(sentences) - 1]
    for boundary in boundaries:
        group = sentences[start : boundary + 1]
        if group:
            chunks.append({
                "id": f"{doc_id}_{position}",
                "doc_id": doc_id,
                "position": position,
                "text": " ".join(group),
            })
            position += 1
        start = boundary + 1
    return chunks


def chunk_document_semantically(doc_id: str, text: str) -> list[dict]:
    sentences = split_into_sentences(text)
    if len(sentences) <= 1:
        return [{"id": f"{doc_id}_0", "doc_id": doc_id, "position": 0, "text": text}]

    sentence_embeddings = embed_with_retry(sentences)
    breakpoints = find_breakpoints(sentences, sentence_embeddings)
    return group_into_chunks(doc_id, sentences, breakpoints)


def embed_and_store(chunks: list[dict], batch_size: int = 10, seconds_between_batches: int = 20) -> None:
    """
    Embed chunks in small batches and upsert them into the Chroma collection.

    Same rate-limit-aware batching as ingest.py — see that file for why these
    specific numbers (Voyage's free-tier 3 req/min, 10K tokens/min budget).
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
        chunks = chunk_document_semantically(doc["doc_id"], doc["text"])
        all_chunks.extend(chunks)
    print(f"  produced {len(all_chunks)} chunks")

    print("Embedding + storing in ChromaDB ...")
    embed_and_store(all_chunks)
    print("Done.")


if __name__ == "__main__":
    main()