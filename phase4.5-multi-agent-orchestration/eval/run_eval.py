"""
Retrieval eval for the docs sub-agent.

Three metrics, reported separately and never blended (same rule as Phase 3):

  doc recall@k    did the right *document* come back? Uses relevant_doc_ids,
                  which are collection-independent — this is the only metric
                  that can compare fixed vs structured chunking, because chunk
                  ids number differently in the two collections.

  chunk precision@k  of what came back, how much was actually relevant? Needs
                  relevant_chunk_ids_structured, so it is structured-only.

  margin          best relevant similarity minus best irrelevant similarity,
                  per question. Needs no chunk annotation, and it is the direct
                  test of the dilution diagnosis: a threshold has to fit inside
                  this gap. Baseline on pydantic_docs was 0.476 - 0.413 = 0.063.

  python eval/run_eval.py --collection pydantic_docs_structured --k 8 --threshold 0.5
  python eval/run_eval.py --sweep
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from retriever import retrieve  # noqa: E402

DATASET_PATH = Path(__file__).parent / "dataset.json"
RESULTS_DIR = Path(__file__).parent / "results"


def precision_at_k(retrieved_ids: list[str], relevant_ids: list[str]) -> float:
    if not retrieved_ids:
        return 0.0
    return sum(1 for i in retrieved_ids if i in relevant_ids) / len(retrieved_ids)


def recall_at_k(retrieved: list[str], relevant: list[str]) -> float:
    if not relevant:
        return 0.0
    return sum(1 for i in relevant if i in retrieved) / len(relevant)


def evaluate(collection: str, k: int, threshold: float) -> dict:
    data = json.loads(DATASET_PATH.read_text())
    answerable, refusals, results = [], [], []

    for q in data["questions"]:
        if q["category"] == "malformed":
            continue

        # threshold=0.0 so every candidate is visible; the threshold is applied
        # below, otherwise a question that returns nothing has no margin to
        # measure and the metric silently disappears.
        chunks = retrieve(q["question"], k=k, threshold=0.0, collection_name=collection)
        passing = [c for c in chunks if (1 - c.distance) >= threshold]

        relevant_docs = q["relevant_doc_ids"]
        best_rel = max((1 - c.distance for c in chunks if c.doc_id in relevant_docs), default=None)
        best_irr = max((1 - c.distance for c in chunks if c.doc_id not in relevant_docs), default=None)

        row = {
            "id": q["id"],
            "category": q["category"],
            "returned": len(passing),
            "best_relevant": round(best_rel, 3) if best_rel is not None else None,
            "best_irrelevant": round(best_irr, 3) if best_irr is not None else None,
            "margin": round(best_rel - best_irr, 3) if None not in (best_rel, best_irr) else None,
        }

        if q["category"] == "out-of-scope":
            # Correct behaviour is returning nothing above the threshold.
            row["refused_correctly"] = len(passing) == 0
            refusals.append(row)
        else:
            retrieved_docs = {c.doc_id for c in passing}
            row["doc_recall"] = round(recall_at_k(retrieved_docs, relevant_docs), 3)
            gold_chunks = q.get("relevant_chunk_ids_structured") or []
            row["chunk_precision"] = (
                round(precision_at_k([c.id for c in passing], gold_chunks), 3) if gold_chunks else None
            )
            answerable.append(row)

        results.append(row)

    def mean(rows, key):
        vals = [r[key] for r in rows if r.get(key) is not None]
        return round(statistics.mean(vals), 3) if vals else None

    return {
        "collection": collection,
        "k": k,
        "threshold": threshold,
        "summary": {
            "doc_recall": mean(answerable, "doc_recall"),
            "chunk_precision": mean(answerable, "chunk_precision"),
            "mean_margin": mean(answerable, "margin"),
            "refusal_correctness": (
                round(sum(1 for r in refusals if r["refused_correctly"]) / len(refusals), 3)
                if refusals else None
            ),
        },
        "results": results,
    }


def print_report(out: dict) -> None:
    s = out["summary"]
    print(f"\ncollection={out['collection']}  k={out['k']}  threshold={out['threshold']}")
    print(f"{'id':<6} {'cat':<13} {'ret':>4} {'rel':>6} {'irr':>6} {'margin':>7} {'docR':>6} {'chunkP':>7}")
    print("-" * 68)
    for r in out["results"]:
        fmt = lambda v: f"{v:>6.3f}" if isinstance(v, float) else f"{'-':>6}"
        dr = f"{r['doc_recall']:>6.3f}" if r.get("doc_recall") is not None else f"{'-':>6}"
        cp = f"{r['chunk_precision']:>7.3f}" if r.get("chunk_precision") is not None else f"{'-':>7}"
        print(f"{r['id']:<6} {r['category']:<13} {r['returned']:>4} {fmt(r['best_relevant'])} "
              f"{fmt(r['best_irrelevant'])} {fmt(r['margin']):>7} {dr} {cp}")
    print("-" * 68)
    print(f"  doc recall@k        : {s['doc_recall']}")
    print(f"  chunk precision@k   : {s['chunk_precision']}")
    print(f"  mean margin         : {s['mean_margin']}")
    print(f"  refusal correctness : {s['refusal_correctness']}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--collection", default="pydantic_docs_structured")
    parser.add_argument("--k", type=int, default=8)
    parser.add_argument("--threshold", type=float, default=0.5)
    parser.add_argument("--sweep", action="store_true", help="both collections, a grid of k/threshold")
    parser.add_argument("--save", help="write JSON to results/<name>.json")
    args = parser.parse_args()

    RESULTS_DIR.mkdir(exist_ok=True)

    if args.sweep:
        rows = []
        for collection in ("pydantic_docs", "pydantic_docs_structured"):
            for k in (5, 8, 10):
                for threshold in (0.35, 0.40, 0.45, 0.50):
                    out = evaluate(collection, k, threshold)
                    rows.append(out)
                    s = out["summary"]
                    print(f"{collection:<26} k={k:<3} t={threshold:<5} "
                          f"docR={s['doc_recall']}  margin={s['mean_margin']}  "
                          f"refusal={s['refusal_correctness']}")
        (RESULTS_DIR / "sweep.json").write_text(json.dumps(rows, indent=2))
        print(f"\nSaved → {RESULTS_DIR / 'sweep.json'}")
        return

    out = evaluate(args.collection, args.k, args.threshold)
    print_report(out)
    if args.save:
        path = RESULTS_DIR / f"{args.save}.json"
        path.write_text(json.dumps(out, indent=2))
        print(f"\nSaved → {path}")


if __name__ == "__main__":
    main()
