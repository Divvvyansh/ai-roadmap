"""
RAG agent: Claude + a search_docs tool backed by retriever.retrieve().
"""
import sys
import os
import json
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "RAG"))

import anthropic
from dotenv import load_dotenv
from tool_schemas import SEARCH_DOCS_TOOL

from retriever import retrieve, Chunk

load_dotenv()

MODEL = "claude-sonnet-4-5"
client = anthropic.Anthropic()

SYSTEM_PROMPT = "You are a helpful assistant that answers user's queries about fastapi and how to use it. " \
"Always break down the user's question into a concise query that can be run through a retrieval tool to search " \
"the fastapi documentation. " \
"RULES: " \
"- Always run the SEARCH_DOCS_TOOL before answering the user's query." \
"- If no results are found from the tool call, reply with what is returned from the tool." 

def run_tool(tool_name: str, tool_input: dict) -> tuple[str, list[Chunk]]:
    """Dispatch a tool_use block to the actual Python function and return a string result."""
    if tool_name == "search_docs":
        chunks = retrieve(tool_input["query"])
        if not chunks:
            return "No results found in the documentation." , []
        else:
            resp = ""
            blocks = []
            for c in chunks:
                block = f" [{c.doc_id} : {c.text}]"
                blocks.append(block)
            response = resp.join(blocks)
            return response, chunks
    raise ValueError(f"Unknown tool: {tool_name}")


def top_doc_ids(chunks_used: list[list[Chunk]], n: int = 2) -> list[str]:
    """Rank doc_ids by number of distinct chunks contributed, return top n."""
    seen_chunks = {}  

    for call_chunks in chunks_used:
        for chunk in call_chunks:
            if chunk.id not in seen_chunks:
                seen_chunks[chunk.id] = chunk
            pass

    doc_counts = Counter()  # TODO: doc_id -> count of distinct chunks
    for chunk in seen_chunks.values():
        if chunk.doc_id:
            doc_counts[chunk.doc_id] += 1
        pass

    return [doc_id for doc_id, count in doc_counts.most_common(n)]


def ask(question: str) -> dict:
    """
    Run the full tool-use loop for one question.
    Returns {"answer": str, "chunks_used": list[str]}.
    """
    messages = [{"role": "user", "content": question}]
    chunks_used = []
    first_turn = True

    while True:
        extra = {}
        if first_turn:
            extra["tool_choice"] = {"type": "tool", "name": "search_docs"}
        response = client.messages.create(
            model=MODEL,
            system=SYSTEM_PROMPT,
            tools=[SEARCH_DOCS_TOOL],
            **extra,
            messages=messages,
            max_tokens=1024,
        )

        first_turn = False
            

        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            text = " ".join(
                block.text for block in response.content if hasattr(block, "text")
            )
            docs = top_doc_ids(chunks_used)
            return {"answer": text, "docs_used": docs, "chunks_used": chunks_used}
        
        if response.stop_reason == "tool_use":
            tool_result = []
            turn_chunks = []
            for block in response.content:
                if block.type != "tool_use":
                    continue

                retreived, chunks = run_tool(block.name, block.input)

                tool_result.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": retreived,
                    }
                )
                chunks_used.append(chunks)
                turn_chunks.append(chunks)

            if all(c == [] for c in turn_chunks):
                return {"answer": "No results found in the documentation.", "docs_used": [], "chunks_used": chunks_used}

            messages.append({"role": "user", "content": tool_result})
            continue

        return {"answer": "", "docs_used": [], "chunks_used": chunks_used}


def main():
    test_questions = [
        "How do I add a background task to a path operation?",
        "What's the capital of France?",
    ]
    for q in test_questions:
        print(f"\nQ: {q}")
        result = ask(q)
        print(f"A: {result['answer']}")
        print(f"docs_used: {result['docs_used']}")


if __name__ == "__main__":
    main()