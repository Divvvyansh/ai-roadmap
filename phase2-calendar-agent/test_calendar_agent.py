"""
pytest suite for the calendar agent.

Run from the calendar_agent/ directory:
    pytest test_calendar_agent.py -v

All Google API and HTTP calls are mocked — no credentials required.
"""

import json
import sys
import types
from datetime import datetime
from io import BytesIO
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

# ---------------------------------------------------------------------------
# Make calendar_agent imports resolve when pytest is run from the repo root
# ---------------------------------------------------------------------------
import os
sys.path.insert(0, os.path.dirname(__file__))

import calendar_tools as ct
from agent import TOOL_MAP, run_tool, trim_history
from tool_schemas import TOOLS


# ===========================================================================
# Helpers
# ===========================================================================

PARIS = ZoneInfo("Europe/Paris")


def _make_service_event(
    event_id="evt1",
    summary="Test Event",
    start_dt="2026-06-10T09:00:00+02:00",
    end_dt="2026-06-10T10:00:00+02:00",
    description="",
    html_link="https://calendar.google.com/event/1",
):
    """Build a minimal Google Calendar API event dict."""
    return {
        "id": event_id,
        "summary": summary,
        "start": {"dateTime": start_dt},
        "end": {"dateTime": end_dt},
        "description": description,
        "htmlLink": html_link,
    }


# ===========================================================================
# _to_rfc3339  (pure function — no mocking)
# ===========================================================================


class TestToRfc3339:
    def test_bare_date_start_of_day(self):
        result = ct._to_rfc3339("2026-06-10", start_of_day=True)
        dt = datetime.fromisoformat(result)
        assert dt.hour == 0 and dt.minute == 0 and dt.second == 0
        assert dt.tzinfo is not None

    def test_bare_date_end_of_day(self):
        result = ct._to_rfc3339("2026-06-10", start_of_day=False)
        dt = datetime.fromisoformat(result)
        assert dt.hour == 23 and dt.minute == 59

    def test_datetime_with_tz_passthrough(self):
        iso = "2026-06-10T14:30:00+02:00"
        result = ct._to_rfc3339(iso, start_of_day=True)
        dt = datetime.fromisoformat(result)
        assert dt.hour == 14 and dt.minute == 30

    def test_datetime_without_tz_gets_paris(self):
        result = ct._to_rfc3339("2026-06-10T10:00:00", start_of_day=True)
        dt = datetime.fromisoformat(result)
        assert dt.tzinfo is not None


# ===========================================================================
# get_events
# ===========================================================================


class TestGetEvents:
    def _mock_service(self, items):
        svc = MagicMock()
        svc.events().list().execute.return_value = {"items": items}
        return svc

    def test_returns_list_of_event_dicts(self):
        item = _make_service_event()
        with patch.object(ct, "_get_service", return_value=self._mock_service([item])):
            result = ct.get_events("2026-06-10", "2026-06-10")
        assert isinstance(result, list)
        assert result[0]["id"] == "evt1"
        assert result[0]["title"] == "Test Event"

    def test_empty_calendar_returns_empty_list(self):
        with patch.object(ct, "_get_service", return_value=self._mock_service([])):
            result = ct.get_events("2026-06-10", "2026-06-10")
        assert result == []

    def test_missing_summary_uses_fallback(self):
        item = _make_service_event(summary=None)
        item.pop("summary", None)
        with patch.object(ct, "_get_service", return_value=self._mock_service([item])):
            result = ct.get_events("2026-06-10", "2026-06-10")
        assert result[0]["title"] == "(No title)"

    def test_http_error_returns_error_dict(self):
        from googleapiclient.errors import HttpError
        svc = MagicMock()
        svc.events().list().execute.side_effect = HttpError(
            resp=MagicMock(status=403, reason="Forbidden"), content=b"Forbidden"
        )
        with patch.object(ct, "_get_service", return_value=svc):
            result = ct.get_events("2026-06-10", "2026-06-10")
        assert "error" in result[0]

    def test_generic_exception_returns_error_dict(self):
        with patch.object(ct, "_get_service", side_effect=RuntimeError("boom")):
            result = ct.get_events("2026-06-10", "2026-06-10")
        assert "error" in result[0]


# ===========================================================================
# find_free_slots
# ===========================================================================


