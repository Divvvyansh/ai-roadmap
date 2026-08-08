
import json, argparse
from pathlib import Path
from datetime import datetime, timezone

from deployed_client import call_ask_endpoint

DATASET_PATH = Path(__file__).parent / "dataset.json"
RESULTS_DIR  = Path(__file__).parent / "results"


def precision_at_k(retrieved_ids: list[str], relevant_ids: list[str]) -> float:
    total = len(retrieved_ids)
    relevant = 0
    for id in retrieved_ids:
        if id in relevant_ids:
            relevant += 1
    precision = relevant / total if total > 0 else 0.0
    return precision


def recall_at_k(retrieved_ids: list[str], relevant_ids: list[str]) -> float:
    total = len(relevant_ids)
    retrieved_relevant = 0
    for id in relevant_ids:
        if id in retrieved_ids:
            retrieved_relevant += 1
    recall = retrieved_relevant / total if total > 0 else 0.0
    return recall


def run_eval(base_url: str) -> dict:
    data = json.loads(DATASET_PATH.read_text())
    results = []

    for q in data["questions"]:
        if q["category"] == "out-of-scope" or q["category"] == "malformed":
            continue  
        
        response = call_ask_endpoint(q["question"], base_url)
        retrieved_ids = response.get("chunks_used", []) 

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
        "identifier": f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
        "base_url": base_url,
        "summary": {"mean_precision": round(mean_p, 3), "mean_recall": round(mean_r, 3)},
        "results": results,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    args = parser.parse_args()

    RESULTS_DIR.mkdir(exist_ok=True)
    output = run_eval(base_url=args.base_url)

    print(f"Evaluated {len(output['results'])} at ={output.get('identifier')}")
    print(f"Mean precision: {output['summary']['mean_precision']:.3f}, Mean recall: {output['summary']['mean_recall']:.3f}")
    print("-" * 70)
    for r in output["results"]:
        print(f"{r['id']:<6} {r['category']:<12} {r['precision']:>6.3f} {r['recall']:>7.3f}  {r['retrieved_ids']}")

    out_path = RESULTS_DIR / f"deployed_eval_{output['identifier']}.json"

    out_path.write_text(json.dumps(output, indent=2))
    print(f"\nSaved → {out_path}")


if __name__ == "__main__":
    main()
