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

## orchestration sub-agents

DELEGATE_TO_TRIAGE = {
    "name": "delegate_to_triage_agent",
    "description": (
        "Invokes a triage agent that has access to a corpus of all closed issues in the pydantic repository. "
        "Its task is to determine if the issue described in the input task string describes a duplicate of an existing issue in the corpus. "
        "The agent is blind to any information about the pydantic documentation and will only search in its issues corpus anytime it is used. "
        "The agent always starts from a fresh message list and has no knowledge of the context of anything not sent to it explicitly. "
        "A good task string should be an issue report or a question about the repository. "
        "A good task string must include title, description of the problem, and the example code or traceback — copied verbatim from the issue, not summarized. "
        "The agent will return a prose string that includes the result of the search, including 'no duplicate found' if no duplicates are found. This is a successful result, not a failure. "
        "If a duplicate is found, the agent response string will consist of 'Duplicate found' followed by information about the issue that the question duplicates. "
        "If no duplicate is found, the agent response string will consist of 'No duplicate found' followed by a list of the most similar issues the agent found and then rejected as not duplicates and their similarity scores. "
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "task": {
                "type": "string",
                "description": (
                    "A bug report or a question about the pydantic repository in the way an issue report would be written. "
                    "Do not add questions in the beginning or end like 'is this a duplicate?' "
                ),
            }
        },
        "required": ["task"],
    },
}

DELEGATE_TO_DOCS = {
    "name": "delegate_to_docs_agent",
    "description": (
        "Invokes a docs agent that has access to a corpus of the documentation of the pydantic repository. "
        "Its task is to answer a query about the pydantic repository by looking up information from the documentation. "
        "The agent is blind to any information about the pydantic issues list and will only search in its documentation corpus anytime it is used. "
        "The agent always starts from a fresh message list and has no knowledge of the context of anything not sent to it explicitly. "
        "A good task string should be a query about pydantic, its behaviour, usage or use case along with the specific setting/type/nesting the issue involves, not just the general topic. "
        "The agent will return a prose string containing either the answer to the query or 'the documentation does not cover this.' "
        "If the agent does not find the answer to the question in the documentation, it will clearly state so and provide some doc_ids that it retrieved and rejected as irrelevant. This is an acceptable response and a successful result. "
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "task": {
                "type": "string",
                "description": (
                    "A query about pydantic's behaviour or usage. "
                ),
            }
        },
        "required": ["task"],
    },
}