class TestFindFreeSlots:
    def test_empty_day_returns_full_window(self):
        with patch.object(ct, "get_events", return_value=[]):
            slots = ct.find_free_slots("2026-06-10", 60)
        assert len(slots) == 1
        start = datetime.fromisoformat(slots[0]["start"])
        end = datetime.fromisoformat(slots[0]["end"])
        assert start.hour == 8
        assert end.hour == 20

    def test_event_in_middle_splits_day(self):
        events = [{"start": "2026-06-10T12:00:00+02:00", "end": "2026-06-10T13:00:00+02:00"}]
        with patch.object(ct, "get_events", return_value=events):
            slots = ct.find_free_slots("2026-06-10", 60)
        assert len(slots) == 2
        ends = [datetime.fromisoformat(s["end"]).hour for s in slots]
        assert 12 in ends

    def test_duration_longer_than_any_gap_returns_empty(self):
        events = [
            {"start": "2026-06-10T08:00:00+02:00", "end": "2026-06-10T20:00:00+02:00"}
        ]
        with patch.object(ct, "get_events", return_value=events):
            slots = ct.find_free_slots("2026-06-10", 60)
        assert slots == []

    def test_get_events_error_is_propagated(self):
        with patch.object(ct, "get_events", return_value={"error": "API down"}):
            result = ct.find_free_slots("2026-06-10", 30)
        assert result == {"error": "API down"}

    def test_slots_respect_duration_minimum(self):
        # 30-min gap only; requesting 60 min should not include it
        events = [
            {"start": "2026-06-10T08:30:00+02:00", "end": "2026-06-10T20:00:00+02:00"}
        ]
        with patch.object(ct, "get_events", return_value=events):
            slots = ct.find_free_slots("2026-06-10", 60)
        assert slots == []


# ===========================================================================
# create_event
# ===========================================================================


class TestCreateEvent:
    def _mock_service(self, returned_event):
        svc = MagicMock()
        svc.events().insert().execute.return_value = returned_event
        return svc

    def test_success_returns_event_dict(self):
        raw = _make_service_event()
        with patch.object(ct, "_get_service", return_value=self._mock_service(raw)):
            result = ct.create_event(
                title="Test Event",
                start="2026-06-10T09:00:00+02:00",
                end="2026-06-10T10:00:00+02:00",
            )
        assert result["id"] == "evt1"
        assert result["title"] == "Test Event"
        assert "link" in result

    def test_attendees_added_to_body(self):
        raw = _make_service_event()
        svc = MagicMock()
        svc.events().insert().execute.return_value = raw
        with patch.object(ct, "_get_service", return_value=svc):
            ct.create_event(
                title="Meeting",
                start="2026-06-10T09:00:00+02:00",
                end="2026-06-10T10:00:00+02:00",
                attendees=["alice@example.com"],
            )
        call_kwargs = svc.events().insert.call_args[1]["body"]
        assert call_kwargs["attendees"] == [{"email": "alice@example.com"}]

    def test_http_error_returns_error_dict(self):
        from googleapiclient.errors import HttpError
        svc = MagicMock()
        svc.events().insert().execute.side_effect = HttpError(
            resp=MagicMock(status=400, reason="Bad Request"), content=b""
        )
        with patch.object(ct, "_get_service", return_value=svc):
            result = ct.create_event("T", "2026-06-10T09:00:00+02:00", "2026-06-10T10:00:00+02:00")
        assert "error" in result


# ===========================================================================
# update_event
# ===========================================================================


class TestUpdateEvent:
    def test_title_update(self):
        raw = _make_service_event(summary="Old Title")
        updated = _make_service_event(summary="New Title")
        svc = MagicMock()
        svc.events().get().execute.return_value = raw
        svc.events().update().execute.return_value = updated
        with patch.object(ct, "_get_service", return_value=svc):
            result = ct.update_event("evt1", {"title": "New Title"})
        assert result["title"] == "New Title"

    def test_http_error_returns_error_dict(self):
        from googleapiclient.errors import HttpError
        svc = MagicMock()
        svc.events().get().execute.side_effect = HttpError(
            resp=MagicMock(status=404, reason="Not Found"), content=b""
        )
        with patch.object(ct, "_get_service", return_value=svc):
            result = ct.update_event("missing", {"title": "X"})
        assert "error" in result


# ===========================================================================
# cancel_event
# ===========================================================================


class TestCancelEvent:
    def test_success_returns_message(self):
        svc = MagicMock()
        svc.events().delete().execute.return_value = None
        with patch.object(ct, "_get_service", return_value=svc):
            result = ct.cancel_event("evt1")
        assert "message" in result
        assert "error" not in result

    def test_http_error_returns_error_dict(self):
        from googleapiclient.errors import HttpError
        svc = MagicMock()
        svc.events().delete().execute.side_effect = HttpError(
            resp=MagicMock(status=404, reason="Not Found"), content=b""
        )
        with patch.object(ct, "_get_service", return_value=svc):
            result = ct.cancel_event("missing")
        assert "error" in result


