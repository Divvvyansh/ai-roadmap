import json
from tracker.claude_client import get_client
from tracker.categories import CATEGORIES_STR
from tracker.validator import validate_expense

SYSTEM_PROMPT = f"""
You are an expense parser.

Extract structured data from user input.

Consider any amount without a currency to be in euros. If a date is not provided, null.

Return ONLY valid JSON.

Allowed categories:
{CATEGORIES_STR}

Examples:

Input: "coffee 3.5 at Starbucks yesterday"
Output:
{{
  "amount": 3.5,
  "merchant": "Starbucks",
  "category": "Food & Drink",
  "date": "2026-04-18"
}}

Input: "uber ride 15 euros"
Output:
{{
  "amount": 15,
  "merchant": "Uber",
  "category": "Transport",
  "date": null
}}

Input: "colgate mouthwash 5.99"
Output:
{{
  "amount": 5.99,
  "merchant": "Colgate",
  "category": "Other",
  "date": null
}}

Rules:
- No explanation
- No markdown
- No extra text
- Always return valid JSON
"""

def extract_expense(text: str) -> dict:
    client = get_client()
    messages = []
    messages.append({"role": "user", "content": text})
    messages.append({"role": "assistant", "content": "here is the json without any additional comments. /n ```json"})

    response = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=250,
        system=SYSTEM_PROMPT,
        messages=messages,
        stop_sequences=["```"]
    )
    parsed = json.loads(response.content[0].text)
    validated = validate_expense(parsed)
    return validated