# Calendar Agent

A natural-language Google Calendar assistant built on a hand-rolled Claude tool-use loop — no LangChain, no agent framework. You type plain English; Claude decides which calendar tool to call, when to ask a clarifying question, and when to pause for confirmation before anything destructive happens.

This is Phase 2 of a self-directed AI engineering roadmap focused on learning agent patterns from first principles before adopting frameworks that hide them.

## What it does

- **Reads and writes your Google Calendar** in plain English — "what's on my plate tomorrow afternoon?", "book a 30-min call with Sam Thursday morning", "move my 2pm to 4pm instead"
- **Checks for conflicts before booking** — always calls `get_events` before scheduling
- **Asks before acting** — creating, updating, or cancelling an event requires an explicit "yes" from you first; nothing destructive happens silently
- **Resolves ambiguity by asking**, not guessing — "next Tuesday morning" without a time gets a clarifying question, not a made-up 9am
- **Morning briefing** (`briefing.py`) — weather + today's events + a suggested lunch slot + remaining free afternoon slots, formatted for the terminal or cron
- **Telegram frontend** (`telegram_bot.py`) — the same agent loop, reachable from a phone via a Telegram bot

## Architecture

```
┌─────────────┐     ┌──────────────┐     ┌───────────────────┐
│  agent.py   │────▶│  Claude API  │────▶│  tool_use blocks   │
│ (tool loop) │◀────│ (Sonnet 4.5) │◀────│  tool_result blocks│
└──────┬──────┘     └──────────────┘     └───────────────────┘
       │
       ▼
┌─────────────────┐      ┌────────────────────┐
│ tool_schemas.py  │      │ calendar_tools.py   │
│ (JSON schemas    │      │ (thin wrappers over │
│  sent to Claude) │      │  Google Calendar API │
└──────────────────┘      │  + Open-Meteo)       │
                           └────────────────────┘
```

The tool loop (`agent.py`) is the core pattern: send the conversation + tool definitions to Claude, and if `stop_reason == "tool_use"`, run the requested tool locally, append its result, and loop again. This repeats until Claude returns `end_turn`. Tool functions never raise — they return `{"error": "..."}` so Claude can read the failure and explain it to the user in natural language instead of the process crashing.

| File | Responsibility |
|---|---|
| `calendar_tools.py` | Google Calendar + weather API wrappers. No Claude code here — testable in isolation. |
| `tool_schemas.py` | JSON Schema definitions of each tool, passed to the Anthropic API's `tools` parameter. |
| `agent.py` | The tool loop — ties Claude and the tools together. CLI entry point. |
| `briefing.py` | Standalone script: weather + today's events + lunch suggestion, run manually or via cron. |
| `telegram_bot.py` | Telegram frontend around the same agent loop, with per-chat conversation history. |

## The tools

| Tool | Purpose |
|---|---|
| `get_events(start_date, end_date)` | Fetch events between two dates |
| `find_free_slots(date, duration_minutes)` | Find open windows on a given day (08:00–20:00) |
| `create_event(title, start, end, ...)` | Create a new event — requires user confirmation |
| `update_event(event_id, changes)` | Move or edit an existing event — requires user confirmation |
| `cancel_event(event_id)` | Delete an event — requires user confirmation |
| `add_invitee(event_id, email)` | Add an attendee to an existing event — requires user confirmation |
| `get_weather(date)` | Forecast via Open-Meteo (no API key needed) |

## Example session

```
Calendar Agent
Talk to your Google Calendar in plain English.
Type quit or exit to stop.

You: what have I got tomorrow afternoon?
  → calling get_events with {"start_date": "2026-06-06T12:00:00", "end_date": "2026-06-06T20:00:00"}
  ← result: [{"id": "abc123", "title": "1:1 with Sam", "start": "2026-06-06T14:00:00+02:00", ...}]

Agent:
Tomorrow afternoon you've got one thing: a 1:1 with Sam at 14:00–14:30. Otherwise open.

You: book a 45 min call with the design team at 4pm
  → calling get_events with {"start_date": "2026-06-06T16:00:00", "end_date": "2026-06-06T16:45:00"}
  ← result: []

Agent:
That slot's free. I'll create "Call with design team", 16:00–16:45 tomorrow. Shall I go ahead?

You: yes
  → calling create_event with {"title": "Call with design team", "start": "2026-06-06T16:00:00+02:00", "end": "2026-06-06T16:45:00+02:00"}
  ← result: {"id": "xyz789", "title": "Call with design team", ...}

Agent:
Done — booked for 16:00–16:45 tomorrow.
```

## Setup

Requires Python 3.10+ (uses `zoneinfo` and PEP 604 syntax) and a Google Cloud project with the Calendar API enabled.

```bash
pip install -r requirements.txt
```

1. **Google Calendar OAuth**: create a Google Cloud project, enable the Calendar API, create an OAuth 2.0 Desktop client, and download it as `credentials.json` into this directory. The first run opens a browser to authorize; a `token.json` is written afterward and reused (both are gitignored — never commit them).
2. **Anthropic API key**: copy `.env.example` to `.env` and set `ANTHROPIC_API_KEY`.
3. **(Optional) Telegram bot**: create a bot via [@BotFather](https://t.me/BotFather), add `TELEGRAM_BOT_TOKEN` to `.env`.

Run it:

```bash
python agent.py              # interactive CLI
python briefing.py           # one-off morning briefing
python telegram_bot.py       # Telegram frontend
```

## Testing

```bash
pytest
```

All 44 tests mock the Google API and HTTP calls — no credentials or network access required to run the suite.

## Design notes

- **Timezone-aware throughout**: the system prompt injects the current date/time in `Europe/Paris` on every turn so Claude resolves "tomorrow" and "next Monday" correctly without a separate parsing step.
- **History trimming avoids mid-tool-exchange cuts**: naive slicing of the message history could leave a dangling `tool_result` with no matching `tool_use`, which the API rejects with a 400. `trim_history` walks backward to a safe cut point — a plain-text user turn — instead.
- **Confirmation is enforced in two places**: both the system prompt and each mutating tool's schema description tell Claude to confirm before calling `create_event` / `update_event` / `cancel_event` / `add_invitee`. Belt-and-suspenders, since a system prompt alone is a soft constraint.