SEARCH_ISSUES_TOOL = {
    "name": "search_issues",
    "description": (
        "Semantic search over closed issues in the pydantic/pydantic repository. "
        "Returns up to 5 candidates as [number : title : similarity : html_url].\n\n"
        "The similarity score orders the candidate list. It does NOT measure whether "
        "a candidate is a duplicate. Measured against known duplicate pairs, true "
        "duplicates score a median of 0.884 and unrelated issues a median of 0.864 — "
        "the two ranges overlap almost completely, because pydantic issues share heavy "
        "template boilerplate. Treat a high score as a reason to read an issue, never "
        "as a verdict. Use get_issue to read candidate bodies before deciding."),
    "input_schema": {
        "type": "object",
        "properties": {"query": {
            "type": "string",
            "description": (
                "A natural-language description of the problem, in the shape an issue "
                "report would be written. This is embedded and compared against the text "
                "of past issues, so a full sentence retrieves better than bare keywords."
            ),
        }},
        "required": ["query"],
    },
}

GET_ISSUE_TOOL = {
    "name": "get_issue",
    "description": (
        "Given an issue number, this tool retrieves the following fields about the issue as a dictionary:"
        "number (issue number), title (title of the issue), body (The content body of this issue), labels(added to the issue), state_reason (developer's reason for closing the issue), closed_at (date and time the issue was closed)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {"number": {
            "type": "integer",
            "description": (
                "The issue number, as returned by search_issues. Numbers not present "
                "in the corpus return a not-found message rather than an error."
            ),
        }},
        "required": ["number"],
    },
}

SEARCH_DOCS_TOOL = {
    "name": "search_docs",
    "description": (
        "Semantic search over the pydantic library documentation. Returns up to 8 "
        "chunks as [doc_id : text].\n\n"
        "Chunks come back for almost any input, including questions the documentation "
        "does not cover — a non-empty result is not evidence that the question is "
        "answerable. Assert only what the returned chunks support, and say so plainly "
        "when they do not support an answer."
            ),
    "input_schema": {
        "type": "object",
        "properties": {"query": {
            "type": "string",
            "description": (
                "A natural-language question about pydantic's behaviour or usage. "
                "This is embedded and matched against documentation passages."
            ),
        }},
        "required": ["query"],
    },
}
