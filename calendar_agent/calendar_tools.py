"""
Google Calendar API wrappers.
Each function is a thin wrapper — returns plain dicts/lists, never raises to the caller.
Errors are returned as {"error": "..."} so Claude can read them and respond naturally.
"""

import os
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

import urllib.request
import json as _json

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Open-Meteo location for Paris (no API key required)
_LATITUDE = 48.8566
_LONGITUDE = 2.3522

# WMO weather interpretation codes → human-readable description
_WMO_CODES = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Icy fog",
    51: "Light drizzle", 53: "Moderate drizzle", 55: "Heavy drizzle",
    61: "Light rain", 63: "Moderate rain", 65: "Heavy rain",
    71: "Light snow", 73: "Moderate snow", 75: "Heavy snow",
    80: "Light showers", 81: "Moderate showers", 82: "Heavy showers",
    95: "Thunderstorm", 96: "Thunderstorm with hail", 99: "Heavy thunderstorm with hail",
}

SCOPES = ["https://www.googleapis.com/auth/calendar"]
TIMEZONE = "Europe/Paris"
CREDENTIALS_FILE = os.path.join(os.path.dirname(__file__), "credentials.json")
TOKEN_FILE = os.path.join(os.path.dirname(__file__), "token.json")


def _get_service():
    """Authenticate and return a Google Calendar API service object."""
    creds = None

    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())

    return build("calendar", "v3", credentials=creds)


