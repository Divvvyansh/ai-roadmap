"""
Telegram bot frontend for the Calendar Agent.

Setup:
  1. Create a bot via @BotFather → copy the token
  2. Add TELEGRAM_BOT_TOKEN=<token> to your .env file
  3. pip install python-telegram-bot
  4. python telegram_bot.py

Commands:
  /start    — greeting
  /briefing — send today's morning briefing inline
  /clear    — wipe this chat's conversation history
  Any other message is forwarded to the calendar agent tool loop.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from typing import Dict, List, Optional

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from telegram.constants import ParseMode

import anthropic
from rich.console import Console

# Load .env from this directory first (contains TELEGRAM_BOT_TOKEN),
# then try the parent directory for ANTHROPIC_API_KEY if it lives there.
_here = os.path.dirname(os.path.abspath(__file__))
load_dotenv(dotenv_path=os.path.join(_here, ".env"))
load_dotenv(dotenv_path=os.path.join(_here, "..", ".env"))

from calendar_tools import (  # noqa: E402
    create_event,
    find_free_slots,
    get_events,
    update_event,
    cancel_event,
    get_weather,
)
from tool_schemas import TOOLS  # noqa: E402
from briefing import build_briefing  # noqa: E402

# ── Config ────────────────────────────────────────────────────────────────────

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ANTHROPIC_KEY  = os.getenv("ANTHROPIC_API_KEY")
MODEL          = "claude-sonnet-4-5"
MAX_HISTORY    = 10
TIMEZONE       = "Europe/Paris"

logging.basicConfig(
    format="%(asctime)s  %(name)s  %(levelname)s  %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Suppress chatty telegram library logs
logging.getLogger("httpx").setLevel(logging.WARNING)

# ── Shared state ──────────────────────────────────────────────────────────────

# One conversation history per Telegram chat_id
_histories: Dict[int, List[dict]] = {}

anthropic_client: Optional[anthropic.Anthropic] = None

# ── Tool dispatcher ───────────────────────────────────────────────────────────

TOOL_MAP = {
    "get_events": get_events,
    "find_free_slots": find_free_slots,
    "create_event": create_event,
    "update_event": update_event,
    "cancel_event": cancel_event,
    "get_weather": get_weather,
}


def run_tool(name: str, inputs: dict):
    fn = TOOL_MAP.get(name)
    if fn is None:
        return {"error": f"Unknown tool: {name}"}
    return fn(**inputs)


# ── System prompt ─────────────────────────────────────────────────────────────

def build_system_prompt() -> str:
    from datetime import datetime
    from zoneinfo import ZoneInfo
    now = datetime.now(ZoneInfo(TIMEZONE))
    return f"""You are a helpful calendar and event management assistant with access to the user's Google Calendar.
You are running as a Telegram bot. Keep replies concise — Telegram is a messaging app, not a terminal.
Use plain text formatting (no markdown headers). Bullet points are fine.

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
- Keep responses short. This is a chat interface.
"""


# ── History helpers ───────────────────────────────────────────────────────────

def get_history(chat_id: int) -> list[dict]:
    return _histories.setdefault(chat_id, [])


def trim_history(history: list[dict]) -> list[dict]:
    """Same safe-trim logic as agent.py."""
    if len(history) <= MAX_HISTORY * 2:
        return history
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


# ── Core chat function ────────────────────────────────────────────────────────

def chat_sync(history: list[dict], user_input: str) -> str:
    """
    Single user turn through the full tool loop.
    Mutates history in place. Returns Claude's final text response.
    Runs synchronously — called from async handlers via run_in_executor.
    """
    history.append({"role": "user", "content": user_input})

    while True:
        response = anthropic_client.messages.create(
            model=MODEL,
            max_tokens=2048,
            system=build_system_prompt(),
            tools=TOOLS,
            messages=history,
        )

        history.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            return " ".join(
                block.text for block in response.content if hasattr(block, "text")
            )

        if response.stop_reason == "tool_use":
            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                logger.info("Tool call: %s(%s)", block.name, block.input)
                result = run_tool(block.name, block.input)
                logger.info("Tool result: %s", str(result)[:200])
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(result, ensure_ascii=False),
                })
            history.append({"role": "user", "content": tool_results})
            continue

        return f"[Unexpected stop_reason: {response.stop_reason}]"


# ── Telegram handlers ─────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "👋 Hi! I'm your Calendar Agent.\n\n"
        "Talk to me in plain English — I can check your schedule, find free slots, "
        "create and update events.\n\n"
        "Commands:\n"
        "  /briefing — today's morning briefing\n"
        "  /clear    — reset conversation history\n\n"
        "What can I help you with?"
    )


async def cmd_clear(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    _histories[chat_id] = []
    await update.message.reply_text("🗑️ Conversation history cleared.")


async def cmd_briefing(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send today's briefing as a Telegram message."""
    await update.message.reply_text("⏳ Generating today's briefing…")

    # Run the briefing in a thread (it makes network calls)
    loop = asyncio.get_event_loop()
    briefing_text = await loop.run_in_executor(None, _generate_briefing_text)

    # Telegram message limit is 4096 chars; truncate if needed
    if len(briefing_text) > 4000:
        briefing_text = briefing_text[:4000] + "\n…(truncated)"

    await update.message.reply_text(briefing_text)


