
from __future__ import annotations

import json
import re
import time
from pathlib import Path

import chromadb
import voyageai
import voyageai.error
from dotenv import load_dotenv

load_dotenv()

CORPUS_PATH = Path(__file__).parent / "corpus" / "issues.jsonl"
CHROMA_PATH = Path(__file__).parent / "chroma_store"

MAX_DOC_CHARS = 4000

# variant name -> which sections join the title in the embedded text.
VARIANTS = {
    "title_only": [],
    "title_desc": ["description"],
    "title_desc_code": ["description", "example code"],
}

vo = voyageai.Client()
chroma_client = chromadb.PersistentClient(path=str(CHROMA_PATH))


def load_issues() -> list[dict]:
    return [json.loads(line) for line in CORPUS_PATH.read_text().splitlines()]


def split_sections(body: str | None) -> dict[str, str]:
    """Split a templated issue body into {lowercased header: section text}.
    """
    if not body:
        return {}
    parts = re.split(r"^#{2,3}\s*(.+?)\s*$", body, flags=re.MULTILINE)
    if len(parts) == 1: 
        return {"_body": body.strip()}
    sections = {}
    for header, text in zip(parts[1::2], parts[2::2]):
        sections[header.lower()] = text.strip()
    return sections


def issue_to_document(issue: dict, variant: str) -> str:
    """Build the text that gets embedded for one issue."""
    doc = issue["title"]
    body_initial = issue.get("body")
    sections = split_sections(body_initial)
    if variant == "title_only":
        pass
    else:
        if "_body" in sections:
            doc += "\n\n" + sections.get("_body", "")
        else:
            for section in VARIANTS[variant]:
                if section in sections:
                    doc += "\n\n" + sections[section]
    if len(doc) > MAX_DOC_CHARS:
        doc = doc[:MAX_DOC_CHARS]
    return doc 


def build_records(issues: list[dict], variant: str) -> list[dict]:
    records = []
    skipped = 0
    for issue in issues:
        doc_text = issue_to_document(issue, variant)
        if not doc_text.strip():
            skipped += 1
            continue
        record = {
            "id": str(issue["number"]),
            "text": doc_text,
            "metadata": {
                "number": issue["number"],
                "title": issue["title"],
                "html_url": issue["html_url"],
            },
        }
        records.append(record)
    if skipped:
        print(f"  skipped {skipped} empty/near-empty records")
    return records


def embed_with_retry(texts: list[str], max_retries: int = 5) -> list[list[float]]:
    for attempt in range(max_retries):
        try:
            return vo.embed(
                texts,
                model="voyage-3.5",
                input_type=None,  
            ).embeddings
        except voyageai.error.RateLimitError:
            wait = 20 * (attempt + 1)
            print(f"  rate limited, waiting {wait}s (attempt {attempt + 1}/{max_retries})")
            time.sleep(wait)
    raise RuntimeError("Exceeded max retries on Voyage rate limit")


def embed_and_store(records: list[dict], collection_name: str,
                    batch_size: int = 10, seconds_between_batches: int = 20) -> None:

    collection = chroma_client.get_or_create_collection( 
        name=collection_name,
        metadata={"hnsw:space": "cosine"},
    )
    for i in range(0, len(records), batch_size):
        batch = records[i : i + batch_size]
        texts = [r["text"] for r in batch]
        embeddings = embed_with_retry(texts)

        collection.upsert(
            ids=[r["id"] for r in batch],
            embeddings=embeddings,
            documents=texts,
            metadatas=[r["metadata"] for r in batch],
        )
        print(f"  embedded + stored records {i}-{i + len(batch)}")

        if i + batch_size < len(records):
            time.sleep(seconds_between_batches)


def main():
    issues = load_issues()
    print(f"{len(issues)} issues loaded")
    for variant in VARIANTS:
        records = build_records(issues, variant)
        print(f"\n{variant}: {len(records)} records -> collection issues_{variant}")
        embed_and_store(records, f"issues_{variant}")


if __name__ == "__main__":
    main()