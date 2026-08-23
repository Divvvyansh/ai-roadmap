"""
Live GitHub reads for the triage sub-agent.
"""
from __future__ import annotations

import os
import time

import requests
from dotenv import load_dotenv

from retriever import RetryableToolError

load_dotenv()

REPO = "pydantic/pydantic"
API = "https://api.github.com"

TOKEN = os.environ.get("GITHUB_TOKEN")


def _headers() -> dict:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    return headers


def gh_get(path: str, params: dict | None = None) -> dict | None:
    """One GET against the GitHub API.
    """
    response = requests.get(
        f"{API}{path}", headers=_headers(), params=params, timeout=15
    )
    if response.status_code == 403 :
        if response.headers.get("x-ratelimit-remaining") == "0":
            reset_time = int(response.headers.get("x-ratelimit-reset", time.time() + 60))
            wait_time = max(reset_time - time.time(), 0)
            raise RetryableToolError(f"GitHub rate limit hit. Try after: {wait_time:.2f} seconds")
        else:
            retry_after = int(response.headers.get("retry-after", 60))
            raise RetryableToolError(f"Rate limit hit. Try after {retry_after} seconds.")
    elif response.status_code == 429:
        retry_after = int(response.headers.get("retry-after", 60))
        raise RetryableToolError(f"Rate limit hit. Try after {retry_after} seconds.")  
    elif response.status_code == 404:
        return None
    elif response.status_code == 200:
        issue = response.json()
        return issue
    elif response.status_code >= 500:
        raise RetryableToolError(f"Exception encountered: {response.content}")
    else:
        error_code = response.status_code
        raise Exception(f"Exception with error code: {error_code} : {response.content}")


def fetch_issue(number: int) -> dict | None:
    """Live read of one issue.
    """
    # Voyage and GitHub both raise RetryableToolError, so without a marker the
    # two rate limiters are indistinguishable in a run log.
    issue = gh_get(f"/repos/{REPO}/issues/{number}")
    if issue is not None:
        output_issue = {
            "number": issue["number"],
            "title": issue["title"],
            "body": issue["body"],
            "labels": [label["name"] for label in issue.get("labels", [])],
            "state_reason": issue["state_reason"],
            "closed_at": issue["closed_at"],
        }
        return None if "pull_request" in issue else output_issue
    return None
