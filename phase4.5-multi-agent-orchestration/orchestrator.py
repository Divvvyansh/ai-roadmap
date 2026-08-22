"""
The orchestrator: a tool-use loop whose two tools are full nested agent loops.
"""
from __future__ import annotations

import anthropic
from anthropic.types import MessageParam
from dotenv import load_dotenv

from subagents import run_docs_subagent, run_triage_subagent
from tool_schemas import DELEGATE_TO_DOCS, DELEGATE_TO_TRIAGE

load_dotenv()

MODEL = "claude-sonnet-4-5"
MAX_TURNS = 5

client = anthropic.Anthropic()

SYSTEM = (
    "You triage incoming issues for the pydantic/pydantic repository on behalf of a "
    "maintainer. You have two specialists. You do not answer pydantic questions from your "
    "own knowledge — if a specialist did not tell you, you do not know it.\n"
    "You are writing to a maintainer, never to the reporter, and never in second person "
    "your output is final — nobody will answer a question.\n"
    "Missing information becomes a caveat plus a suggested next step ('ask the reporter for a repro'), not a request. \n\n"

    "Consult both specialists before recommending anything. They are independent, so "
    "request them in the same turn rather than waiting for one to come back. Each starts "
    "from a fresh context and cannot see the issue you are holding — copy what it needs "
    "into the task string.\n\n"

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


def run_delegate_tool(name: str, tool_input: dict) -> tuple[str, bool]:
    """Dispatch one delegate tool_use block. Returns (content, is_error)."""
    if name == "delegate_to_triage_agent":
        content, is_error = run_triage_subagent(tool_input["task"])
    elif name == "delegate_to_docs_agent":
        content, is_error = run_docs_subagent(tool_input["task"])
    else:
        raise NotImplementedError
    return content, is_error


def orchestrate(issue_text: str) -> str:
    messages: list[MessageParam] = [{"role": "user", "content": issue_text}]
    last_text = ""

    while len(messages) < 2*MAX_TURNS + 1:
        response = client.messages.create(
            model=MODEL,
            system=SYSTEM,
            messages=messages,
            tools=[DELEGATE_TO_DOCS, DELEGATE_TO_TRIAGE],
            max_tokens=4000,
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
                tools=[DELEGATE_TO_DOCS, DELEGATE_TO_TRIAGE],
                tool_choice={"type": "none"},
                max_tokens=2000,
            ) 
    messages.append({"role": "assistant", "content": final_response.content})
    last_text = " ".join(
        block.text for block in final_response.content if block.type == "text"
    )
    return last_text

if __name__ == "__main__":
    print(orchestrate(
        "Title: extra='forbid' not rejecting unknown fields on nested model\n\n"
        "When I set model_config = ConfigDict(extra='forbid') on a parent model, "
        "unknown fields on a nested model are still accepted... "
    ))

