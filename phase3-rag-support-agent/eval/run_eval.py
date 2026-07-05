
import json, sys, argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from RAG.retriever import retrieve

DATASET_PATH = Path(__file__).parent / "dataset.json"
RESULTS_DIR  = Path(__file__).parent / "results"


def precision_at_k(retrieved_ids: list[str], relevant_ids: list[str]) -> float:
    # Of the chunks we retrieved, what fraction are actually relevant?
    # Hint: set intersection, divided by len(retrieved_ids)
    # Edge case: what if retrieved_ids is empty?
    total = len(retrieved_ids)
    relevant = 0
    for id in retrieved_ids:
        if id in relevant_ids:
            relevant += 1
    precision = relevant / total if total > 0 else 0.0
    return precision


def recall_at_k(retrieved_ids: list[str], relevant_ids: list[str]) -> float:
    # Of the chunks that ARE relevant, what fraction did we retrieve?
    # Hint: set intersection, divided by len(relevant_ids)
    # Edge case: what if relevant_ids is empty? (shouldn't happen for in-scope Qs, but guard it)
    total = len(relevant_ids)
    retrieved_relevant = 0
    for id in relevant_ids:
        if id in retrieved_ids:
            retrieved_relevant += 1
    recall = retrieved_relevant / total if total > 0 else 0.0
    return recall


def run_eval(k: int = 5, threshold: float = 0.5) -> dict:
    data = json.loads(DATASET_PATH.read_text())
    results = []

    for q in data["questions"]:
        if q["category"] == "out-of-scope" or q["category"] == "malformed":
            continue  # skip out-of-scope questions

        chunks = retrieve(q["question"], k=k, threshold=threshold)
        retrieved_ids = [c.id for c in chunks]

        p = precision_at_k(retrieved_ids, q["relevant_chunk_ids"])
        r = recall_at_k(retrieved_ids, q["relevant_chunk_ids"])

        results.append({
            "id": q["id"],
            "category": q["category"],
            "question": q["question"],
            "retrieved_ids": retrieved_ids,
            "relevant_ids": q["relevant_chunk_ids"],
            "precision": round(p, 3),
            "recall": round(r, 3),
        })

    mean_p = sum(r["precision"] for r in results) / len(results)  
    mean_r = sum(r["recall"] for r in results) / len(results)  

    return {
        "k": k,
        "threshold": threshold,
        "summary": {"mean_precision": round(mean_p, 3), "mean_recall": round(mean_r, 3)},
        "results": results,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--threshold", type=float, default=0.5)
    args = parser.parse_args()

    RESULTS_DIR.mkdir(exist_ok=True)
    output = run_eval(k=args.k, threshold=args.threshold)

    print(f"\nk={output['k']}  threshold={output['threshold']}")
    print(f"{'id':<6} {'cat':<12} {'prec':>6} {'recall':>7}  retrieved")
    print("-" * 70)
    for r in output["results"]:
        print(f"{r['id']:<6} {r['category']:<12} {r['precision']:>6.3f} {r['recall']:>7.3f}  {r['retrieved_ids']}")

    s = output["summary"]
    print("-" * 70)
    print(f"{'MEAN':<19} {s['mean_precision']:>6.3f} {s['mean_recall']:>7.3f}")

    out_path = RESULTS_DIR / f"eval_k{args.k}_t{int(args.threshold*100)}.json"

    out_path.write_text(json.dumps(output, indent=2))
    print(f"\nSaved → {out_path}")


if __name__ == "__main__":
    main()
