"""
Sub-agents: triage (duplicate detection over issue history) and docs (pydantic
docs RAG). Each is a full tool-use loop that collapses to ONE string.

The orchestrator in Week 2 sees only that string plus an is_error flag. It never
sees the candidates a sub-agent considered and rejected, how many turns it took,
or which tools it called.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
from pathlib import Path

import anthropic
import chromadb
import voyageai
import voyageai.error
from anthropic.types import MessageParam
from dotenv import load_dotenv

from retriever import RetryableToolError, retrieve as retrieve_docs
from tool_schemas import GET_ISSUE_TOOL, SEARCH_DOCS_TOOL, SEARCH_ISSUES_TOOL

from github_client import fetch_issue

load_dotenv()

MODEL = "claude-haiku-4-5"
MAX_TURNS = 6

SEARCH_TOOLS = ("search_issues", "search_docs")

DOCS_COLLECTION = "pydantic_docs_structured"
ISSUES_COLLECTION = "issues_title_desc_code"
CHROMA_PATH = Path(__file__).parent / "chroma_store"
ISSUES_PATH = Path(__file__).parent / "corpus" / "issues.jsonl"

ISSUE_CACHE_PATH = Path(__file__).parent / "eval" / ".issue_embed_cache.json"

client = anthropic.Anthropic()
vo = voyageai.Client()
chroma_client = chromadb.PersistentClient(path=str(CHROMA_PATH))

_issue_cache: dict[str, list[float]] | None = None
_issue_cache_lock = threading.Lock()

# ---------------------------------------------------------------- issue search

def embed_issue_text(text: str, use_cache: bool = True) -> list[float]:
    """
    Embed issue text for searching the issue collection.
    """
    global _issue_cache
    key = hashlib.sha256(text.encode()).hexdigest()[:16]

    with _issue_cache_lock:
        if _issue_cache is None:
            try:
                _issue_cache = json.loads(ISSUE_CACHE_PATH.read_text())
            except (FileNotFoundError, json.JSONDecodeError):
                _issue_cache = {}
        if use_cache and key in _issue_cache:
            return _issue_cache[key]

    for attempt in range(3):
        try:
            embedding = [float(x) for x in vo.embed(
                [text], model="voyage-3.5", input_type=None).embeddings[0]]
            break
        except voyageai.error.RateLimitError:
            wait = 20 * (attempt + 1)
            print(f"  rate limited, waiting {wait}s (attempt {attempt + 1}/3)")
            time.sleep(wait)
    else:
        raise RetryableToolError("Voyage embedding failed after 3 rate-limit retries. try again later.")

    with _issue_cache_lock:
        _issue_cache[key] = embedding
        ISSUE_CACHE_PATH.parent.mkdir(exist_ok=True)
        ISSUE_CACHE_PATH.write_text(json.dumps(_issue_cache))
    return embedding


# Test-only. Numbers search_issues will not return.

EXCLUDE_FROM_SEARCH: set[int] = set()


def search_issues(query: str, k: int = 5) -> list[dict]:

    embedded_query = embed_issue_text(query)
    collection = chroma_client.get_collection(ISSUES_COLLECTION)
    results = collection.query(
        query_embeddings=[embedded_query],
        n_results=k + len(EXCLUDE_FROM_SEARCH),
        include=["metadatas", "distances"],
    )
    hits = []
    for metadata, distance in zip(results["metadatas"][0], results["distances"][0]):
        if metadata["number"] in EXCLUDE_FROM_SEARCH:
            continue
        if len(hits) >= k:
            break
        similarity = 1 - distance  
        hits.append(
            {
                "number": metadata["number"],
                "title": metadata["title"],
                "similarity": similarity,
                "html_url": metadata["html_url"],
            }
        )
    return hits

def get_issue(number: int) -> dict | None:
    """Full text of one issue from the harvested corpus and the github API."""
    with open(ISSUES_PATH, "r") as f:
        for line in f:
            issue = json.loads(line)
            if issue["number"] == number:
                break
        else:
            issue = None
    if issue is None:
        new_issue = fetch_issue(number)
        if new_issue is not None:
            return new_issue
        return None
    output_issue = {
        "number": issue["number"],
        "title": issue["title"],
        "body": issue["body"],
        "labels": issue["labels"],
        "state_reason": issue["state_reason"],
        "closed_at": issue["closed_at"] if issue["closed_at"] else None,
    }
    return output_issue


def run_tool(name: str, tool_input: dict) -> str:
    """Dispatch one tool_use block. Returns the string the model will read."""
    tool_output = ""
    if name == "search_issues":
        hits = search_issues(tool_input["query"])
        for hit in hits:
            tool_output += f" [{hit['number']} : {hit['title']} : {hit['similarity']:.2f} : {hit['html_url']}]"
        return tool_output
    elif name == "get_issue":
        issue = get_issue(tool_input["number"])
        if issue:
            tool_output = f" [{issue['number']} : {issue['title']} : {issue['body']} : {issue['labels']} : {issue['state_reason']} : {issue['closed_at']}]"
        else:
            tool_output = "No issue found with that number."
        return tool_output
    elif name == "search_docs":
        chunks = retrieve_docs(tool_input["query"], k=8, threshold=0.45, collection_name=DOCS_COLLECTION)
        if not chunks:
            return "No results found in the documentation." 
        else:
            resp = ""
            blocks = []
            for c in chunks:
                block = f" [{c.doc_id} : {c.text}]"
                blocks.append(block)
            response = resp.join(blocks)
            return response
    else:
        raise ValueError(f"Unknown tool: {name}")

def run_subagent(
    task: str,
    system: str,
    tools: list[dict],
    essential_tools: tuple[str, ...] = SEARCH_TOOLS,
    essential_label: str = "corpus searches",
) -> tuple[str, bool]:
    
    messages: list[MessageParam] = [{"role": "user", "content": task}]
    last_text = ""

    essential_ok = 0
    essential_failed = 0
    secondary_failed = 0  
    hard_failure = False
    hard_failure_note = ""

    while len(messages) < 2*MAX_TURNS + 1:
        response = client.messages.create(
            model=MODEL,
            system=system,
            messages=messages,
            tools=tools,
            max_tokens=1500,
        )
        messages.append({"role": "assistant", "content": response.content})
        last_text = " ".join(
            block.text for block in response.content if block.type == "text"
        )

        if response.stop_reason == "tool_use":
            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                try:
                    content = run_tool(block.name, block.input)
                    failed = False
                    if block.name in essential_tools:
                        essential_ok += 1
                except RetryableToolError as exc:
                    content = f"{exc} — this tool call did not run."
                    failed = True
                    if block.name in essential_tools:
                        essential_failed += 1
                    else:
                        secondary_failed += 1
                except Exception as exc:
                    content = f"{type(exc).__name__}: {exc}"
                    failed = True
                    hard_failure = True
                    hard_failure_note = content

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": content,
                    "is_error": failed,
                })
            messages.append({"role": "user", "content": tool_results})
        elif response.stop_reason == "end_turn":
            if hard_failure and essential_ok == 0:
                return (f"Tool failure, not retryable: {hard_failure_note}. No "
                        f"{essential_label} succeeded, so no verdict was reached. "
                        f"Retrying will fail identically until the deployment is "
                        f"fixed."), True
            if hard_failure:
                return (f"PARTIAL RESULT: a tool failed permanently ({hard_failure_note}) and "
                        f"will keep failing, so part of this check never ran. Treat the "
                        f"finding below as incomplete rather than conclusive.\n\n{last_text}"), False 
            if essential_failed and essential_ok == 0:
                return (f"Rate limited: all {essential_failed} {essential_label} failed "
                        f"and none succeeded, so no evidence was gathered and no verdict "
                        f"was reached. Retry later."), True
            if essential_ok == 0:
                return (f"No verdict: the agent answered without a single successful call "
                        f"to {' or '.join(essential_tools)}, so nothing below rests on "
                        f"retrieved evidence. Discard it."), True
            if essential_failed or secondary_failed:
                caveats = []
                if essential_failed:
                    total = essential_ok + essential_failed
                    caveats.append(
                        f"{essential_failed} of {total} {essential_label} were rate "
                        f"limited and did not run, so the evidence is incomplete")
                if secondary_failed:
                    caveats.append(
                        f"{secondary_failed} supporting issue lookup(s) were rate limited, "
                        f"so those issues could not be read — the {essential_label} "
                        f"themselves were unaffected")
                return (f"PARTIAL RESULT: {'; '.join(caveats)}. Treat the finding below "
                        f"as incomplete rather than conclusive.\n\n{last_text}"), False
            return last_text, False
        elif response.stop_reason == "max_tokens":
            return (f"Sub-agent could not generate a full response due to running out "
                    f"of tokens. Partial result: {last_text}"), False
        else:
            return (f"Sub-agent failed with stop_reason={response.stop_reason}. "
                    f"Partial result: {last_text}"), True

    return (f"Sub-agent did not finish within its turn budget. "
            f"Partial result: {last_text}"), True


def run_triage_subagent(task: str) -> tuple[str, bool]:
    system = (
        "You are a triage agent for the pydantic/pydantic GitHub repository. Given a "
        "bug report or question, decide whether it duplicates a previously closed issue.\n\n"

        "Your output is read by another agent, not by a person. Be terse and factual: "
        "no greetings, no praise, no offers of further help, no second person.\n\n"

        "PROCEDURE\n"
        "1. If the report cites an issue number, call get_issue on that number before "
        "searching. A number the reporter supplied is a claim, not a finding — it may be "
        "unrelated, may not exist, or may be a pull request. If the lookup fails or comes "
        "back empty, say so explicitly and carry on; never repeat a cited number as though "
        "you confirmed it.\n"
        "2. Rewrite the report as a natural-language search query and call search_issues.\n"
        "3. Call get_issue on 2-3 candidates and read their bodies. Do not commit to the "
        "top-ranked candidate without reading others.\n\n"
        "4. After a duplicate is found or 2 tool calls have been made to search_issues, decide, then answer in a single final message.\n\n"

        "BUDGET\n"
        "1. Do not make more than 2 search_issues tool calls.\n"
        "Irrelevant candidates are the 'no duplicate found' answer, not a reason to search again.\n\n" 
        f"2. You only get {MAX_TURNS} message turns. Reserve the last message for the final decision and response.\n\n"

        "THE SIMILARITY SCORE IS NOT EVIDENCE. Measured against known duplicate pairs, "
        "true duplicates score a median of 0.884 and unrelated issues a median of 0.864, "
        "and in roughly half of all cases an unrelated issue outranks the true duplicate. "
        "Use the score to choose which candidates to read; never to conclude that one is "
        "a duplicate. Judge on body text, labels, and state_reason.\n\n"

        "ANSWER FORMAT\n"
        "- Duplicate found: the issue number, its state_reason and closed_at, and one or "
        "two sentences on what it covered and why it matches.\n"
        "- No duplicate found: say so in the first line, then list every candidate. Before you print anything, the first line must say no duplicates found. "
        "search_issues returned as 'number - title - similarity', each with a short reason "
        "it was rejected. Finding no duplicate is a valid, successful result — state it "
        "plainly, do not apologise or hedge. Retrieval surfaces the correct prior issue "
        "only about 72% of the time, so those rejected candidates are the caller's only "
        "signal that a near-miss existed. " 
        "The similarity must contain 'similairty: ' and the similarity score that you found explicitly. ")
    return run_subagent(task, system, [SEARCH_ISSUES_TOOL, GET_ISSUE_TOOL])


def run_docs_subagent(task: str) -> tuple[str, bool]:
    system = (
        "You answer questions about pydantic using only pydantic's own documentation.\n\n"

        "Your output is read by another agent, not by a person. Be terse and factual: "
        "no greetings, no offers of further help.\n\n"

        "PROCEDURE\n"
        "1. Rewrite the question as a natural-language search query and call search_docs.\n"
        "2. Answer only from the returned chunks, citing the doc_id of each chunk relied on.\n\n"

        "GROUNDING\n"
        "Assert nothing the retrieved chunks do not support. Retrieval returns chunks for "
        "almost any input, including questions the documentation does not cover — chunks "
        "coming back is not evidence the question is answerable, and at the configured "
        "threshold roughly half of out-of-scope questions still retrieve something. If the "
        "chunks do not contain the answer, say exactly that and name the doc_ids that came "
        "back instead. A grounded 'the documentation does not cover this' is a correct "
        "answer, not a failure.")
    return run_subagent(task, system, [SEARCH_DOCS_TOOL])


# ------------------------------------------------------------------- checker

def run_checker_subagent(task: str) -> tuple[str, bool]:
    """Verify that a cited issue actually supports the claim made about it.

    Deliberately blind to triage's reasoning: it re-reads the cited issue itself
    and judges the citation, not the argument that produced it.
    """
    system = (
        "You are a github issue checking agent that checks if a new issue is a real duplicate of the issue that the input says it is. \n"
        "Your output is read by another agent, not by a person. Be terse and factual: \n"
        "no greetings, no praise, no offers of further help, no second person.\n\n"

        "Procedure: \n"
        "1. Always call the get_issue tool before you produce a response. \n"
        "2. From the input message, extract the issue number that is a potential duplicate and pull up its details using the tool. \n"
        "3. Look at the new issue in the input and the potential duplicate that you pulled using the tool and compare them. \n"
        "4. Verify and conclude whether the duplicate issue indeed fully duplicates the new issue. \n\n"

        "WHAT COUNTS AS A DUPLICATE\n"
        "The bar is a shared cause, not a shared topic. Two issues are duplicates "
        "when the change that resolved the cited issue would also resolve the new "
        "report. Same feature, same config key, or same error message is not "
        "enough on its own: pydantic issues share heavy template boilerplate and a "
        "small API surface, so unrelated reports routinely name the same thing.\n\n"

        "You are not choosing the best match. You were handed one issue and no "
        "alternatives, and 'this does not clear the bar' is a correct and expected "
        "answer. Do not reach for a way to make the claim work.\n\n"

        "Check three things against the cited issue's body, labels and "
        "state_reason:\n"
        "1. TRIGGER -- what input, config, or call sequence produces the "
        "behaviour. Same symptom reached by a different trigger is not a "
        "duplicate.\n"
        "2. BEHAVIOUR, in specifics -- 'validation does not fire' and 'validation "
        "fires with the wrong error type' are different bugs, not two wordings of "
        "one.\n"
        "3. RESOLUTION -- state_reason 'completed' means the cited issue was "
        "fixed, so a new report of that same behaviour is either a different bug "
        "or a regression; say which, rather than confirming a duplicate. "
        "state_reason 'not_planned' means the behaviour was intentional, which "
        "supports the claim only if the new report asks for the same thing that "
        "was declined.\n\n"

        "Reject these, even though each is genuinely related:\n"
        "- Same feature, different configuration, type, or nesting depth.\n"
        "- The cited issue is a broad umbrella; the new report is one specific "
        "case inside it that the cited issue never addressed.\n"
        "- One is a bug report and the other a feature request about the same "
        "behaviour.\n"
        "- The cited issue was closed before a version the new report is running "
        "on.\n"
        "- The cited issue is a question that was answered, and the new report is "
        "a defect claim about the same area.\n\n"

        "Answer format: \n"
        "Begin your response with a line reading exactly 'VERDICT: X', where X is "
        "one of DUPLICATE, RELATED, REGRESSION, UNRELATED. Nothing else on that "
        "line. Then the explanation.\n"
        "If the duplicate issue clears the bar to qualify as a genuine duplicate - say so directly in the first line. "
        "Then quote text from the duplicate issue that supports your claim of why it is a genuine duplicate. \n"
        "If, for any reason the duplicate issue turns out to be related to the new issue - first clearly state that it is not a duplicate  "
        "then proceed to explain how it is related any why it did not clear the bar to qualify as a genuine duplicate. \n"
        "If the new issue falls under the category of being a regression or a different bug - state so and support your claim. \n"
        "If the duplicate issue is nota genuine duplicate and neither related to the new issue - say so directly in one line. \n\n"

        "Ground rules: \n"
        "1. Only conclude that an issue is an genuine duplicate if you can quote specififc text from the fetched issue that can fully support the claim. \n"
        "2. The input potential duplicate comes from another sub-agent that wanted its claim to be true - Challenge it fully before making an conclusion, \n\n"
    )
    return run_subagent(
        task, system, [GET_ISSUE_TOOL],
        essential_tools=("get_issue",),
        essential_label="cited-issue lookups",
    )


REPORT = (
    "Title: extra='forbid' not rejecting unknown fields on nested model\n\n"
    "When I set model_config = ConfigDict(extra='forbid') on a parent model, "
    "unknown fields on a nested model are still accepted."
)


def _check(number: int) -> tuple[str, bool]:
    return run_checker_subagent(
        f"CLAIM: the report below duplicates issue #{number}.\n\n"
        f"ORIGINAL REPORT:\n{REPORT}"
    )


def main_checker():
    """Three cases. #11166 is a plausible citation, #10656 ('cannot pickle
    _thread.RLock') is a wrong one, and #99999 forces the lookup to fail.
    """
    global fetch_issue

    for number in (11166, 10656):
        content, is_error = _check(number)
        print(f"----- cited #{number}  is_error={is_error}\n{content}\n")

    calls = []
    real_fetch_issue = fetch_issue

    def _raising_fetch_issue(number: int):
        calls.append(number)
        raise RetryableToolError(
            "FORCED(test): GitHub rate limit hit. Try after: 3600 seconds")

    fetch_issue = _raising_fetch_issue
    try:
        content, is_error = _check(99999)
    finally: 
        fetch_issue = real_fetch_issue

    print(f"----- cited #99999 (forced lookup failure)  is_error={is_error}\n"
          f"{content}\n")

    if not calls:
        print("INCONCLUSIVE: fetch_issue was never called, so the forced failure "
              "path did not run. Whatever produced the result above, it was not "
              "this test.")
    elif not is_error:
        print(f"FAIL: fetch_issue raised on {calls}, but the sub-agent returned "
              f"is_error=False. An unverifiable citation was reported as a "
              f"usable result.")
    else:
        print(f"OK: fetch_issue raised on {calls}, and the failure reached the "
              f"orchestrator as is_error=True.")


PAIRS_PATH = Path(__file__).parent / "eval" / "duplicate_pairs.json"

VERDICTS = ("DUPLICATE", "RELATED", "REGRESSION", "UNRELATED")


def _verdict(text: str) -> str:
    """Read the mandated VERDICT: line. UNPARSED is a result, not an error --
    it counts how often the prompt failed to emit the token at all."""
    for line in text.splitlines():
        line = line.strip()
        if line.upper().startswith("VERDICT:"):
            label = line.split(":", 1)[1].strip().upper()
            return label if label in VERDICTS else f"UNPARSED({label[:20]})"
    return "UNPARSED(no verdict line)"


def _corpus_index() -> dict[int, dict]:
    return {i["number"]: i for i in
            (json.loads(l) for l in open(ISSUES_PATH))}


def main_checker_pairs(n: int = 8, seed: int = 0):
    """Both halves of the confusion matrix in one run.

    For each known duplicate pair, the checker is asked the same question twice:
    once citing the issue a maintainer actually closed it against (should
    confirm), once citing a random unrelated corpus issue (should not). One
    number without the other says nothing -- a checker that always confirms and
    one that always rejects each score 100% on one half.
    """
    import random

    index = _corpus_index()
    pairs = [p for p in json.loads(PAIRS_PATH.read_text())
             if p["duplicate"] in index and p["original"] in index]
    rng = random.Random(seed)
    sample = rng.sample(pairs, min(n, len(pairs)))
    others = [num for num in index if num not in
              {x for p in sample for x in (p["duplicate"], p["original"])}]

    true_counts: dict[str, int] = {}
    rand_counts: dict[str, int] = {}

    for pair in sample:
        dup = index[pair["duplicate"]]
        report = f"Title: {dup['title']}\n\n{(dup['body'] or '')[:2000]}"
        decoy = rng.choice(others)

        for cited, counts, kind in ((pair["original"], true_counts, "true"),
                                    (decoy, rand_counts, "rand")):
            content, is_error = run_checker_subagent(
                f"CLAIM: the report below duplicates issue #{cited}.\n\n"
                f"ORIGINAL REPORT:\n{report}"
            )
            v = "ERROR" if is_error else _verdict(content)
            counts[v] = counts.get(v, 0) + 1
            print(f"  #{dup['number']:>6} vs #{cited:<6} [{kind}] -> {v}")

    total = len(sample)
    print(f"\n{'verdict':<28} {'true pair':>10} {'random':>10}")
    for v in sorted(set(true_counts) | set(rand_counts)):
        print(f"{v:<28} {true_counts.get(v, 0):>10} {rand_counts.get(v, 0):>10}")
    print(f"{'-- n':<28} {total:>10} {total:>10}")
    print(f"\nconfirm rate: true pairs {true_counts.get('DUPLICATE', 0)}/{total}, "
          f"random citations {rand_counts.get('DUPLICATE', 0)}/{total}")
    unparsed = sum(c for v, c in (*true_counts.items(), *rand_counts.items())
                   if v.startswith("UNPARSED"))
    if unparsed:
        print(f"WARNING: {unparsed}/{2 * total} responses had no parseable "
              f"VERDICT line -- the numbers above undercount everything.")


if __name__ == "__main__":
    main_checker()
