

import json
import os
import sys
import anthropic
from dotenv import load_dotenv
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from calendar_tools import create_event, find_free_slots, get_events, update_event
from tool_schemas import TOOLS

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))

console = Console()

MODEL = "claude-sonnet-4-5"
MAX_HISTORY = 10  

SYSTEM_PROMPT = """You are a helpful calendar and event management assistant with access to the user's Google Calendar.

RULES:
- Always call get_events before scheduling anything — check for conflicts first.
- If the user's request is ambiguous (e.g. "next Tuesday" without a year, "morning" without a time),
  ask one clarifying question before calling any tool.
- For destructive actions (create_event, update_event), show what you're about to do and ask
  "Shall I go ahead?" BEFORE calling the tool. Do not call these tools without explicit user approval.
- Dates and times are always in Asia/Kolkata timezone (IST, UTC+5:30).
- Use ISO 8601 format for all datetimes passed to tools: 2026-06-06T14:00:00+05:30.
- If a tool returns {"error": "..."}, tell the user clearly what went wrong.
- Keep responses concise. Use bullet points for event lists.
"""


TOOL_MAP = {
    "get_events": get_events,
    "find_free_slots": find_free_slots,
    "create_event": create_event,
    "update_event": update_event,
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
            system=SYSTEM_PROMPT,
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
    """Keep the last MAX_HISTORY user+assistant pairs to avoid token bloat."""
    if len(history) > MAX_HISTORY * 2:
        return history[-(MAX_HISTORY * 2):]
    return history


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
