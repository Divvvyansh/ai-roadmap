"""
Retriever: embed a query -> similarity search in ChromaDB -> filter by distance threshold.
"""
from dataclasses import dataclass
from pathlib import Path
import time
import voyageai.error
import chromadb
import voyageai
from dotenv import load_dotenv

load_dotenv()

CHROMA_PATH = Path(__file__).parent / "chroma_store"
COLLECTION_NAME = "support_docs"

vo = voyageai.Client()
chroma_client = chromadb.PersistentClient(path=str(CHROMA_PATH))


@dataclass
class Chunk:
    id: str
    doc_id: str
    position: int
    text: str
    distance: float


def retrieve(query: str, k: int = 5, threshold: float = 0.5) -> list[Chunk]:
    """
    Embed `query`, fetch the k nearest chunks from ChromaDB, and drop any
    chunk whose distance exceeds `threshold`.
    """
    collection = chroma_client.get_collection(COLLECTION_NAME)

    for attempt in range(3):
        try:
            query_embedding = vo.embed([query], model="voyage-3.5", input_type="query").embeddings[0]
        except voyageai.error.RateLimitError:
            wait = 20 * (attempt + 1)  
            print(f"rate limited, waiting {wait}s (attempt {attempt + 1}/{3})")
            time.sleep(wait)

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
        "How do I add a background task to a path operation?",
        "How do I validate query parameters with regex?",
        "What's the capital of France?",  # out-of-scope, should return little/nothing
    ]
    for query in test_queries:
        print(f"\nQuery: {query!r}")
        chunks = retrieve(query, k=5, threshold=0.6)
        if not chunks:
            print("  (no chunks passed the threshold)")
        for c in chunks:
            print(f"  [{c.distance:.3f}] {c.doc_id}#{c.position}: {c.text[:80]!r}")


if __name__ == "__main__":
    main()