"""
JSON Schema definitions for the 4 calendar tools.
These are passed directly to the Anthropic API's `tools` parameter.
Keep this file in sync with the function signatures in calendar_tools.py.
"""

TOOLS = [
    {
        "name": "get_events",
        "description": (
            "Fetch all calendar events between two dates. "
            "Always call this before scheduling anything — check for conflicts first. "
            "Dates must be ISO 8601 (e.g. 2026-06-06 or 2026-06-06T09:00:00)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "start_date": {
                    "type": "string",
                    "description": "Start of the range, ISO 8601 date or datetime.",
                },
                "end_date": {
                    "type": "string",
                    "description": "End of the range, ISO 8601 date or datetime.",
                },
            },
            "required": ["start_date", "end_date"],
        },
        "input_examples": {
            "Get all events for June 6, 2026": {
                "start_date": "2026-06-06",
                "end_date": "2026-06-07",
            },
            "Get events from June 6, 9am to June 6, 5pm": {
                "start_date": "2026-06-06T09:00:00",
                "end_date": "2026-06-06T17:00:00",
            },
        },
    },
    {
        "name": "find_free_slots",
        "description": (
            "Find free time windows on a specific day that fit a given duration. "
            "Only looks within 08:00–20:00 IST. "
            "Use this when the user asks for 'a free slot', 'when am I available', or similar. "
            "date must be an ISO 8601 date (2026-06-06)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "description": "The day to search, ISO 8601 date (YYYY-MM-DD).",
                },
                "duration_minutes": {
                    "type": "integer",
                    "description": "Required meeting length in minutes.",
                },
            },
            "required": ["date", "duration_minutes"],
        },
        "input_examples": {
            "Find a 60-minute slot on June 6, 2026": {
                "date": "2026-06-06",
                "duration_minutes": 60,
            },
        },
    },
    {
        "name": "create_event",
        "description": (
            "Create a new calendar event. "
            "ALWAYS get user confirmation before calling this tool. "
            "Show the user the title, start, and end, then ask 'Shall I go ahead?' "
            "start and end must be full ISO 8601 datetimes with timezone offset "
            "(e.g. 2026-06-06T14:00:00+05:30)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Event title / summary.",
                },
                "start": {
                    "type": "string",
                    "description": "Start datetime, ISO 8601 with timezone (e.g. 2026-06-06T14:00:00+05:30).",
                },
                "end": {
                    "type": "string",
                    "description": "End datetime, ISO 8601 with timezone.",
                },
                "attendees": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of attendee email addresses.",
                },
                "description": {
                    "type": "string",
                    "description": "Optional event description or notes.",
                },
            },
            "required": ["title", "start", "end"],
        },
        "input_examples": {
            "Create a meeting with John and Jane": {
                "title": "Team Meeting",
                "start": "2026-06-06T14:00:00+05:30",
                "end": "2026-06-06T15:00:00+05:30",
                "attendees": ["john@example.com", "jane@example.com"],
                "description": "Discuss project updates.",
            },
            "Block 30 minutes on my calendar on June 6, 2026 to meditate": {
                "title": "30-minute meditation",
                "start": "2026-06-06T16:00:00+05:30",
                "end": "2026-06-06T16:30:00+05:30",
                "description": "Discuss project updates.",   ## Attendees are optional
            },
        },
    },
    {
        "name": "update_event",
        "description": (
            "Update an existing calendar event — move it, rename it, or edit its description. "
            "ALWAYS get user confirmation before calling this tool. "
            "Show the user what will change, then ask 'Shall I go ahead?' "
            "Requires the event_id from a prior get_events call."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "event_id": {
                    "type": "string",
                    "description": "The Google Calendar event ID from a prior get_events result.",
                },
                "changes": {
                    "type": "object",
                    "description": (
                        "Fields to update. Include only what's changing. "
                        "Allowed keys: title (string), start (ISO 8601 datetime), "
                        "end (ISO 8601 datetime), description (string)."
                    ),
                    "properties": {
                        "title": {"type": "string"},
                        "start": {"type": "string"},
                        "end": {"type": "string"},
                        "description": {"type": "string"},
                    },
                },
            },
            "required": ["event_id", "changes"],
        },
        "input_examples": {
            "Move an event to 3pm": {
                "event_id": "abc123",
                "changes": {
                    "start": "2026-06-06T15:00:00+05:30",
                    "end": "2026-06-06T16:00:00+05:30",
                },
            },
            "Rename an event to 'Project Sync'": {
                "event_id": "abc123",
                "changes": {
                    "title": "Project Sync",
                },
            },
            "Add a description to an event": {
                "event_id": "abc123",
                "changes": {
                    "description": "Discuss project updates and next steps.",
                },
            },
        },
    },
]
