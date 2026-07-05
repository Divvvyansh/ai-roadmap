
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from RAG.retriever import retrieve

DATASET_PATH = Path(__file__).parent / "dataset.json"
K = 20
THRESHOLD = 0.3


def print_divider(char="─", width=80):
    print(char * width)


def run():
    data = json.loads(DATASET_PATH.read_text())
    questions = data["questions"]

    print(f"\nAnnotation tool — {len(questions)} questions")
    print("Press Enter to go to next question. Ctrl-C to quit.\n")

    for i, q in enumerate(questions, 1):
        already_done = bool(q.get("relevant_chunk_ids"))

        print_divider("═")
        print(f"[{i}/{len(questions)}]  {q['id']}  |  {q['category'].upper()}  |  should_decline={q['should_decline']}")
        if already_done:
            print(f"  already annotated: {q['relevant_chunk_ids']}")
        print(f"\n  Q: {q['question']}\n")

        if already_done:
            inp = input("  Already annotated — press Enter to show chunks anyway, or 's' to skip: ").strip().lower()
            if inp == "s":
                print()
                continue

        chunks = retrieve(q["question"], k=K, threshold=THRESHOLD)

        if not chunks:
            print("  (no chunks returned above threshold)\n")
        else:
            print(f"  {len(chunks)} chunk(s) returned:\n")
            for c in chunks:
                similarity = 1 - c.distance
                print_divider("·")
                print(f"  ID       : {c.id}")
                print(f"  doc_id   : {c.doc_id}  |  position: {c.position}  |  similarity: {similarity:.3f}")
                print(f"  Text     :\n")
                for line in c.text.splitlines():
                    print(f"    {line}")
                print()

        input("  Press Enter for next question...")
        print()

    print_divider("═")
    print("Done. Update relevant_chunk_ids in eval/dataset.json based on your notes.")


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        print("\n\nStopped.")
        sys.exit(0)
