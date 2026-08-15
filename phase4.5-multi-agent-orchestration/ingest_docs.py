"""
Ingest pipeline for the docs sub-agent's corpus: pydantic's docs/ tree ->
chunk -> embed -> store in ChromaDB.
"""
from __future__ import annotations

import argparse
import re
import statistics
import time
from pathlib import Path

import chromadb
import voyageai
import voyageai.error
from dotenv import load_dotenv

load_dotenv()

CORPUS_DIR = Path(__file__).parent / "corpus" / "pydantic-docs"
CHROMA_PATH = Path(__file__).parent / "chroma_store"

COLLECTIONS = {
    "fixed": "pydantic_docs",
    "structured": "pydantic_docs_structured",
}

vo = voyageai.Client()
chroma_client = chromadb.PersistentClient(path=str(CHROMA_PATH))


def strip_directives(text: str) -> str:
    """Text with mkdocs autodoc directive lines removed. Empty => nothing to embed."""
    return re.sub(r"^:::.*$", "", text, flags=re.MULTILINE).strip()


def load_corpus(corpus_dir: Path, skip_stubs: bool = False) -> list[dict]:
    """Read every .md file under corpus_dir (recursive) into {doc_id, text} dicts."""
    documents = []
    for path in sorted(corpus_dir.rglob("*.md")):
        doc_id = path.relative_to(corpus_dir).with_suffix("").as_posix()
        text = path.read_text(encoding="utf-8")

        if skip_stubs and not strip_directives(text):
            print(f"  skipping stub {doc_id}")
            continue

        documents.append({"doc_id": doc_id, "text": text})
    return documents


def chunk_document(doc_id: str, text: str, max_chars: int = 1000, overlap: int = 150) -> list[dict]:
    """Baseline: blind fixed-size windows. Produced the pydantic_docs collection."""
    chunks = []
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


def split_sections(text: str) -> list[tuple[str, str]]:
    """Split markdown into (heading_path, body) pairs."""

    parts = re.split(r"^(#{2,6})\s+(.+?)\s*$", text, flags=re.MULTILINE)
    heading_path = []
    sections = []

    if parts[0].strip():
        sections.append(("", parts[0]))

    for i in range(1, len(parts), 3):
        hashes, heading, body = parts[i:i + 3]
        level = len(hashes)
        heading_path = heading_path[:level - 2] + [heading.strip()]
        sections.append(("/".join(heading_path), body))

    return sections


def chunk_document_structured(doc_id: str, text: str, max_chars: int = 1000) -> list[dict]:
    """Heading-aware: sections first, then handle the ragged ones."""
    chunks = []
    position = 0
    for heading_path, body in split_sections(text):
        if not body.strip():
            continue
        if len(body) <= 100:
            print(f"  skipping tiny section {doc_id} {heading_path}")
            continue
        if len(body) > 100 and len(body) <= max_chars:
            pieces = [body]
        else:
            pieces = [c["text"] for c in chunk_document(doc_id, body, max_chars=max_chars)]

        for piece in pieces:
            piece = piece.strip()
            if not piece:
                continue
            chunks.append({
                "id": f"{doc_id}_{position}",
                "doc_id": doc_id,
                "position": position,
                "text": f"{heading_path}\n\n{piece}" if heading_path else piece,
            })
            position += 1
    return chunks


def embed_with_retry(texts: list[str], max_retries: int = 5) -> list[list[float]]:
    for attempt in range(max_retries):
        try:
            return vo.embed(texts, model="voyage-3.5", input_type="document").embeddings
        except voyageai.error.RateLimitError:
            wait = 20 * (attempt + 1)
            print(f"  rate limited, waiting {wait}s (attempt {attempt + 1}/{max_retries})")
            time.sleep(wait)
    raise RuntimeError("Exceeded max retries on Voyage rate limit")


def embed_and_store(chunks: list[dict], collection_name: str,
                    batch_size: int = 10, seconds_between_batches: int = 20) -> None:
    collection = chroma_client.get_or_create_collection(
        name=collection_name, metadata={"hnsw:space": "cosine"}
    )

    for i in range(0, len(chunks), batch_size):
        batch = chunks[i : i + batch_size]
        texts = [c["text"] for c in batch]
        embeddings = embed_with_retry(texts)

        collection.upsert(
            ids=[c["id"] for c in batch],
            embeddings=embeddings,
            documents=texts,
            metadatas=[{"doc_id": c["doc_id"], "position": c["position"]} for c in batch],
        )
        print(f"  embedded + stored chunks {i}-{i + len(batch)}")

        if i + batch_size < len(chunks):
            time.sleep(seconds_between_batches)


def describe(chunks: list[dict]) -> None:
    """Chunk stats without spending embed budget. Run this before every ingest."""
    lens = sorted(len(c["text"]) for c in chunks)
    if not lens:
        print("  no chunks!")
        return
    print(f"  chunks : {len(lens)}")
    print(f"  median : {statistics.median(lens):.0f}")
    print(f"  mean   : {statistics.mean(lens):.0f}")
    print(f"  p10/p90: {lens[len(lens) // 10]} / {lens[9 * len(lens) // 10]}")
    print(f"  min/max: {lens[0]} / {lens[-1]}")
    print(f"  under 100 chars: {sum(1 for n in lens if n < 100)}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--strategy", choices=COLLECTIONS, default="structured")
    parser.add_argument("--dry-run", action="store_true", help="chunk + print stats, no embedding")
    args = parser.parse_args()

    collection_name = COLLECTIONS[args.strategy]
    structured = args.strategy == "structured"

    print(f"Loading corpus from {CORPUS_DIR} ...")
    documents = load_corpus(CORPUS_DIR, skip_stubs=structured)
    print(f"found {len(documents)} documents")

    chunker = chunk_document_structured if structured else chunk_document
    all_chunks = []
    for doc in documents:
        all_chunks.extend(chunker(doc["doc_id"], doc["text"]))

    print(f"\n{args.strategy} chunking:")
    describe(all_chunks)

    if args.dry_run:
        print("\ndry run — nothing embedded.")
        return

    print(f"\nEmbedding + storing in ChromaDB collection '{collection_name}' ...")
    embed_and_store(all_chunks, collection_name)
    print("Done.")


if __name__ == "__main__":
    main()
