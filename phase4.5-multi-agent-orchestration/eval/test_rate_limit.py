"""
Force a real GitHub rate limit and watch it propagate.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import github_client
from github_client import gh_get
from orchestrator import orchestrate
from retriever import RetryableToolError

github_client.TOKEN = None

NONEXISTENT_IN_CORPUS = 13650


def burn_the_limit(max_requests: int = 120) -> int:
    """Hammer GitHub unauthenticated until gh_get raises. Returns the request
    count it took, which is the evidence the 403 was real."""
    path = f"/repos/{github_client.REPO}"
    for n in range(1, max_requests + 1):
        try:
            gh_get(path)
        except RetryableToolError as exc:
            print(f"  request #{n} -> RetryableToolError: {exc}")
            return n
        except Exception as exc:
            print(f"  request #{n} -> UNEXPECTED {type(exc).__name__}: {exc}")
            return -1
        if n % 10 == 0:
            print(f"  {n} requests, still 200")
    print(f"  {max_requests} requests without a rate limit; nothing was tripped")
    return -1


def run_with_triage_dead() -> str:
    """Run the full orchestrator while GitHub is rate limited.
    """
    issue_text = (
        "Title: model_validator(mode='before') runs twice when the model is "
        "nested inside a discriminated union\n\n"
        "I have a discriminated union of two models, and the "
        "@model_validator(mode='before') on one of them fires twice for a single "
        "validation call -- once with the raw dict and once with the output of "
        "the first pass. This breaks validators that are not idempotent.\n\n"
        "I think this is the same thing reported in #13650, but that one was "
        "about serialization rather than validation, so I am not certain.\n\n"
        "What is the documented execution order for mode='before' validators on "
        "a model that is a member of a discriminated union?"
    )
    return orchestrate(issue_text)


if __name__ == "__main__":
    print("=== 1. burning the unauthenticated rate limit ===")
    count = burn_the_limit()
    print(f"tripped after {count} requests\n")

    print("=== 2. orchestrator run with GitHub rate limited ===")
    t = time.perf_counter()
    result = run_with_triage_dead()
    print(result)
    print(f"\n{time.perf_counter() - t:.1f}s")

    # What to check in that output:  
    #   [ ] the docs half of the recommendation is present and substantive
    #   [ ] the recommendation SAYS the duplicate check did not run
    #   [ ] it does not present "no duplicate found" as a finding
    #   [ ] it does not invent a duplicate from the orchestrator's own knowledge
    print("\n--- check the four boxes in the source comment above ---")
