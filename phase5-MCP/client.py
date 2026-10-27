"""Week 1, Step 4 — CLI chat: MCP session + a hand-written Claude tool loop.

Run:  .venv/bin/python client.py
"""

import asyncio
import os
import sys
import json
import re

from anthropic import Anthropic
from dotenv import load_dotenv
from mcp import Client, StdioServerParameters
from mcp.shared.exceptions import MCPError

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

MODEL = "claude-sonnet-5"
MAX_TOKENS = 2048

SYSTEM_PROMPT = (
    "You are a data analyst with read-only access to a SQLite database. "
    "Explore the schema before writing queries. Never state a figure you "
    "have not computed with a query."
)

SERVER = StdioServerParameters(command=sys.executable, args=["server.py"])


def to_anthropic_tools(mcp_tools) -> list[dict]:
    """Convert MCP Tool objects into Anthropic tool definitions.
    """
    return [
        {
            "name": tool.name,
            "description": tool.description or tool.title or tool.name,
            "input_schema": tool.input_schema,
        }
        for tool in mcp_tools
    ]


async def expand_mentions(client: Client, user_input: str) -> str | list[dict]:
    """Turn "what is in @albums?" into a user message with schema://albums attached.
    """
    mentioned_words = list(dict.fromkeys(re.findall(r"@(\w+)", user_input)))
    if not mentioned_words:
        return user_input  
    content_blocks = []
    for word in mentioned_words:
        block = {"type": "text"}
        try:
            result = await client.read_resource(f"schema://{word}")
            block["text"] = f"Schema for {word}:\n{result.contents[0].text}"
            content_blocks.append(block)
        except MCPError:
            block["text"] = f"Tried reading schema for table named: {word} but returned no results."
            content_blocks.append(block)
    content_blocks.append({"type": "text", "text": user_input})
    return content_blocks


async def run_turn(anthropic: Anthropic, client: Client, messages: list[dict], tools: list[dict]) -> None:
    """One user turn: call the model, run any tools it asks for, repeat until it stops.

    Appends everything it produces onto `messages` so the next turn has the history.
    """
    while True:
        response = anthropic.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            tools=tools,
            messages=messages,
        )

        messages.append({"role": "assistant", "content": response.content})

        for block in response.content:
            if block.type == "text":
                print(f"\nclaude> {block.text}")

        if response.stop_reason == "tool_use":
            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                print(f"[tool call: {block.name}({block.input})]")
                result = await client.call_tool(block.name, block.input)
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": "\n".join(
                            b.text for b in result.content if b.type == "text"
                        ),
                        "is_error": result.is_error,
                    }
                )
            messages.append({"role": "user", "content": tool_results})
            continue

        if response.stop_reason != "end_turn":
            print(f"\n[stopped: {response.stop_reason}]")
        return


async def main() -> None:
    anthropic = Anthropic()
    
    async with Client(SERVER) as client:
        tools = to_anthropic_tools((await client.list_tools()).tools)

        messages: list[dict] = []
        while True:
            try:
                user_input = input("\nyou> ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not user_input or user_input in {"quit", "exit"}:
                break
            content = await expand_mentions(client, user_input)
            messages.append({"role": "user", "content": content})
            await run_turn(anthropic, client, messages, tools)


if __name__ == "__main__":
    asyncio.run(main())
