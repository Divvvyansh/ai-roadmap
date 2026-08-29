"""
The orchestrator: a tool-use loop whose tools are full nested agent loops.
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed

import anthropic
from anthropic.types import MessageParam
from dotenv import load_dotenv

from retriever import QUERY_CACHE_PATH
from subagents import (
    ISSUE_CACHE_PATH,
    run_checker_subagent,
    run_docs_subagent,
    run_triage_subagent,
)
from tool_schemas import DELEGATE_TO_CHECKER, DELEGATE_TO_DOCS, DELEGATE_TO_TRIAGE

load_dotenv()

MODEL = "claude-opus-5"
MAX_TURNS = 5

client = anthropic.Anthropic()

TOOLS = [DELEGATE_TO_DOCS, DELEGATE_TO_TRIAGE, DELEGATE_TO_CHECKER]

SYSTEM = (
    "You triage incoming issues for the pydantic/pydantic repository on behalf of a "
    "maintainer. You have three specialists. You do not answer pydantic questions from your "
    "own knowledge — if a specialist did not tell you, you do not know it.\n"
    "You are writing to a maintainer, never to the reporter, and never in second person "
    "your output is final — nobody will answer a question.\n"
    "Missing information becomes a caveat plus a suggested next step ('ask the reporter for a repro'), not a request. \n\n"

    "Consult the triage and docs specialists before recommending anything. Those two are "
    "independent of each other, so request them in the same turn rather than waiting for "
    "one to come back. The third, the checker, is not independent of them and is covered "
    "below. Every specialist starts from a fresh context and cannot see the issue you are "
    "holding — copy what it needs into the task string.\n\n"

    "RECONCILING WHAT THEY SAY\n"
    "The two signals point at different maintainer actions. The common combinations:\n"
    "- Duplicate found, docs cover the behaviour: recommend closing as a duplicate, and "
    "include the docs answer and its doc_ids so the reporter gets a real reply.\n"
    "- Duplicate found, docs silent: recommend closing as a duplicate, and flag the "
    "documentation gap.\n"
    "- No duplicate, docs cover it: this is a support question, not a bug. Answer it from "
    "the docs agent's response and cite the doc_ids.\n"
    "- No duplicate, docs silent: a genuinely new issue. Escalate, and say what was ruled "
    "out.\n\n"

    "THE CHECKER\n"
    "The checker retrieves nothing. It is given one issue number, re-reads that issue "
    "itself, and judges whether it actually supports the duplicate claim. It is the only "
    "signal you have that does not come out of the same retrieval the triage agent used, "
    "which is what makes it worth an extra turn.\n\n"

    "It cannot go out with the other two, because it needs an issue number and no issue "
    "number exists until triage answers. Send triage and docs together; if triage comes "
    "back citing an issue you are considering acting on, send the checker in the next "
    "turn. If triage found no duplicate there is nothing to check — do not call it.\n\n"

    "Give the checker the cited issue number and the incoming report, verbatim. Give it "
    "nothing else. Do not pass on triage's verdict, its confidence, its similarity scores, "
    "or the candidates it rejected. The checker is only useful because it reaches its "
    "verdict without seeing triage's; tell it what triage decided and it will grade that "
    "argument instead of re-reading the evidence, and you will have two signals that agree "
    "because one copied the other.\n\n"

    "WHAT EACH VERDICT MEANS FOR THE RECOMMENDATION\n"
    "- DUPLICATE: the citation held up. Recommend closing as a duplicate, and say the "
    "citation was independently verified. A verified citation and an unverified one must "
    "not read the same to a maintainer.\n"
    "- RELATED: same area, different defect. Do not recommend closing. This is the "
    "possible-duplicate case described below: surface the issue number, say what the "
    "checker found different about it, and leave the decision with the maintainer.\n"
    "- REGRESSION: the cited issue was fixed and the behaviour is back. Not a duplicate "
    "and not a new issue. Recommend reopening or linking it as a regression, and name the "
    "fix that no longer holds. This outranks both closing and escalating in urgency — a "
    "fix that silently stopped working affects everyone on that version, not just the "
    "reporter.\n"
    "- UNRELATED: triage cited an issue that does not bear on the report. Treat the "
    "duplicate search as having found nothing and fall back to the no-duplicate rows "
    "above. Say explicitly that a candidate was proposed and rejected on inspection — a "
    "maintainer told simply that nothing was found will go and search for it themselves.\n\n"

    "WHEN TRIAGE AND THE CHECKER DISAGREE\n"
    "The checker wins. Its two directions are not equally reliable: measured against known "
    "duplicate pairs it confirmed 0 of 8 randomly cited issues, so a rejection is rarely a "
    "false alarm — but it also rejected half of the pairs a maintainer had actually closed "
    "as duplicates, so a rejection is not proof the two issues are unrelated. Deferring to "
    "it costs some correct closures and prevents wrong ones, which is the right trade when "
    "the wrong action is closing someone's live bug.\n"
    "Never resolve the disagreement silently. State what triage cited, what the checker "
    "concluded on re-reading it, and that you followed the checker. A maintainer who can "
    "see the disagreement can overrule you in ten seconds; one handed a clean answer "
    "cannot.\n\n"

    "These are the common cases, not an exhaustive set of bins to sort into. The "
    "specialists report degrees of confidence: a near-miss candidate scoring close to the "
    "top one, or docs that cover a feature in general but not the specific configuration "
    "being asked about. Weigh that rather than forcing it into the nearest row. An "
    "uncertain duplicate is worth surfacing as a possible duplicate needing a human look, "
    "which is a different recommendation from both closing it and escalating it.\n\n"

    "OUTPUT\n"
    "Exactly one recommendation, addressed to a maintainer deciding what to do with this "
    "issue. State the action first, then the evidence behind it: the issue numbers and "
    "doc_ids the specialists returned. Say which parts you are confident about and which "
    "you are not. Cite nothing the specialists did not give you."
)


def _cache_sizes() -> tuple[int, int]:
    """(docs query cache, issue embed cache) key counts.
    """
    sizes = []
    for path in (QUERY_CACHE_PATH, ISSUE_CACHE_PATH):
        try:
            sizes.append(len(json.loads(path.read_text())))
        except (FileNotFoundError, json.JSONDecodeError):
            sizes.append(0)
    return sizes[0], sizes[1]

_LEAK_MARKERS = (
    "similarity", "triage", "candidate", "rejected", "confidence",
    "confident", "score", "specialist", "believe", "verify", "top-ranked",
)


def _audit_checker_task(task: str) -> None:
    """Print the checker's task string and flag anything that looks like leaked
    reasoning. Observability only -- never blocks the call.

    Only the text the ORCHESTRATOR wrote is scanned. Everything after the
    ORIGINAL REPORT marker is the reporter's own prose, and reporters write
    "I believe", "I'm confident", "similar to" all the time -- scanning it makes
    the audit fire on the one part of the string that is supposed to be
    verbatim."""
    print(f"[checker] task string ({len(task)} chars):\n{task}\n")
    authored = task.split("ORIGINAL REPORT:", 1)[0]
    hits = [m for m in _LEAK_MARKERS if m in authored.lower()]
    if hits:
        print(f"[checker] LEAK WARNING: task mentions {hits}. The checker may be "
              f"grading triage's argument rather than re-reading the issue; a "
              f"DUPLICATE verdict from this call is not independent.\n")
    else:
        print("[checker] no leak markers found.\n")


def run_delegate_tool(name: str, tool_input: dict) -> tuple[str, bool]:
    """Dispatch one delegate tool_use block. Returns (content, is_error)."""
    if name == "delegate_to_triage_agent":
        content, is_error = run_triage_subagent(tool_input["task"])
    elif name == "delegate_to_docs_agent":
        content, is_error = run_docs_subagent(tool_input["task"])
    elif name == "delegate_to_checker_agent":
        _audit_checker_task(tool_input["task"])
        content, is_error = run_checker_subagent(tool_input["task"])
    else:
        raise NotImplementedError
    return content, is_error


def _run_one_block(block) -> dict:
    """One tool_use block -> one tool_result dict (without tool ID). Must never raise.
    """
    try:
        content, is_error = run_delegate_tool(block.name, block.input)
    except Exception as exc:
        content = f"{type(exc).__name__}: {exc}"
        is_error = True
    tool_result = {
        "type": "tool_result",
        "content": content,
        "is_error": is_error,
    }
    return tool_result


def execute_blocks_serial(blocks) -> list[dict]:
    """Baseline path. Kept only to capture the Step 9 "before" wall clock --
    delete it once the number is recorded in notes.md."""
    tool_results = []
    for block in blocks:
        try:
            content, is_error = run_delegate_tool(block.name, block.input)
        except Exception as exc:
            content = f"{type(exc).__name__}: {exc}"
            is_error = True
        tool_results.append({
            "type": "tool_result",
            "tool_use_id": block.id,
            "content": content,
            "is_error": is_error,
        })
    return tool_results


def execute_blocks_parallel(blocks) -> list[dict]:
    """Same contract as execute_blocks_serial: one tool_result per block, every
    tool_use_id matched, all of them going back in a single user message."""
    with ThreadPoolExecutor(max_workers=len(blocks)) as pool:
        futures = {pool.submit(_run_one_block, block): block for block in blocks}
        tool_results = []
        for fut in as_completed(futures):
            original = futures[fut]
            value = fut.result()
            value["tool_use_id"] = original.id
            tool_results.append(value)

    order = {b.id: i for i, b in enumerate(blocks)}
    return sorted(tool_results, key=lambda r: order[r["tool_use_id"]])


def orchestrate(issue_text: str) -> str:
    messages: list[MessageParam] = [{"role": "user", "content": issue_text}]
    last_text = ""

    while len(messages) < 2*MAX_TURNS + 1:
        response = client.messages.create(
            model=MODEL,
            system=SYSTEM,
            messages=messages,
            tools=TOOLS,
            max_tokens=4000,
        )
        messages.append({"role": "assistant", "content": response.content})
        last_text = " ".join(
            block.text for block in response.content if block.type == "text"
        )

        if response.stop_reason == "tool_use":
            blocks = [b for b in response.content if b.type == "tool_use"]
            tool_results = execute_blocks_parallel(blocks)
            messages.append({"role": "user", "content": tool_results})
        elif response.stop_reason == "end_turn":
            return last_text
        elif response.stop_reason == "max_tokens":
            return f"Token limit exhausted: Partial result is {last_text}"
        else:
            return (f"Failed with stop_reason={response.stop_reason}. "
                                f"Partial result: {last_text}")

    final_response = client.messages.create(
                model=MODEL,
                system=SYSTEM,
                messages=messages,
                tools=TOOLS,
                tool_choice={"type": "none"},
                max_tokens=2000,
            ) 
    messages.append({"role": "assistant", "content": final_response.content})
    last_text = " ".join(
        block.text for block in final_response.content if block.type == "text"
    )
    return last_text

def issue_text_from_corpus(number: int) -> str:
    """The body of a real harvested issue, verbatim, as the orchestrator's input.

    Used to force the checker path: pass the `duplicate` side of a pair from
    eval/duplicate_pairs.json and triage has a real prior issue to find, so it
    produces a citation the orchestrator then has to verify.
    """
    import json
    from subagents import ISSUES_PATH
    import subagents
    for line in open(ISSUES_PATH):
        issue = json.loads(line)
        if issue["number"] == number:
            subagents.EXCLUDE_FROM_SEARCH.add(number)
            return f"Title: {issue['title']}\n\n{(issue['body'] or '')[:3000]}"
    raise ValueError(f"#{number} is not in the corpus")


if __name__ == "__main__":
    import sys
    import time
    if len(sys.argv) > 1:
        issue_text = issue_text_from_corpus(int(sys.argv[1]))
    else:
        issue_text = (
            "Title: extra='forbid' not rejecting unknown fields on nested model\n\n"
            "When I set model_config = ConfigDict(extra='forbid') on a parent model, "
            "unknown fields on a nested model are still accepted... "
        )

    docs_before, issues_before = _cache_sizes()
    t = time.perf_counter()
    print(orchestrate(issue_text))
    elapsed = time.perf_counter() - t
    docs_after, issues_after = _cache_sizes()
    print(f"\n{elapsed:.1f}s")
    print(f"new embeddings this run: "
          f"docs {docs_after - docs_before}, issues {issues_after - issues_before}")
