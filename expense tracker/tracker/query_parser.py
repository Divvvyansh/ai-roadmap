import json
from tracker.claude_client import get_client
from tracker.categories import CATEGORIES_STR

SYSTEM_PROMPT = f"""
You are a query parser for an expense tracker.

Convert a user question into structured JSON.

Return ONLY JSON with:
- intent: "total" | "category_total" | "list" | "unknown"
- category: one of [{CATEGORIES_STR}] or null
- time_range: "today" | "this_week" | "this_month" | "all_time" or null

Examples:

Input: "How much did I spend?"
Output:
{{"intent": "total", "category": null, "time_range": "all_time"}}

Input: "How much did I spend on food?"
Output:
{{"intent": "category_total", "category": "Food & Drink", "time_range": "all_time"}}

Input: "Show my expenses this month"
Output:
{{"intent": "list", "category": null, "time_range": "this_month"}}

Rules:
- Only JSON
- No explanation
"""

def parse_query(text: str) -> dict:
    client = get_client()
    messages = []
    messages.append({"role": "user", "content": text})
    messages.append({"role": "assistant", "content": "here is the json without any additional comments. /n ```json"})

    response = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=100,
        system=SYSTEM_PROMPT,
        messages=messages,
        stop_sequences=["```"]
    )

    return json.loads(response.content[0].text)