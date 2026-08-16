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

Recall@k answers "is the original in the list". It does not answer "should the
agent believe its top candidate", which is what the triage prompt needs. So the
similarity *scores* are kept too, and reported as two distributions — what a
true duplicate scores vs what the best wrong candidate scores — plus a floor
sweep trading coverage against precision. If those distributions overlap, no
similarity floor works and the agent should report top-n with scores instead.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

import chromadb

sys.path.insert(0, str(Path(__file__).parent.parent))
from ingest_issues import issue_to_document, load_issues, vo, VARIANTS  # noqa: E402

PAIRS_PATH = Path(__file__).parent / "duplicate_pairs.json"
CHROMA_PATH = Path(__file__).parent.parent / "chroma_store"
RESULTS_DIR = Path(__file__).parent / "results"
KS = (1, 3, 5, 10)

# Candidate similarity floors for the triage agent's "confident match" rule.
FLOORS = (0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80)

# The variant actually wired into subagents.py.
PRODUCTION_VARIANT = "title_desc_code"

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
            include=["distances"],
        )
        distances = (res["distances"] or [[]])[0]
        ranked = [(i, 1 - d) for i, d in zip(res["ids"][0], distances)
                  if i != dup][:max_k]
        ranked_ids = [i for i, _ in ranked]
        evaluated += 1

        rank = ranked_ids.index(orig) + 1 if orig in ranked_ids else None
        if rank:
            ranks.append(rank)
        for k in KS:
            if rank and rank <= k:
                hits[k] += 1

        # The two distributions a floor has to separate:
        #   sim_original       what a TRUE duplicate scores
        #   sim_best_impostor  what the best WRONG candidate scores
        sim_original = next((s for i, s in ranked if i == orig), None)
        sim_best_impostor = next((s for i, s in ranked if i != orig), None)
        top1_id, top1_sim = ranked[0] if ranked else (None, None)

        rows.append({
            "duplicate": dup,
            "original": orig,
            "rank": rank,
            "confidence": pair.get("confidence"),
            "sim_original": round(sim_original, 4) if sim_original is not None else None,
            "sim_best_impostor": round(sim_best_impostor, 4) if sim_best_impostor is not None else None,
            "margin": (round(sim_original - sim_best_impostor, 4)
                       if sim_original is not None and sim_best_impostor is not None
                       else None),
            # What the agent would actually act on: its single best candidate.
            "top1_id": top1_id,
            "top1_sim": round(top1_sim, 4) if top1_sim is not None else None,
            "top1_correct": top1_id == orig,
        })

    return {
        "variant": variant,
        "collection": f"issues_{variant}",
        "pairs_evaluated": evaluated,
        "recall_at_k": {f"recall@{k}": round(hits[k] / evaluated, 3) for k in KS},
        "mean_rank_when_found": round(sum(ranks) / len(ranks), 2) if ranks else None,
        "found_anywhere_in_top_10": len(ranks),
        "similarity": {
            "true_duplicates": describe([r["sim_original"] for r in rows]),
            "best_impostors": describe([r["sim_best_impostor"] for r in rows]),
            "margin_when_found": describe([r["margin"] for r in rows]),
        },
        "floor_sweep": floor_sweep(rows),
        "results": rows,
    }


def describe(vals: list) -> dict | None:
    """Distribution of a similarity column, ignoring misses."""
    vals = sorted(v for v in vals if v is not None)
    if not vals:
        return None
    return {
        "n": len(vals),
        "min": round(vals[0], 3),
        "p25": round(vals[len(vals) // 4], 3),
        "median": round(statistics.median(vals), 3),
        "mean": round(statistics.mean(vals), 3),
        "max": round(vals[-1], 3),
    }


def floor_sweep(rows: list[dict]) -> list[dict]:
    """
    For each candidate floor: if the agent only claims a duplicate when its top
    candidate clears the floor, how often does it speak, and how often is it right?

      coverage   fraction of pairs where the top candidate clears the floor
      precision  of those, the fraction where the top candidate IS the original

    A floor is only worth having if precision climbs meaningfully faster than
    coverage falls. If it doesn't, drop the floor and always report top-n with
    scores.
    """
    out = []
    for floor in FLOORS:
        clearing = [r for r in rows if r["top1_sim"] is not None and r["top1_sim"] >= floor]
        correct = [r for r in clearing if r["top1_correct"]]
        out.append({
            "floor": floor,
            "pairs_clearing": len(clearing),
            "coverage": round(len(clearing) / len(rows), 3) if rows else None,
            "precision": round(len(correct) / len(clearing), 3) if clearing else None,
        })
    return out


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

    prod = next(o for o in outputs if o["variant"] == PRODUCTION_VARIANT)
    print(f"\n--- similarity distributions ({PRODUCTION_VARIANT}) ---")
    print(f"{'':<20} {'n':>4} {'min':>7} {'p25':>7} {'median':>7} {'mean':>7} {'max':>7}")
    for label, d in prod["similarity"].items():
        if d is None:
            continue
        print(f"{label:<20} {d['n']:>4} {d['min']:>7.3f} {d['p25']:>7.3f} "
              f"{d['median']:>7.3f} {d['mean']:>7.3f} {d['max']:>7.3f}")

    print("\n--- floor sweep: agent claims a duplicate only if top candidate >= floor ---")
    print(f"{'floor':>6} {'clears':>7} {'coverage':>9} {'precision':>10}")
    for row in prod["floor_sweep"]:
        prec = f"{row['precision']:>10.3f}" if row["precision"] is not None else f"{'-':>10}"
        print(f"{row['floor']:>6.2f} {row['pairs_clearing']:>7} {row['coverage']:>9.3f}{prec}")

    (RESULTS_DIR / "duplicate_recall.json").write_text(json.dumps(outputs, indent=2))
    print(f"\nSaved → {RESULTS_DIR / 'duplicate_recall.json'}")


if __name__ == "__main__":
    main()
