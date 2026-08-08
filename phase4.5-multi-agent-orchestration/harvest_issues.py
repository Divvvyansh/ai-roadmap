"""
Harvest pydantic/pydantic issues + duplicate ground truth from the GitHub REST API.

Outputs:
  corpus/issues.jsonl        one JSON object per issue (the retrieval corpus)
  eval/duplicate_pairs.json  [{"duplicate": N, "original": M, "confidence": "..."}]
"""
from __future__ import annotations  # venv is 3.9; makes `X | None` annotations legal

import json
import os
import re
import time
from pathlib import Path
import requests
from dotenv import load_dotenv

load_dotenv()

REPO = "pydantic/pydantic"
API = "https://api.github.com"
TOKEN = os.environ["GITHUB_TOKEN"]

CORPUS_PATH = Path(__file__).parent / "corpus" / "issues.jsonl"
PAIRS_PATH = Path(__file__).parent / "eval" / "duplicate_pairs.json"

HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}

ISSUE_REF = (
    r"(?:#|https?://github\.com/(?P<repo>[\w.-]+/[\w.-]+)/issues/)(?P<num>\d+)"
)

DUP_PATTERNS = [
    (rf"\b(?:duplicate|dupe?)\s+of\b[^\n]{{0,40}}?{ISSUE_REF}", "explicit"),
    (ISSUE_REF, "bare_ref"),
]


def gh_get(path: str, params: dict | None = None) -> requests.Response:
    """One GET against the GitHub API, with primary-rate-limit handling."""
    try:
        response = requests.get(f"{API}{path}", headers=HEADERS, params=params)
        if response.status_code == 403 and response.headers.get("x-ratelimit-remaining") == "0":
            reset_time = int(response.headers.get("x-ratelimit-reset", time.time() + 60))
            sleep_time = max(reset_time - time.time(), 0)
            print(f"Rate limit hit. Sleeping for {sleep_time:.2f} seconds.")
            time.sleep(sleep_time)
            return gh_get(path, params) 
        elif response.status_code == 429:
            retry_after = int(response.headers.get("retry-after", 60))
            print(f"Secondary rate limit hit. Sleeping for {retry_after} seconds.")
            time.sleep(retry_after)
            return gh_get(path, params)  
        response.raise_for_status()
        return response
    except requests.RequestException as e:
        print("An error occurred while making the request.", e)
        return requests.Response()  
        

def trim(issue: dict) -> dict:
    """Keep only the fields worth embedding or filtering on."""
    return {
        "number": issue["number"],
        "title": issue["title"],
        "body": issue.get("body"),
        "labels": [label["name"] for label in issue.get("labels", [])],
        "state_reason": issue.get("state_reason"),
        "created_at": issue["created_at"],
        "closed_at": issue["closed_at"],
        "html_url": issue["html_url"],
        "comments_count": issue.get("comments", 0),
    }


def fetch_issue_page(params: dict) -> tuple[list[dict], bool]:
    """One page of the issues list, PRs dropped, trimmed. Second value is
    False when the page came back empty, i.e. pagination is done."""
    response = gh_get(f"/repos/{REPO}/issues", params=params)
    issues = response.json()
    return [trim(i) for i in issues if "pull_request" not in i], bool(issues)


def fetch_closed_issues(max_issues: int | None = None, max_pages: int = 300) -> list[dict]:
    """Page through closed issues, newest first, skipping pull requests."""
    filtered_issues = []
    for page in range(1, max_pages + 1):
        batch, had_results = fetch_issue_page(
            {"state": "closed", "per_page": 100, "page": page}
        )
        if not had_results:
            break
        filtered_issues.extend(batch)
        if max_issues is not None and len(filtered_issues) >= max_issues:
            break
        if page % 10 == 0:
            print(f"  page {page}: {len(filtered_issues)} issues so far")
    return filtered_issues[:max_issues] if max_issues else filtered_issues


