"""
Orchestration eval.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import anthropic  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

import subagents  # noqa: E402
from orchestrator import _LEAK_MARKERS, orchestrate  # noqa: E402

load_dotenv()

DATASET_PATH = Path(__file__).parent / "orchestration_dataset.json"
RESULTS_DIR = Path(__file__).parent / "results"
ISSUES_PATH = Path(__file__).parent.parent / "corpus" / "issues.jsonl"

JUDGE_MODEL = "claude-opus-5"

ACTIONS = (
    "close_as_duplicate",
    "answer_as_support",
    "escalate_new_issue",
    "possible_duplicate_human_review",
    "regression",
)

judge_client = anthropic.Anthropic()


# ------------------------------------------------------------------ loading

def load_dataset() -> tuple[dict, list[dict]]:
    d = json.loads(DATASET_PATH.read_text())
    return d["_meta"], d["cases"]


def issue_report(number: int) -> str:
    """Title and body of one corpus issue, verbatim. Same text the dataset's
    _meta calls a ceiling: real reports are paraphrases, not the issue itself."""
    for line in open(ISSUES_PATH):
        issue = json.loads(line)
        if issue["number"] == number:
            return f"Title: {issue['title']}\n\n{(issue['body'] or '')[:3000]}"
    raise ValueError(f"#{number} not in corpus")


# ---------------------------------------------------------------- running

def run_case(case: dict) -> dict:
    """One orchestration, plus everything the scorers need, as plain JSON."""
    subagents.EXCLUDE_FROM_SEARCH.clear()
    subagents.EXCLUDE_FROM_SEARCH.update(case["exclude_from_search"])
    try:
        t = time.perf_counter()
        result = orchestrate(issue_report(case["issue_number"]))
        elapsed = time.perf_counter() - t
        row = result.as_dict()
        row["error"] = None
    except Exception as exc:                      
        elapsed = 0.0
        row = {"recommendation": "", "stop_reason": "exception",
               "orchestrator_turns": 0, "orchestrator_usage": {},
               "subagent_usage": {}, "agents_called": [], "delegations": [],
               "error": f"{type(exc).__name__}: {exc}"}
    finally:
        subagents.EXCLUDE_FROM_SEARCH.clear()

    row["case_id"] = case["id"]
    row["elapsed_s"] = round(elapsed, 1)
    return row


def cmd_run(args) -> None:
    meta, cases = load_dataset()
    if args.cases:
        wanted = set(args.cases.split(","))
        cases = [c for c in cases if c["id"] in wanted]
    if args.category:
        cases = [c for c in cases if c["category"] == args.category]
    if args.limit:
        cases = cases[: args.limit]

    RESULTS_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_path = RESULTS_DIR / f"orchestration_traces_{stamp}.json"

    print(f"{len(cases)} case(s) -> {out_path}")
    rows = []
    for i, case in enumerate(cases, 1):
        print(f"[{i}/{len(cases)}] {case['id']} ...", flush=True)
        row = run_case(case)
        rows.append(row)
        out_path.write_text(json.dumps(
            {"_meta": {"dataset": meta, "run_at": stamp}, "rows": rows}, indent=2))
        agents = ",".join(row["agents_called"]) or "-"
        print(f"      {row['elapsed_s']}s  agents={agents}  "
              f"stop={row['stop_reason']}"
              + (f"  ERROR {row['error']}" if row["error"] else ""))
    print(f"\nwrote {len(rows)} rows to {out_path}")
    print(f"score with: python eval/run_orchestration_eval.py score {out_path}")


# ---------------------------------------------------------------- scorers

CITE_RE = re.compile(r"#(\d{2,6})")


def cited_numbers(row: dict) -> tuple[list[int], str]:
    """Issue numbers the system committed to, in order of confidence.

    Only a number sent to the checker counts as a CITATION. A number in the
    recommendation prose does not. known-7353 named "#10590 -- UrlConstraints'
    host_required not applied (0.70)" in its list of REJECTED candidates, and a
    regex over the recommendation scored that as a correct citation, inflating
    the metric with an answer the system had explicitly declined to give. The
    orchestrator's prompt says to send the checker anything it is considering
    acting on, so "went to the checker" is the system's own definition of
    committed."""
    for d in row["delegations"]:
        if d["agent"] == "checker":
            m = re.search(r"duplicates issue #(\d+)", d["task"])
            if m:
                return [int(m.group(1))], "checker"
    return [int(n) for n in CITE_RE.findall(row["recommendation"])], "mentioned"


def score_citation(case: dict, row: dict) -> dict:
    """Cluster-scored, and a MISS is not proof of a wrong answer."""
    cluster = set(case["expected_duplicate_cluster"])
    cited, source = cited_numbers(row)
    committed = cited if source == "checker" else []
    if not cluster:
        return {"applicable": False, "cited": cited, "source": source,
                "committed": committed, "unlabelled_citation": bool(committed)}
    return {"applicable": True, "cited": cited, "source": source,
            "committed": committed,
            "hit": bool(cluster & set(committed)),
            "expected": sorted(cluster)}


def score_delegation(case: dict, row: dict) -> dict:
    called = set(row["agents_called"])
    required = set(case["expected_agents"])
    checker_ran = "checker" in called
    made_citation = any(
        d["agent"] == "checker" for d in row["delegations"])
    return {
        "required_present": required.issubset(called),
        "missing": sorted(required - called),
        "checker_ran": checker_ran,
        "expects_citation": case["expects_citation"],
        "checker_rule_ok": checker_ran == made_citation,
    }


def score_leak(row: dict) -> dict:
    """Mechanical, not judged. Scans only the text the orchestrator authored --
    everything after ORIGINAL REPORT: is the reporter's own prose, and reporters
    write "I believe" and "similar to" constantly."""
    out = []
    for d in row["delegations"]:
        if d["agent"] != "checker":
            continue
        authored = d["task"].split("ORIGINAL REPORT:", 1)[0].lower()
        hits = [m for m in _LEAK_MARKERS if m in authored]
        out.append({"hits": hits, "clean": not hits})
    return {"checked": len(out), "clean": sum(1 for o in out if o["clean"]),
            "detail": out}


def score_cost(row: dict) -> dict:
    o = row["orchestrator_usage"] or {}
    per_agent: dict[str, dict] = {}
    for d in row["delegations"]:
        u = d["usage"]
        a = per_agent.setdefault(d["agent"], {k: 0 for k in u})
        for k, v in u.items():
            a[k] += v
    return {"orchestrator": o, "per_agent": per_agent,
            "subagent_total": row["subagent_usage"] or {}}


# ---------------------------------------------------------------- judges

def _judge(system: str, user: str) -> str:
    r = judge_client.messages.create(
        model=JUDGE_MODEL, system=system, max_tokens=700,
        messages=[{"role": "user", "content": user}])
    return " ".join(b.text for b in r.content if b.type == "text")


ACTION_JUDGE_SYSTEM = (
    "You classify a maintainer-facing triage recommendation into exactly one "
    "action. You are not told which action is expected and must not guess at "
    "one — classify only what the text actually recommends.\n\n"
    "Begin your reply with a line reading exactly 'ACTION: X' where X is one of:\n"
    "close_as_duplicate — close this issue against a specific prior issue.\n"
    "answer_as_support — not a defect; answer the reporter from documentation.\n"
    "escalate_new_issue — a genuinely new problem; route it to a maintainer.\n"
    "possible_duplicate_human_review — a candidate prior issue exists but the "
    "recommendation stops short of closing and asks for a human look.\n"
    "regression — a previously fixed issue's behaviour has returned; reopen or "
    "link as a regression rather than closing.\n\n"
    "Then one sentence quoting the phrase that decided it. If the text is "
    "ambiguous between two, pick the one the FIRST stated action supports."
)


def judge_action(row: dict) -> dict:
    if not row["recommendation"]:
        return {"action": None, "raw": "", "note": "empty recommendation"}
    raw = _judge(ACTION_JUDGE_SYSTEM,
                 f"RECOMMENDATION:\n{row['recommendation'][:6000]}")
    m = re.search(r"ACTION:\s*([a-z_]+)", raw)
    action = m.group(1) if m and m.group(1) in ACTIONS else None
    return {"action": action, "raw": raw[:400]}


AGENT_TOOLS = {
    "triage": "search_issues (semantic search over closed issues) and get_issue "
              "(full text of any issue by number)",
    "docs": "search_docs (semantic search over the pydantic documentation)",
    "checker": "get_issue (full text of any issue by number) -- so a task naming "
               "an issue NUMBER is complete; the agent fetches that issue itself "
               "by design, and including someone else's summary of it would "
               "defeat the purpose",
}

TASK_JUDGE_SYSTEM = (
    "You judge whether a task string handed to a sub-agent is SELF-CONTAINED.\n\n"
    "The sub-agent starts from an empty message list. It cannot see the issue "
    "the caller is holding, the conversation, or any prior delegation.\n\n"
    "It CAN use its tools. Anything reachable through a tool is not missing from "
    "the task -- an identifier the agent can look up is sufficient, and demanding "
    "the looked-up content be pasted in is wrong. Judge only what the agent "
    "cannot obtain on its own.\n\n"
    "Begin your reply with a line reading exactly 'SELF_CONTAINED: YES' or "
    "'SELF_CONTAINED: NO'. Then one sentence.\n\n"
    "NO if the task refers to context it does not include ('the issue above', "
    "'this error', 'as described'), summarises away specifics the agent needs "
    "(exact config, exact error, the code that triggers it), or asks a question "
    "that cannot be answered from its own text. YES otherwise. Length is not the "
    "criterion — a short task that carries everything needed is self-contained."
)


def judge_task_strings(row: dict) -> list[dict]:
    out = []
    for d in row["delegations"]:
        if not d["task"]:
            continue
        raw = _judge(TASK_JUDGE_SYSTEM,
                     f"SUB-AGENT: {d['agent']}\n"
                     f"ITS TOOLS: {AGENT_TOOLS.get(d['agent'], 'unknown')}\n\n"
                     f"TASK STRING:\n{d['task'][:6000]}")
        m = re.search(r"SELF_CONTAINED:\s*(YES|NO)", raw)
        out.append({"agent": d["agent"],
                    "self_contained": (m.group(1) == "YES") if m else None,
                    "raw": raw[:300]})
    return out


# ---------------------------------------------------------------- scoring

def cmd_score(args) -> None:
    data = json.loads(Path(args.traces).read_text())
    rows = {r["case_id"]: r for r in data["rows"]}
    _, cases = load_dataset()
    cases = [c for c in cases if c["id"] in rows]

    scored = []
    for case in cases:
        row = rows[case["id"]]
        s = {
            "case_id": case["id"],
            "category": case["category"],
            "expected_action": case["expected_action"],
            "error": row.get("error"),
            "citation": score_citation(case, row),
            "delegation": score_delegation(case, row),
            "leak": score_leak(row),
            "cost": score_cost(row),
            "elapsed_s": row.get("elapsed_s"),
        }
        if not args.no_judge and not row.get("error"):
            s["action_judge"] = judge_action(row)
            s["task_strings"] = judge_task_strings(row)
        scored.append(s)
        print(f"scored {case['id']}", flush=True)

    report = summarise(scored)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = RESULTS_DIR / f"orchestration_scores_{stamp}.json"
    out.write_text(json.dumps({"summary": report, "cases": scored}, indent=2))
    print_report(report, scored)
    print(f"\nwrote {out}")


def summarise(scored: list[dict]) -> dict:
    cite = [s for s in scored if s["citation"]["applicable"]]
    judged = [s for s in scored if s.get("action_judge", {}).get("action")]
    tasks = [t for s in scored for t in s.get("task_strings", [])]
    leaks = [s["leak"] for s in scored if s["leak"]["checked"]]

    orch = {"api_calls": 0, "input_tokens": 0, "output_tokens": 0}
    sub = {"api_calls": 0, "input_tokens": 0, "output_tokens": 0}
    per_agent: dict[str, dict] = {}
    for s in scored:
        for k in orch:
            orch[k] += s["cost"]["orchestrator"].get(k, 0)
            sub[k] += s["cost"]["subagent_total"].get(k, 0)
        for agent, u in s["cost"]["per_agent"].items():
            a = per_agent.setdefault(agent, {k: 0 for k in orch})
            for k in a:
                a[k] += u.get(k, 0)
    n = len(scored) or 1
    return {
        "n_cases": len(scored),
        "errors": sum(1 for s in scored if s["error"]),
        "citation_accuracy": {
            "applicable": len(cite),
            "hits": sum(1 for s in cite if s["citation"]["hit"]),
            "unlabelled_citations": sum(
                1 for s in scored if s["citation"].get("unlabelled_citation")),
            "note": ("LOWER BOUND -- ground truth holds only explicitly linked "
                     "duplicates; adjudicate misses by hand"),
        },
        "recommendation_accuracy": {
            "judged": len(judged),
            "correct": sum(1 for s in judged
                           if s["action_judge"]["action"] == s["expected_action"]),
            "confusion": _confusion(judged),
        },
        "delegation_accuracy": {
            "required_present": sum(1 for s in scored
                                    if s["delegation"]["required_present"]),
            "checker_rule_ok": sum(1 for s in scored
                                   if s["delegation"]["checker_rule_ok"]),
            "of": len(scored),
        },
        "task_string_quality": {
            "judged": len(tasks),
            "self_contained": sum(1 for t in tasks if t["self_contained"]),
            "by_agent": {a: sum(1 for t in tasks
                                if t["agent"] == a and t["self_contained"])
                         for a in {t["agent"] for t in tasks}},
        },
        "checker_task_leaks": {
            "checked": sum(l["checked"] for l in leaks),
            "clean": sum(l["clean"] for l in leaks),
        },
        "cost": {
            "orchestrator": orch,
            "subagents": sub,
            "per_agent": per_agent,
            "per_case_orchestrator_tokens": round(
                (orch["input_tokens"] + orch["output_tokens"]) / n),
            "per_case_subagent_tokens": round(
                (sub["input_tokens"] + sub["output_tokens"]) / n),
        },
    }


def _confusion(judged: list[dict]) -> dict:
    out: dict[str, dict[str, int]] = {}
    for s in judged:
        exp, got = s["expected_action"], s["action_judge"]["action"]
        out.setdefault(exp, {}).setdefault(got, 0)
        out[exp][got] += 1
    return out


def print_report(r: dict, scored: list[dict]) -> None:
    print(f"\n=== {r['n_cases']} cases, {r['errors']} errored ===\n")
    c = r["citation_accuracy"]
    print(f"citation accuracy       {c['hits']}/{c['applicable']} "
          f"(cluster-scored, LOWER BOUND) | citations on unlabelled "
          f"cases needing inspection: {c['unlabelled_citations']}")
    a = r["recommendation_accuracy"]
    print(f"recommendation accuracy {a['correct']}/{a['judged']}")
    d = r["delegation_accuracy"]
    print(f"delegation accuracy     required agents {d['required_present']}/{d['of']}"
          f" | checker rule {d['checker_rule_ok']}/{d['of']}")
    t = r["task_string_quality"]
    print(f"task-string quality     {t['self_contained']}/{t['judged']} "
          f"self-contained {t['by_agent']}")
    lk = r["checker_task_leaks"]
    print(f"checker task leaks      {lk['clean']}/{lk['checked']} clean")
    print("\n--- cost, levels kept apart ---")
    print(f"{'level':<16}{'calls':>8}{'in':>10}{'out':>9}")
    for name, u in (("orchestrator", r["cost"]["orchestrator"]),
                    ("sub-agents", r["cost"]["subagents"])):
        print(f"{name:<16}{u['api_calls']:>8}{u['input_tokens']:>10}"
              f"{u['output_tokens']:>9}")
    for agent, u in sorted(r["cost"]["per_agent"].items()):
        print(f"  {agent:<14}{u['api_calls']:>8}{u['input_tokens']:>10}"
              f"{u['output_tokens']:>9}")
    print(f"\nper case: orchestrator {r['cost']['per_case_orchestrator_tokens']} tok, "
          f"sub-agents {r['cost']['per_case_subagent_tokens']} tok")
    if a["confusion"]:
        print("\n--- recommendation confusion (expected -> judged) ---")
        for exp, got in sorted(a["confusion"].items()):
            print(f"  {exp:<32} {got}")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="execute cases, save traces")
    r.add_argument("--limit", type=int)
    r.add_argument("--cases", help="comma-separated case ids")
    r.add_argument("--category")
    r.set_defaults(func=cmd_run)

    s = sub.add_parser("score", help="score a saved trace file")
    s.add_argument("traces")
    s.add_argument("--no-judge", action="store_true",
                   help="mechanical metrics only, no API calls")
    s.set_defaults(func=cmd_score)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
