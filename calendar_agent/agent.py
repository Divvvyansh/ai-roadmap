

import json
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo
import anthropic
from dotenv import load_dotenv
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from calendar_tools import create_event, find_free_slots, get_events, update_event, cancel_event, get_weather, add_invitee
from tool_schemas import TOOLS

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))

console = Console()

MODEL = "claude-sonnet-4-5"
MAX_HISTORY = 10

TIMEZONE = "Europe/Paris"


def build_system_prompt() -> str:
    now = datetime.now(ZoneInfo(TIMEZONE))
    return f"""You are a helpful calendar and event management assistant with access to the user's Google Calendar.

Today is {now.strftime("%A, %d %B %Y")} and the current time is {now.strftime("%H:%M")} ({TIMEZONE}).
Use this to resolve relative references like "tomorrow", "next Monday", or "this afternoon" without asking.

RULES:
- Always call get_events before scheduling anything — check for conflicts first.
- If the user's request is ambiguous (e.g. "morning" without a specific time), ask one clarifying question before calling any tool.
- For destructive actions (create_event, update_event, cancel_event), show what you're about to do and ask
  "Shall I go ahead?" BEFORE calling the tool. Do not call these tools without explicit user approval.
- Dates and times are always in Paris timezone (CEST or CET depending on the time of year).
- Use ISO 8601 format for all datetimes passed to tools: 2026-06-06T14:00:00+02:00.
- If a tool returns {{"error": "..."}}, tell the user clearly what went wrong.
- Keep responses concise. Use bullet points for event lists.
"""


TOOL_MAP = {
    "get_events": get_events,
    "find_free_slots": find_free_slots,
    "create_event": create_event,
    "update_event": update_event,
    "cancel_event": cancel_event,
    "get_weather": get_weather,
    "add_invitee": add_invitee,
}


def run_tool(name: str, inputs: dict):
    fn = TOOL_MAP.get(name)
    if fn is None:
        return {"error": f"Unknown tool: {name}"}
    return fn(**inputs)



def chat(client: anthropic.Anthropic, history: list[dict], user_input: str) -> str:
    """
    Send one user turn through the full tool loop.
    Mutates history in place. Returns Claude's final text response.
    """
    history.append({"role": "user", "content": user_input})

    while True:
        response = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            system=build_system_prompt(),
            tools=TOOLS,
            messages=history,
        )

        history.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            text = " ".join(
                block.text for block in response.content if hasattr(block, "text")
            )
            return text

        if response.stop_reason == "tool_use":
            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue

                console.print(
                    f"  [dim]→ calling [bold]{block.name}[/bold] "
                    f"with {json.dumps(block.input, ensure_ascii=False)}[/dim]"
                )

                result = run_tool(block.name, block.input)

                console.print(f"  [dim]← result: {json.dumps(result, ensure_ascii=False)[:200]}[/dim]")

                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )

            history.append({"role": "user", "content": tool_results})
            continue

        return f"[Unexpected stop_reason: {response.stop_reason}]"


def trim_history(history: list[dict]) -> list[dict]:
    """
    Keep the last MAX_HISTORY user-initiated turns to avoid token bloat.

    Naive index slicing can cut mid-tool-exchange, leaving a tool_result message
    at position 0 with no matching tool_use — the API rejects that with a 400.
    Instead, scan backward to find a safe cut point: a user message whose content
    is a plain string (not a list of tool_results).
    """
    if len(history) <= MAX_HISTORY * 2:
        return history

    # Walk backward counting plain user turns (text messages, not tool_results)
    turns = 0
    cut = len(history)
    for i in range(len(history) - 1, -1, -1):
        msg = history[i]
        if msg["role"] == "user" and isinstance(msg["content"], str):
            turns += 1
            if turns == MAX_HISTORY:
                cut = i
                break

    return history[cut:]


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        console.print("[red]ANTHROPIC_API_KEY not set. Add it to .env[/red]")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)
    history: list[dict] = []

    console.print(
        Panel(
            "[bold green]Calendar Agent[/bold green]\n"
            "Talk to your Google Calendar in plain English.\n"
            "Type [bold]quit[/bold] or [bold]exit[/bold] to stop.",
            expand=False,
        )
    )

    while True:
        try:
            user_input = console.input("\n[bold cyan]You:[/bold cyan] ").strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Bye.[/dim]")
            break

        if not user_input:
            continue
        if user_input.lower() in ("quit", "exit"):
            console.print("[dim]Bye.[/dim]")
            break

        with console.status("[dim]Thinking...[/dim]", spinner="dots"):
            reply = chat(client, history, user_input)

        console.print("\n[bold magenta]Agent:[/bold magenta]")
        console.print(Markdown(reply))

        history = trim_history(history)


if __name__ == "__main__":
    main()
