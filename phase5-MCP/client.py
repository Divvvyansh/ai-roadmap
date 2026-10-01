"""Week 1, Step 4 — CLI chat: MCP session + a hand-written Claude tool loop.

Run:  .venv/bin/python client.py
"""

import asyncio
import os
import sys
import json

from anthropic import Anthropic
from dotenv import load_dotenv
from mcp import Client, StdioServerParameters

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
            messages.append({"role": "user", "content": user_input})
            await run_turn(anthropic, client, messages, tools)


if __name__ == "__main__":
    asyncio.run(main())