def get_events(start_date: str, end_date: str) -> list[dict]:
    """
    Fetch all calendar events between start_date and end_date (ISO 8601).
    Returns a list of event dicts with keys: id, title, start, end, description.
    Returns {"error": "..."} on failure.
    """
    try:
        service = _get_service()
        # Convert bare dates to datetime with timezone if needed
        start = _to_rfc3339(start_date, start_of_day=True)
        end = _to_rfc3339(end_date, start_of_day=False)

        result = (
            service.events()
            .list(
                calendarId="primary",
                timeMin=start,
                timeMax=end,
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )

        events = []
        for e in result.get("items", []):
            events.append(
                {
                    "id": e["id"],
                    "title": e.get("summary", "(No title)"),
                    "start": e["start"].get("dateTime", e["start"].get("date")),
                    "end": e["end"].get("dateTime", e["end"].get("date")),
                    "description": e.get("description", ""),
                }
            )
        return events

    except HttpError as e:
        return [{"error": f"Google API error: {e}"}]
    except Exception as e:
        return [{"error": str(e)}]


def find_free_slots(date: str, duration_minutes: int) -> list[dict]:
    """
    Find free time windows on a given date that fit duration_minutes.

    Looks only within working hours (08:00–20:00 IST).
    Returns a list of {"start": ..., "end": ...} dicts in ISO 8601.
    Returns {"error": "..."} on failure.
    """
    try:
        tz = ZoneInfo(TIMEZONE)
        day = datetime.fromisoformat(date).replace(tzinfo=tz)
        window_start = day.replace(hour=8, minute=0, second=0, microsecond=0)
        window_end = day.replace(hour=20, minute=0, second=0, microsecond=0)

        events = get_events(
            window_start.isoformat(),
            window_end.isoformat(),
        )

        if isinstance(events, dict) and "error" in events:
            return events

        # Build list of busy intervals
        busy = []
        for e in events:
            try:
                s = datetime.fromisoformat(e["start"]).astimezone(tz)
                en = datetime.fromisoformat(e["end"]).astimezone(tz)
                busy.append((s, en))
            except Exception:
                pass
        busy.sort(key=lambda x: x[0])

        # Walk the day and collect gaps long enough for duration_minutes
        free = []
        cursor = window_start
        for busy_start, busy_end in busy:
            if cursor < busy_start:
                gap = int((busy_start - cursor).total_seconds() / 60)
                if gap >= duration_minutes:
                    free.append(
                        {"start": cursor.isoformat(), "end": busy_start.isoformat()}
                    )
            cursor = max(cursor, busy_end)

        # Remaining time after last event
        if cursor < window_end:
            gap = int((window_end - cursor).total_seconds() / 60)
            if gap >= duration_minutes:
                free.append(
                    {"start": cursor.isoformat(), "end": window_end.isoformat()}
                )

        return free

    except Exception as e:
        return [{"error": str(e)}]


def create_event(title: str, start: str, end: str, description: str = "", attendees: Optional[list] = None) -> dict:
    """
    Create a new calendar event.

    start and end must be ISO 8601 datetimes (e.g. 2026-06-06T14:00:00+05:30).
    Returns the created event dict with keys: id, title, start, end, link.
    Returns {"error": "..."} on failure.
    """
    try:
        service = _get_service()
        body = {
            "summary": title,
            "description": description,
            "start": {"dateTime": start, "timeZone": TIMEZONE},
            "end": {"dateTime": end, "timeZone": TIMEZONE},
        }
        if attendees:
            body["attendees"] = [{"email": a} for a in attendees]
        event = service.events().insert(calendarId="primary", body=body).execute()
        return {
            "id": event["id"],
            "title": event.get("summary"),
            "start": event["start"].get("dateTime"),
            "end": event["end"].get("dateTime"),
            "link": event.get("htmlLink"),
        }

    except HttpError as e:
        return {"error": f"Google API error: {e}"}
    except Exception as e:
        return {"error": str(e)}


def update_event(event_id: str, changes: dict) -> dict:
    """
    Update an existing calendar event by event_id.

    changes is a dict with any subset of: title, start, end, description.
    Returns the updated event dict.
    Returns {"error": "..."} on failure.
    """
    try:
        service = _get_service()
        event = service.events().get(calendarId="primary", eventId=event_id).execute()

        if "title" in changes:
            event["summary"] = changes["title"]
        if "description" in changes:
            event["description"] = changes["description"]
        if "start" in changes:
            event["start"] = {"dateTime": changes["start"], "timeZone": TIMEZONE}
        if "end" in changes:
            event["end"] = {"dateTime": changes["end"], "timeZone": TIMEZONE}

        updated = (
            service.events()
            .update(calendarId="primary", eventId=event_id, body=event)
            .execute()
        )
        return {
            "id": updated["id"],
            "title": updated.get("summary"),
            "start": updated["start"].get("dateTime"),
            "end": updated["end"].get("dateTime"),
            "link": updated.get("htmlLink"),
        }

    except HttpError as e:
        return {"error": f"Google API error: {e}"}
    except Exception as e:
        return {"error": str(e)}


def cancel_event(event_id: str) -> dict:
    """
    Cancel an existing calendar event by event_id.

    Returns a success message or an error message.
    """
    try:
        service = _get_service()
        service.events().delete(calendarId="primary", eventId=event_id).execute()
        return {"message": "Event cancelled successfully."}

    except HttpError as e:
        return {"error": f"Google API error: {e}"}
    except Exception as e:
        return {"error": str(e)}


def get_weather(date: str) -> dict:
    """
    Fetch weather forecast for a given date using the free Open-Meteo API.

    date must be an ISO 8601 date string (YYYY-MM-DD).
    Returns a dict with: date, description, temp_min, temp_max, precipitation_mm.
    Returns {"error": "..."} on failure.
    """
    try:
        url = (
            f"https://api.open-meteo.com/v1/forecast"
            f"?latitude={_LATITUDE}&longitude={_LONGITUDE}"
            f"&daily=temperature_2m_max,temperature_2m_min,precipitation_sum,weathercode"
            f"&timezone=Europe%2FParis"
            f"&start_date={date}&end_date={date}"
        )
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = _json.loads(resp.read().decode())

        daily = data.get("daily", {})
        if not daily.get("time"):
            return {"error": "No weather data returned for that date."}

        code = daily["weathercode"][0]
        return {
            "date": daily["time"][0],
            "description": _WMO_CODES.get(code, f"Weather code {code}"),
            "temp_min": daily["temperature_2m_min"][0],
            "temp_max": daily["temperature_2m_max"][0],
            "precipitation_mm": daily["precipitation_sum"][0],
        }

    except Exception as e:
        return {"error": str(e)}


# ── Helpers ──────────────────────────────────────────────────────────────────

def _to_rfc3339(dt_str: str, start_of_day: bool) -> str:
    """Convert an ISO date or datetime string to a timezone-aware RFC 3339 string."""
    tz = ZoneInfo(TIMEZONE)
    # Bare date (YYYY-MM-DD) — fromisoformat parses it as midnight on all Python
    # versions, so start_of_day=False would silently return 00:00 instead of 23:59.
    # Detect bare dates explicitly before calling fromisoformat.
    if "T" not in dt_str and len(dt_str) == 10:
        d = datetime.strptime(dt_str, "%Y-%m-%d")
        hour = 0 if start_of_day else 23
        minute = 0 if start_of_day else 59
        second = 0 if start_of_day else 59
        return d.replace(hour=hour, minute=minute, second=second, tzinfo=tz).isoformat()
    try:
        dt = datetime.fromisoformat(dt_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=tz)
    except ValueError:
        d = datetime.strptime(dt_str, "%Y-%m-%d")
        if start_of_day:
            dt = d.replace(hour=0, minute=0, second=0, tzinfo=tz)
        else:
            dt = d.replace(hour=23, minute=59, second=59, tzinfo=tz)
    return dt.isoformat()
