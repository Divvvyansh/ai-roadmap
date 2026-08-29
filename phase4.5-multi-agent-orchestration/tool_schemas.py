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


DELEGATE_TO_CHECKER = {
    "name": "delegate_to_checker_agent",
    "description": (
        "Invokes a checker agent that independently verifies whether one specific cited issue actually supports a duplicate claim made about it. "
        "It is handed a single issue number and no alternatives, so 'this is not a duplicate' is a normal and expected answer — unlike the triage agent, which picks a best match out of five candidates and therefore always has a winner. "

        "Call this whenever the triage agent cites an issue number that you are considering acting on. "
        "The retrieval underneath the triage agent cannot separate duplicates from unrelated issues on its own: true duplicates score a median of 0.884 and unrelated issues 0.864, and an unrelated issue outranks the true duplicate in roughly half of all cases. "
        "A triage citation is a candidate for closure, never a basis for one. Acting on an unchecked citation risks closing a live bug against an issue that has nothing to do with it. "

        "The agent returns a first line reading exactly 'VERDICT: X', followed by its reasoning, and for a confirmed duplicate, quoted text from the cited issue. "
        "DUPLICATE means the cited issue has the same trigger and the same behaviour, and the change that resolved it would resolve this report. "
        "RELATED means the cited issue is genuinely about the same area but differs in trigger, configuration, or scope — not grounds for closing. "
        "REGRESSION means the cited issue was closed as completed and this report describes that behaviour happening again — not a duplicate, a defect that came back. "
        "UNRELATED means the cited issue does not bear on this report at all. All four are successful results, not failures. "

        "The agent starts from a fresh message list and sees nothing that is not copied into the task string. It re-reads the cited issue itself rather than trusting any description of it. "
        "Do not tell it what the triage agent concluded, how confident triage was, or what similarity score the candidate scored. A judge shown the argument grades the argument instead of the evidence, and its verdict then stops being an independent signal you can weigh against triage's — you get two signals that agree because one copied the other. "
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "task": {
                "type": "string",
                "description": (
                    "Exactly two things, in this shape:\n"
                    "CLAIM: the report below duplicates issue #N.\n"
                    "ORIGINAL REPORT:\n"
                    "<the incoming issue's title and body, copied verbatim>\n\n"
                    "The report must be the reporter's own words, not a summary of them. "
                    "The checker decides by comparing specifics — the exact configuration, the exact error, the code that triggers it — and a summary is precisely where those specifics are lost. "
                    "Summarising also makes every issue read more like every other issue, which biases the checker toward confirming. "
                    "Include no verdict, no similarity score, and no reasoning from the triage agent."
                ),
            }
        },
        "required": ["task"],
    },
}
