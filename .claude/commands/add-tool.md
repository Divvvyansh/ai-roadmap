You are adding a new tool to the calendar agent located at `calendar_agent/`.

The user has described the tool they want: $ARGUMENTS

## Phase 1 — Plan (output to user BEFORE making any changes)

Read the following files to understand the current codebase:
- `calendar_agent/calendar_tools.py`
- `calendar_agent/tool_schemas.py`
- `calendar_agent/agent.py`

Then output a clear summary to the user that includes:

- **Tool name** you will use (snake_case)
- **Parameters** — name, type, whether required or optional, and what each does
- **Return shape** — what the dict/list will look like on success and on error
- **Function body summary** — which API or service it calls and how
- **Schema** — the full `input_schema` dict you will add to tool_schemas.py
- **Files to be changed** — list each file and the exact change (append function / append to TOOLS list / update import line + TOOL_MAP)

End this section with the line:
> "Waiting for your go-ahead. Reply 'yes' or 'go' to apply these changes."

Wait for the user to confirm before proceeding to Phase 2.

## Phase 2 — Implement (only after user confirms)

### 2a. Implement the tool in `calendar_agent/calendar_tools.py`
- Append the new function at the end of the file
- Function name in snake_case matching what you described in Phase 1
- Parameters typed with Python type hints
- Returns a plain `dict` or `list[dict]` — never raise exceptions
- Return errors as `{"error": "..."}` so Claude can read them
- Use the existing `_get_service()` helper for any Google Calendar API calls
- Use `_to_rfc3339()` for date conversion where applicable
- Respect the timezone (Europe/Paris, ISO 8601 strings)

### 2b. Add the schema to `calendar_agent/tool_schemas.py`
- Append a new dict to the `TOOLS` list
- Format:
  ```python
  {
      "name": "...",
      "description": "...",
      "input_schema": {
          "type": "object",
          "properties": { ... },
          "required": [ ... ]
      }
  }
  ```
- Description must include: what the tool does, when to use it, what it returns

### 2c. Wire it into `calendar_agent/agent.py`
- Add the function name to the existing `from calendar_tools import ...` line at the top
- Add an entry to `TOOL_MAP`: `"tool_name": tool_function`

### 2d. Run the smoke test
```
cd calendar_agent && python test_tool_wiring.py <tool_name>
```
Replace `<tool_name>` with the actual tool name from Phase 1.
If it fails, diagnose the error, fix it, and re-run before reporting done.

## Conventions (do not deviate)
- Do NOT modify agent.py's system prompt, briefing.py, or CLAUDE.md
- Do NOT add features beyond what the user described
- Do NOT add docstrings or inline comments unless the logic is genuinely non-obvious
- All datetime strings must be ISO 8601 in Europe/Paris timezone