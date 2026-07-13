"""
Morning briefing for the Calendar Agent.

Run manually:
    python briefing.py

Or schedule with cron (8 AM Paris time):
    0 8 * * * /path/to/venv/bin/python /path/to/calendar_agent/briefing.py

Prints a rich-formatted summary of:
  • Today's weather
  • Today's events (chronological)
  • Suggested lunch window (first free 60-min slot between 12:00–14:00)
  • Count of remaining free slots in the afternoon
"""

import os
import sys
from datetime import datetime, time
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich import box

# Load .env from this directory first, then try the parent.
_here = os.path.dirname(os.path.abspath(__file__))
load_dotenv(dotenv_path=os.path.join(_here, ".env"))
load_dotenv(dotenv_path=os.path.join(_here, "..", ".env"))

from calendar_tools import get_events, find_free_slots, get_weather  # noqa: E402

TIMEZONE = "Europe/Paris"
WORK_START = 8   # hour
WORK_END   = 20  # hour
LUNCH_START = 12
LUNCH_END   = 14

console = Console()


def _fmt_time(iso: str) -> str:
    """Return HH:MM from an ISO 8601 datetime string."""
    try:
        dt = datetime.fromisoformat(iso).astimezone(ZoneInfo(TIMEZONE))
        return dt.strftime("%H:%M")
    except Exception:
        return iso


def _weather_emoji(description: str) -> str:
    d = description.lower()
    if "thunder" in d:
        return "⛈️"
    if "snow" in d:
        return "❄️"
    if "rain" in d or "drizzle" in d or "shower" in d:
        return "🌧️"
    if "fog" in d:
        return "🌫️"
    if "overcast" in d or "cloudy" in d:
        return "☁️"
    if "partly" in d:
        return "⛅"
    return "☀️"


def build_briefing() -> None:
    tz = ZoneInfo(TIMEZONE)
    today = datetime.now(tz)
    today_str = today.strftime("%Y-%m-%d")
    date_label = today.strftime("%A, %d %B %Y")

    console.print()
    console.print(Rule(f"[bold yellow]☀ Morning Briefing — {date_label}[/bold yellow]"))
    console.print()

    # ── Weather ───────────────────────────────────────────────────────────────
    weather = get_weather(today_str)
    if "error" in weather:
        console.print(f"[red]Weather unavailable:[/red] {weather['error']}")
    else:
        emoji = _weather_emoji(weather["description"])
        console.print(Panel(
            f"{emoji}  [bold]{weather['description']}[/bold]\n"
            f"   🌡  {weather['temp_min']}°C – {weather['temp_max']}°C\n"
            f"   🌧  Precipitation: {weather['precipitation_mm']} mm",
            title="[cyan]Weather · Paris[/cyan]",
            expand=False,
            border_style="cyan",
        ))

    console.print()

    # ── Today's events ────────────────────────────────────────────────────────
    events = get_events(today_str, today_str)

    if isinstance(events, list) and events and "error" in events[0]:
        console.print(f"[red]Calendar unavailable:[/red] {events[0]['error']}")
        return

    console.print("[bold]📅  Today's Events[/bold]")
    if not events:
        console.print("  [dim]No events today — enjoy the free day![/dim]")
    else:
        table = Table(box=box.SIMPLE, show_header=True, header_style="bold magenta", expand=False)
        table.add_column("Time", style="cyan", no_wrap=True, min_width=12)
        table.add_column("Event")
        for e in events:
            start_s = _fmt_time(e["start"])
            end_s = _fmt_time(e["end"])
            table.add_row(f"{start_s} – {end_s}", e["title"])
        console.print(table)

    console.print()

    # ── Lunch suggestion ──────────────────────────────────────────────────────
    free_slots = find_free_slots(today_str, 60)
    lunch_slot = None
    if isinstance(free_slots, list):
        for slot in free_slots:
            if "error" in slot:
                break
            try:
                slot_start = datetime.fromisoformat(slot["start"]).astimezone(tz)
                slot_end = datetime.fromisoformat(slot["end"]).astimezone(tz)
                # Accept any slot that overlaps [LUNCH_START, LUNCH_END]
                if slot_start.hour < LUNCH_END and slot_end.hour > LUNCH_START:
                    # Clamp to the lunch window
                    lunch_from = max(slot_start, slot_start.replace(hour=LUNCH_START, minute=0, second=0))
                    lunch_to = min(slot_end, slot_end.replace(hour=LUNCH_END, minute=0, second=0))
                    if (lunch_to - lunch_from).total_seconds() >= 3600:
                        lunch_slot = (lunch_from, lunch_to)
                        break
            except Exception:
                pass

    console.print("[bold]🍽️  Suggested Lunch Window[/bold]")
    if lunch_slot:
        lf, lt = lunch_slot
        console.print(
            f"  [green]{lf.strftime('%H:%M')} – {lt.strftime('%H:%M')}[/green]  "
            f"(first free 60-min block in the 12:00–14:00 window)"
        )
    else:
        console.print("  [yellow]No free 60-min block found between 12:00–14:00. Check your schedule![/yellow]")

    console.print()

    # ── Afternoon free slots ───────────────────────────────────────────────────
    afternoon_free = []
    if isinstance(free_slots, list):
        for slot in free_slots:
            if "error" in slot:
                break
            try:
                slot_start = datetime.fromisoformat(slot["start"]).astimezone(tz)
                if slot_start.hour >= LUNCH_END:
                    afternoon_free.append(slot)
            except Exception:
                pass

    console.print("[bold]🕐  Afternoon Free Slots[/bold]")
    if afternoon_free:
        for slot in afternoon_free:
            s = _fmt_time(slot["start"])
            e = _fmt_time(slot["end"])
            console.print(f"  [green]{s} – {e}[/green]")
    else:
        console.print("  [dim]No free afternoon slots today.[/dim]")

    console.print()
    console.print(Rule("[dim]Have a great day![/dim]"))
    console.print()


if __name__ == "__main__":
    build_briefing()
