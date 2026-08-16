"""
Sub-agents: triage (duplicate detection over issue history) and docs (pydantic
docs RAG). Each is a full tool-use loop that collapses to ONE string.

The orchestrator in Week 2 sees only that string plus an is_error flag. It never
sees the candidates a sub-agent considered and rejected, how many turns it took,
or which tools it called.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import anthropic
import chromadb
import voyageai
import voyageai.error
from anthropic.types import MessageParam
from dotenv import load_dotenv

from retriever import retrieve as retrieve_docs
from tool_schemas import GET_ISSUE_TOOL, SEARCH_DOCS_TOOL, SEARCH_ISSUES_TOOL

load_dotenv()

MODEL = "claude-haiku-4-5"
MAX_TURNS = 6

DOCS_COLLECTION = "pydantic_docs_structured"
ISSUES_COLLECTION = "issues_title_desc_code"
CHROMA_PATH = Path(__file__).parent / "chroma_store"
ISSUES_PATH = Path(__file__).parent / "corpus" / "issues.jsonl"

client = anthropic.Anthropic()
vo = voyageai.Client()
chroma_client = chromadb.PersistentClient(path=str(CHROMA_PATH))


# ---------------------------------------------------------------- issue search

def embed_issue_text(text: str) -> list[float]:
    """
    Embed issue text for searching the issue collection.

    input_type=None matches ingest_issues.py: duplicate detection is symmetric,
    both sides are issues. Do NOT reuse retriever.embed_query() here — it passes
    input_type="query", correct for question-against-passage docs search and
    wrong for this. The mismatch would not error, only degrade recall.

    Retries on rate limits like every other embedding path in this project. The
    triage agent issues several searches per run and Voyage's free tier is 3
    req/min, so an un-retried call fails mid-conversation.
    """
    for attempt in range(3):
        try:
            return [float(x) for x in vo.embed(
                [text], model="voyage-3.5", input_type=None).embeddings[0]]
        except voyageai.error.RateLimitError:
            wait = 20 * (attempt + 1)
            print(f"  rate limited, waiting {wait}s (attempt {attempt + 1}/3)")
            time.sleep(wait)
    raise RuntimeError("Voyage embedding failed after 3 rate-limit retries")


def search_issues(query: str, k: int = 5) -> list[dict]:

    embedded_query = embed_issue_text(query)
    collection = chroma_client.get_collection(ISSUES_COLLECTION)
    results = collection.query(
        query_embeddings=[embedded_query],
        n_results=k,
        include=["metadatas", "distances"],
    )
    hits = []
    for metadata, distance in zip(results["metadatas"][0], results["distances"][0]):
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
    """Full text of one issue from the harvested corpus."""
    with open(ISSUES_PATH, "r") as f:
        for line in f:
            issue = json.loads(line)
            if issue["number"] == number:
                break
        else:
            issue = None
    if issue is None:
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

def run_subagent(task: str, system: str, tools: list[dict]) -> tuple[str, bool]:
    """
    Run one sub-agent to completion. Returns (content_for_tool_result, is_error).
    """
    messages: list[MessageParam] = [{"role": "user", "content": task}]
    last_text = ""

    while len(messages) < 2*MAX_TURNS + 1:
        response = client.messages.create(
            model=MODEL,
            system=system,
            messages=messages,
            tools=tools,
            max_tokens=1000,
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
                except Exception as exc:
                    content = f"{type(exc).__name__}: {exc}"
                    failed = True
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": content,
                    "is_error": failed,
                })
            messages.append({"role": "user", "content": tool_results})
        elif response.stop_reason == "end_turn":
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
        "1. Rewrite the report as a natural-language search query and call search_issues.\n"
        "2. Call get_issue on 2-3 candidates and read their bodies. Do not commit to the "
        "top-ranked candidate without reading others.\n"
        "3. Decide, then answer in a single final message.\n\n"

        "THE SIMILARITY SCORE IS NOT EVIDENCE. Measured against known duplicate pairs, "
        "true duplicates score a median of 0.884 and unrelated issues a median of 0.864, "
        "and in roughly half of all cases an unrelated issue outranks the true duplicate. "
        "Use the score to choose which candidates to read; never to conclude that one is "
        "a duplicate. Judge on body text, labels, and state_reason.\n\n"

        "ANSWER FORMAT\n"
        "- Duplicate found: the issue number, its state_reason and closed_at, and one or "
        "two sentences on what it covered and why it matches.\n"
        "- No duplicate found: say so in the first line, then list every candidate "
        "search_issues returned as 'number - title - similarity', each with a short reason "
        "it was rejected. Finding no duplicate is a valid, successful result — state it "
        "plainly, do not apologise or hedge. Retrieval surfaces the correct prior issue "
        "only about 72% of the time, so those rejected candidates are the caller's only "
        "signal that a near-miss existed.")
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


def main():
    content, is_error = run_triage_subagent(
        "A user reports that model_config = ConfigDict(extra='forbid') is not "
        "rejecting unknown fields on a nested model. Is this a known duplicate?"
    )
    print(f"is_error={is_error}\n{content}")


if __name__ == "__main__":
    main()
