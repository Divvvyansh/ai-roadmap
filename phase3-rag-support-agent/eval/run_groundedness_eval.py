
import json, sys, argparse
import anthropic
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from RAG.retriever import retrieve, Chunk

DATASET_PATH = Path(__file__).parent / "dataset.json"
RESULTS_DIR  = Path(__file__).parent / "results"

client = anthropic.Anthropic()


def precision_at_k(retrieved_ids: list[str], relevant_ids: list[str]) -> float:
    total = len(retrieved_ids)
    relevant = 0
    for id in retrieved_ids:
        if id in relevant_ids:
            relevant += 1
    return relevant / total if total > 0 else 0.0


def recall_at_k(retrieved_ids: list[str], relevant_ids: list[str]) -> float:
    total = len(relevant_ids)
    retrieved_relevant = 0
    for id in relevant_ids:
        if id in retrieved_ids:
            retrieved_relevant += 1
    return retrieved_relevant / total if total > 0 else 0.0


def generate_answer(question: str, chunks: list[Chunk]) -> str:
    SYSTEM_PROMPT = "You are a helpful assistant that answers user's queries about fastapi and how to use it. " \
    "Always answer the user's question using ONLY the provided chunks of text. " \
    "If the answer is not contained in the chunks, reply with 'I don't know.'"
    user_message = "Here are the chunks of text:\n"
    for i, chunk in enumerate(chunks):
        user_message += f"Chunk {i+1}:\n{chunk.text}\n\n"
    user_message += f"Question: {question}\nPlease answer the question using ONLY the provided chunks."   
    message = [{"role": "user", "content": user_message}]      

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",  
        system=SYSTEM_PROMPT,
        messages=message,
        max_tokens=512
    )
    return response.content[0].text.strip()


def judge_groundedness(question: str, chunks: list[Chunk], answer: str) -> dict:
    SYSTEM_PROMPT = "You are a helpful assistant that judges whether an answer is grounded in the provided chunks of text. " \
    "You will be given a question, an answer, and a set of chunks. "\
    "Your task is to determine whether every claim in the answer can be traced back to the provided chunks. " \
    "If the answer is fully supported by the chunks, return 'grounded: true'. If any part of the answer is not supported by the chunks, return 'grounded: false'. " \
    "Additionally, provide a brief reasoning for your judgment in the format 'reasoning: <your reasoning here>'. " \
    "Your response should be in the following JSON format:\n" \
    "{\n" \
    "  \"grounded\": true/false,\n" \
    "  \"reasoning\": \"<your reasoning here>\"\n" \
    "}\n" \
    "Ensure that the JSON is valid and parsable." \
    "Return ONLY the raw JSON object. No markdown, no code blocks, no text outside the JSON."  
    user_message = "Question: {}\nAnswer: {}\nChunks:\n".format(question, answer)
    for i, chunk in enumerate(chunks):
        user_message += f"Chunk {i+1}:\n{chunk.text}\n\n"
    user_message += "Please provide your judgment in the specified JSON format."    
    message = [{"role": "user", "content": user_message}]  

    response = client.messages.create(
        model="claude-sonnet-4-6",   
        system= SYSTEM_PROMPT,
        messages=message,
        max_tokens=1000,
    )

    text = response.content[0].text.strip()
    if text.startswith("```"):
        text = "\n".join(text.split("\n")[1:-1]).strip()
    try:
        judgment = json.loads(text)
    except json.JSONDecodeError:
        judgment = {"grounded": False, "reasoning": "Failed to parse judgment JSON."}

    grounded = judgment.get("grounded", False)
    reasoning = judgment.get("reasoning", "")
    return {"grounded": grounded, "reasoning": reasoning}
    


def run_eval(k: int = 5, threshold: float = 0.5) -> dict:
    data = json.loads(DATASET_PATH.read_text())
    results = []

    for q in data["questions"]:
        if q["category"] == "out-of-scope" or q["category"] == "malformed":
            continue

        chunks = retrieve(q["question"], k=k, threshold=threshold)
        retrieved_ids = [c.id for c in chunks]

        p = precision_at_k(retrieved_ids, q["relevant_chunk_ids"])
        r = recall_at_k(retrieved_ids, q["relevant_chunk_ids"])

        answer = generate_answer(q["question"], chunks)
        judgment = judge_groundedness(q["question"], chunks, answer)

        results.append({
            "id": q["id"],
            "category": q["category"],
            "question": q["question"],
            "retrieved_ids": retrieved_ids,
            "relevant_ids": q["relevant_chunk_ids"],
            "precision": round(p, 3),
            "recall": round(r, 3),
            "answer": answer,
            "grounded": judgment["grounded"],
            "reasoning": judgment["reasoning"],
        })

    mean_p = sum(r["precision"] for r in results) / len(results)
    mean_r = sum(r["recall"] for r in results) / len(results)
    groundedness_rate = sum(1 for r in results if r["grounded"]) / len(results)

    return {
        "k": k,
        "threshold": threshold,
        "summary": {
            "mean_precision": round(mean_p, 3),
            "mean_recall": round(mean_r, 3),
            "groundedness": round(groundedness_rate, 3),
        },
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
    print(f"{'id':<6} {'cat':<12} {'prec':>6} {'recall':>7} {'grounded':>9}  answer[:60]")
    print("-" * 90)
    for r in output["results"]:
        grounded_str = "YES" if r["grounded"] else "NO"
        print(
            f"{r['id']:<6} {r['category']:<12} {r['precision']:>6.3f} {r['recall']:>7.3f}"
            f" {grounded_str:>9}  {r['answer'][:60]!r}"
        )

    s = output["summary"]
    print("-" * 90)
    print(f"{'MEAN':<19} {s['mean_precision']:>6.3f} {s['mean_recall']:>7.3f} {s['groundedness']:>9.3f}")

    out_path = RESULTS_DIR / f"groundedness_k{args.k}_t{int(args.threshold * 100)}.json"
    out_path.write_text(json.dumps(output, indent=2))
    print(f"\nSaved → {out_path}")


if __name__ == "__main__":
    main()
