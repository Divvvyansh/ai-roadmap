"""
Step 4 — duplicate-detection retrieval quality.

For each (duplicate, original) pair: query the issue collection with the
duplicate's vector and check whether the original lands in the top k.

Two things this file is careful about, both of which silently corrupt the
number rather than raising:

  input_type   ingest_issues.py embedded with input_type=None, because
               duplicate detection is symmetric — both sides are issues. The
               docs retriever uses input_type="query" for an asymmetric
               question-against-passage search. Reusing that here would put
               the two halves of a same-kind comparison in different spaces,
               so this module does its own embedding and never imports
               retriever.embed_query.

  self-hit     the duplicate is itself in the index, so querying with its own
               vector returns itself at rank 1. It is dropped before ranking;
               otherwise recall@5 is really recall@4.

The bulk measurement queries with each issue's *stored* vector, which costs no
API calls. check_sanity() separately re-embeds a few issues from scratch to
confirm the stored vectors match what the live path would produce.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import chromadb

sys.path.insert(0, str(Path(__file__).parent.parent))
from ingest_issues import issue_to_document, load_issues, vo, VARIANTS  # noqa: E402

PAIRS_PATH = Path(__file__).parent / "duplicate_pairs.json"
CHROMA_PATH = Path(__file__).parent.parent / "chroma_store"
RESULTS_DIR = Path(__file__).parent / "results"
KS = (1, 3, 5, 10)

chroma_client = chromadb.PersistentClient(path=str(CHROMA_PATH))


def embed_symmetric(texts: list[str]) -> list[list[float]]:
    """Same input_type the issues were ingested with. Do not 'fix' this to 'query'."""
    return vo.embed(texts, model="voyage-3.5", input_type=None).embeddings


def cosine_distance(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return 1 - dot / (na * nb)


def check_sanity(variant: str, sample: int = 3) -> bool:
    """
    Before trusting any recall number: a record must be closest to itself.

    Re-derives the document text for a few issues, embeds it fresh, and compares
    against the stored vector. A non-zero distance means either Voyage is not
    deterministic call-to-call (small, mostly harmless) or issue_to_document is
    producing different text now than it did at ingest time (a real bug that
    makes recall@k measure a mismatch rather than retrieval quality).
    """
    collection = chroma_client.get_collection(f"issues_{variant}")
    issues = {str(i["number"]): i for i in load_issues()}
    pairs = json.loads(PAIRS_PATH.read_text())

    ids = [str(p["duplicate"]) for p in pairs[:sample]]
    stored = collection.get(ids=ids, include=["embeddings"])
    fresh = embed_symmetric([issue_to_document(issues[i], variant) for i in stored["ids"]])

    ok = True
    print(f"  sanity check on {len(ids)} issues (variant={variant}):")
    for issue_id, stored_vec, fresh_vec in zip(stored["ids"], stored["embeddings"], fresh):
        drift = cosine_distance(list(stored_vec), fresh_vec)
        hit = collection.query(query_embeddings=[fresh_vec], n_results=1, include=[])["ids"][0][0]
        self_first = hit == issue_id
        ok &= drift < 1e-4 and self_first
        print(f"    #{issue_id}: drift={drift:.2e}  self ranks first={self_first}")
    return ok


def evaluate(variant: str) -> dict:
    collection = chroma_client.get_collection(f"issues_{variant}")
    pairs = json.loads(PAIRS_PATH.read_text())
    max_k = max(KS)

    hits = {k: 0 for k in KS}
    ranks, evaluated, rows = [], 0, []

    for pair in pairs:
        dup, orig = str(pair["duplicate"]), str(pair["original"])
        got = collection.get(ids=[dup], include=["embeddings"])
        if not got["ids"]:
            continue

        # max_k + 1 because the query issue itself occupies one slot.
        res = collection.query(
            query_embeddings=[list(got["embeddings"][0])],
            n_results=max_k + 1,
            include=[],
        )
        ranked = [i for i in res["ids"][0] if i != dup][:max_k]
        evaluated += 1

        rank = ranked.index(orig) + 1 if orig in ranked else None
        if rank:
            ranks.append(rank)
        for k in KS:
            if rank and rank <= k:
                hits[k] += 1
        rows.append({"duplicate": dup, "original": orig, "rank": rank,
                     "confidence": pair.get("confidence")})

    return {
        "variant": variant,
        "collection": f"issues_{variant}",
        "pairs_evaluated": evaluated,
        "recall_at_k": {f"recall@{k}": round(hits[k] / evaluated, 3) for k in KS},
        "mean_rank_when_found": round(sum(ranks) / len(ranks), 2) if ranks else None,
        "found_anywhere_in_top_10": len(ranks),
        "results": rows,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-sanity", action="store_true")
    args = parser.parse_args()
    RESULTS_DIR.mkdir(exist_ok=True)

    if not args.skip_sanity:
        print("Sanity check (costs a few API calls) ...")
        if not check_sanity("title_desc"):
            print("\n  FAILED — a record is not closest to itself. Recall numbers below "
                  "would measure a text mismatch, not retrieval. Stopping.")
            sys.exit(1)
        print("  passed.\n")

    outputs = []
    for variant in VARIANTS:
        out = evaluate(variant)
        outputs.append(out)
        r = out["recall_at_k"]
        print(f"{variant:<22} n={out['pairs_evaluated']:<4} "
              + "  ".join(f"{k}={v:.3f}" for k, v in r.items())
              + f"   mean_rank={out['mean_rank_when_found']}")

    (RESULTS_DIR / "duplicate_recall.json").write_text(json.dumps(outputs, indent=2))
    print(f"\nSaved → {RESULTS_DIR / 'duplicate_recall.json'}")


if __name__ == "__main__":
    main()