def fetch_duplicate_labelled(limit: int = 200) -> list[dict]:
    """Closed issues carrying the `duplicate` label -- the ground-truth candidates."""
    filtered_issues = []
    for page in range(1, (limit // 100) + 2):
        batch, had_results = fetch_issue_page(
            {"state": "closed", "labels": "duplicate", "per_page": 100, "page": page}
        )
        if not had_results:
            break
        filtered_issues.extend(batch)
    return filtered_issues[:limit]


def fetch_issue(number: int) -> dict | None:
    """Fetch one issue by number. None if it doesn't exist or is a PR."""
    response = gh_get(f"/repos/{REPO}/issues/{number}")
    if response.status_code != 200:
        return None
    issue = response.json()
    return None if "pull_request" in issue else trim(issue)


def extract_original(comments: list[dict], issue_number: int) -> tuple[int, str] | None:
    """Find which issue this one duplicates, from its closing comments.

    Patterns are the outer loop so confidence dominates position: an explicit
    "duplicate of #N" in any comment beats a bare "#N" in an earlier one.
    Comments are scanned newest-first, since the closing remark carries the
    verdict and earlier comments are usually discussion.

    A match is rejected when it points at this same issue, or at another
    repository -- a cross-repo original can never be retrieved from this index,
    so recording the pair would guarantee a recall miss that isn't retrieval's
    fault.

    Returns (original_number, confidence) or None if nothing usable was found.
    """
    for pattern, confidence in DUP_PATTERNS:
        for comment in reversed(comments):
            for match in re.finditer(pattern, comment.get("body") or "", re.IGNORECASE):
                if match.group("repo") not in (None, REPO):
                    continue
                original_number = int(match.group("num"))
                if original_number != issue_number:
                    return original_number, confidence
    return None


def build_pairs(dup_issues: list[dict]) -> list[dict]:
    """One API call per duplicate-labelled issue -> its comments -> a pair."""
    pairs =[]
    for issue in dup_issues:
        issue_number = issue["number"]
        response = gh_get(f"/repos/{REPO}/issues/{issue_number}/comments")
        comments = response.json()
        original_info = extract_original(comments, issue_number)
        if original_info:
            original_number, confidence = original_info
            print(f"Found duplicate pair: {issue_number} -> {original_number} (confidence: {confidence})")
            pairs.append({
                "duplicate": issue_number,
                "original": original_number,
                "confidence": confidence
            })
    print(f"Total pairs found: {len(pairs)} out of {len(dup_issues)} duplicate-labelled issues.")
    return pairs


def main(max_issues: int = 2000):
    corpus = {i["number"]: i for i in fetch_closed_issues(max_issues=max_issues)}
    print(f"{len(corpus)} closed issues in the harvest window")

    dup_issues = fetch_duplicate_labelled(limit=200)
    pairs = build_pairs(dup_issues)

    for issue in dup_issues:
        corpus.setdefault(issue["number"], issue)

    # An `original` outside the window would score 0 at eval time and be
    # indistinguishable from a retrieval miss. Fetch each one explicitly so the
    # target is guaranteed to be in the index before recall@k is ever computed.
    missing = sorted({p["original"] for p in pairs} - corpus.keys())
    print(f"{len(missing)} originals fall outside the window; fetching directly")

    unresolvable = set()
    for number in missing:
        issue = fetch_issue(number)
        if issue is None:
            unresolvable.add(number)  
            continue
        corpus[number] = issue

    # A pair whose "original" is a PR is bad ground truth, not a hard retrieval case. Drop them.
    kept = [p for p in pairs if p["original"] not in unresolvable]
    print(f"dropped {len(pairs) - len(kept)} pairs whose original was a PR or missing")
    by_confidence = {}
    for p in kept:
        by_confidence[p["confidence"]] = by_confidence.get(p["confidence"], 0) + 1
    print(f"kept {len(kept)} pairs by confidence: {by_confidence}")

    with open(CORPUS_PATH, "w") as f:
        for number in sorted(corpus):
            f.write(json.dumps(corpus[number]) + "\n")
    print(f"Saved {len(corpus)} issues to {CORPUS_PATH}")

    with open(PAIRS_PATH, "w") as f:
        json.dump(kept, f, indent=2)
    print(f"Saved {len(kept)} duplicate pairs to {PAIRS_PATH}")


if __name__ == "__main__":
    main()