# ===========================================================================
# get_weather
# ===========================================================================


def _make_weather_response(code=0, t_min=10.0, t_max=20.0, precip=0.0, date="2026-06-10"):
    payload = {
        "daily": {
            "time": [date],
            "weathercode": [code],
            "temperature_2m_min": [t_min],
            "temperature_2m_max": [t_max],
            "precipitation_sum": [precip],
        }
    }
    return BytesIO(json.dumps(payload).encode())


class TestGetWeather:
    def test_known_wmo_code_returns_description(self):
        resp = MagicMock()
        resp.read.return_value = _make_weather_response(code=0).read()
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=resp):
            result = ct.get_weather("2026-06-10")
        assert result["description"] == "Clear sky"
        assert result["temp_min"] == 10.0
        assert result["temp_max"] == 20.0
        assert result["precipitation_mm"] == 0.0

    def test_unknown_wmo_code_falls_back_to_code_string(self):
        resp = MagicMock()
        resp.read.return_value = _make_weather_response(code=999).read()
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=resp):
            result = ct.get_weather("2026-06-10")
        assert "999" in result["description"]

    def test_empty_response_returns_error(self):
        payload = json.dumps({"daily": {}}).encode()
        resp = MagicMock()
        resp.read.return_value = payload
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=resp):
            result = ct.get_weather("2026-06-10")
        assert "error" in result

    def test_network_error_returns_error(self):
        with patch("urllib.request.urlopen", side_effect=OSError("timeout")):
            result = ct.get_weather("2026-06-10")
        assert "error" in result


# ===========================================================================
# run_tool dispatcher (agent.py)
# ===========================================================================


class TestRunTool:
    def test_unknown_tool_returns_error(self):
        result = run_tool("nonexistent_tool", {})
        assert "error" in result

    def test_dispatches_to_correct_function(self):
        with patch.dict(TOOL_MAP, {"fake": lambda: {"ok": True}}):
            result = run_tool("fake", {})
        assert result == {"ok": True}


# ===========================================================================
# trim_history (agent.py)
# ===========================================================================


class TestTrimHistory:
    def _make_history(self, n_user_turns):
        history = []
        for _ in range(n_user_turns):
            history.append({"role": "user", "content": "hello"})
            history.append({"role": "assistant", "content": [MagicMock(text="reply")]})
        return history

    def test_short_history_unchanged(self):
        h = self._make_history(5)
        result = trim_history(h)
        assert result == h

    def test_long_history_trimmed(self):
        h = self._make_history(15)
        result = trim_history(h)
        assert len(result) < len(h)

    def test_trim_never_starts_with_tool_result(self):
        h = self._make_history(15)
        result = trim_history(h)
        first = result[0]
        assert first["role"] == "user"
        assert isinstance(first["content"], str)


# ===========================================================================
# Schema + wiring integrity
# ===========================================================================


class TestToolSchemas:
    def test_all_schemas_have_required_keys(self):
        for schema in TOOLS:
            assert "name" in schema
            assert "description" in schema
            assert "input_schema" in schema

    def test_input_schema_has_type_and_properties(self):
        for schema in TOOLS:
            inp = schema["input_schema"]
            assert inp.get("type") == "object"
            assert "properties" in inp

    def test_no_extra_top_level_keys(self):
        allowed = {"name", "description", "input_schema"}
        for schema in TOOLS:
            extras = set(schema.keys()) - allowed
            assert extras == set(), f"{schema['name']} has unexpected keys: {extras}"


class TestToolWiring:
    def test_every_schema_name_is_in_tool_map(self):
        schema_names = {s["name"] for s in TOOLS}
        for name in schema_names:
            assert name in TOOL_MAP, f"'{name}' in TOOLS but missing from TOOL_MAP"

    def test_every_tool_map_entry_has_a_schema(self):
        schema_names = {s["name"] for s in TOOLS}
        for name in TOOL_MAP:
            assert name in schema_names, f"'{name}' in TOOL_MAP but missing from TOOLS"

    def test_all_tool_map_values_are_callable(self):
        for name, fn in TOOL_MAP.items():
            assert callable(fn), f"TOOL_MAP['{name}'] is not callable"

    def test_tool_functions_importable_from_calendar_tools(self):
        for name in TOOL_MAP:
            assert hasattr(ct, name), f"Function '{name}' not found in calendar_tools.py"