def _generate_briefing_text() -> str:
    """Generate briefing as a plain-text string (no rich formatting)."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    tz = ZoneInfo(TIMEZONE)
    today = datetime.now(tz)
    today_str = today.strftime("%Y-%m-%d")
    date_label = today.strftime("%A, %d %B %Y")

    lines = [f"☀️ Morning Briefing — {date_label}\n"]

    # Weather
    weather = get_weather(today_str)
    if "error" not in weather:
        lines.append(
            f"🌤 Weather: {weather['description']}, "
            f"{weather['temp_min']}°C – {weather['temp_max']}°C, "
            f"{weather['precipitation_mm']} mm rain"
        )
    else:
        lines.append("🌤 Weather: unavailable")

    lines.append("")

    # Events
    events = get_events(today_str, today_str)
    lines.append("📅 Today's Events:")
    if not events or (isinstance(events, list) and "error" in events[0]):
        lines.append("  No events today.")
    else:
        for e in events:
            try:
                s = datetime.fromisoformat(e["start"]).astimezone(tz).strftime("%H:%M")
                en = datetime.fromisoformat(e["end"]).astimezone(tz).strftime("%H:%M")
            except Exception:
                s, en = "?", "?"
            lines.append(f"  • {s}–{en}  {e['title']}")

    lines.append("")

    # Lunch slot
    free_slots = find_free_slots(today_str, 60)
    lunch_slot = None
    if isinstance(free_slots, list):
        for slot in free_slots:
            if "error" in slot:
                break
            try:
                slot_start = datetime.fromisoformat(slot["start"]).astimezone(tz)
                slot_end = datetime.fromisoformat(slot["end"]).astimezone(tz)
                if slot_start.hour < 14 and slot_end.hour > 12:
                    lf = max(slot_start, slot_start.replace(hour=12, minute=0, second=0))
                    lt = min(slot_end, slot_end.replace(hour=14, minute=0, second=0))
                    if (lt - lf).total_seconds() >= 3600:
                        lunch_slot = (lf, lt)
                        break
            except Exception:
                pass

    lines.append("🍽 Suggested Lunch:")
    if lunch_slot:
        lf, lt = lunch_slot
        lines.append(f"  {lf.strftime('%H:%M')}–{lt.strftime('%H:%M')}")
    else:
        lines.append("  No free 60-min lunch slot found.")

    return "\n".join(lines)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Route any plain text message through the calendar agent."""
    chat_id = update.effective_chat.id
    user_text = update.message.text.strip()

    if not user_text:
        return

    # Show a typing indicator
    await context.bot.send_chat_action(chat_id=chat_id, action="typing")

    history = get_history(chat_id)
    loop = asyncio.get_event_loop()

    try:
        reply = await loop.run_in_executor(None, chat_sync, history, user_text)
    except Exception as exc:
        logger.exception("Error in chat_sync")
        reply = f"⚠️ Something went wrong: {exc}"

    _histories[chat_id] = trim_history(history)

    # Telegram has a 4096 char limit per message
    for chunk_start in range(0, len(reply), 4000):
        await update.message.reply_text(reply[chunk_start:chunk_start + 4000])


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    if not TELEGRAM_TOKEN:
        print("ERROR: TELEGRAM_BOT_TOKEN not set. Add it to your .env file.")
        sys.exit(1)
    if not ANTHROPIC_KEY:
        print("ERROR: ANTHROPIC_API_KEY not set. Add it to your .env file.")
        sys.exit(1)

    global anthropic_client
    anthropic_client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("briefing", cmd_briefing))
    app.add_handler(CommandHandler("clear", cmd_clear))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Bot is running. Press Ctrl+C to stop.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
