# ph2-calendar-agent

Natural Language Calendar Agent — Phase 2 of the AI Engineering Roadmap.
Allows users to talk to Google Calendar in plain English via a Claude-powered
tool loop. The propject is part of a learning ropadmap and is the phase 2 of this roadmap to help me to learn to use AI tools. The full roadmap can be found in ai-roadmap-updated.pdf. Your job is to help me but also make sure I understand concepts and learn to use tools that make me proficient in usign AI tools and agents.

## Project Structure
calendar_agent/
├── calendar_tools.py     # 4 Google Calendar wrapper functions (no Claude here)
├── tool_schemas.py       # JSON Schema definitions of the 4 tools for the API
├── agent.py              # The main tool loop — ties Claude + tools together
├── credentials.json      # OAuth2 credentials (gitignored, never commit)
├── token.json            # Auto-generated after first auth run (gitignored)
├── .env                  # ANTHROPIC_API_KEY (gitignored, never commit)
└── CLAUDE.md             # This file

## Environment

- Python 3.12 via pyenv
- Dependencies managed with pip
- Load env vars via python-dotenv — never hardcode keys

## The 4 Calendar Tools

These are the only tools Claude can call. Each is a thin wrapper around the
Google Calendar API. Build and test them in isolation before connecting Claude.

| Tool | Purpose |
|------|---------|
| `get_events(start_date, end_date)` | Fetch events between two dates |
| `find_free_slots(date, duration_minutes)` | Find open windows on a given day |
| `create_event(title, start, end)` | Create a new calendar event |
| `update_event(event_id, changes)` | Move or edit an existing event |

## Tool Loop Pattern

The agent follows a strict loop:
1. Send user message + tools to Claude
2. If `stop_reason == "tool_use"` → execute the tool, append result, loop again
3. If `stop_reason == "end_turn"` → print response, get next user input
4. Never call `create_event` or `update_event` without first confirming with the user

## Agent Rules (applied in the system prompt)

- Always call `get_events` before scheduling anything — check for conflicts first
- Resolve ambiguous date/time inputs (e.g. "next Tuesday morning") by asking
  before acting, not after
- For destructive actions (move/delete), show what you're about to do and ask
  "Shall I go ahead?" before calling the tool
- Dates are always ISO 8601 format (2026-06-05T09:00:00)
- User timezone: Asia/Kolkata (IST, UTC+5:30)

## Coding Conventions

- Each tool function returns a dict or list — no exceptions, no raw API objects
- Tool functions live in `calendar_tools.py` only — agent.py imports them
- Tool schemas live in `tool_schemas.py` only — keeps agent.py clean
- Use `rich` for all terminal output (coloured, readable)
- Keep the message history array trimmed to the last 10 exchanges


## What NOT to Do

- Don't put tool schemas inside agent.py — they belong in tool_schemas.py
- Don't catch and silently swallow Google API errors — surface them to Claude
- Don't commit credentials.json or token.json — they are gitignored