

SEARCH_DOCS_TOOL =   {
        "name": "search_docs",
        "description": (
            "Use this tool to retrieve chunks of information from the fastAPI documentation. "
            "Run this tool when the user asks anything related to fastapi and how to use it. "
            "only assert facts present in the retrieved chunks; if none support the answer, say so. "
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The stripped down query/question describing the information required from the documnentation.",
                }
            },
            "required": ["query"],
        },
    }
