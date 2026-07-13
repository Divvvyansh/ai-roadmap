from tracker.claude_client import get_client
from tracker.query_parser import parse_query
from tracker.filters import filter_by_category, filter_by_time
import json

def total_spent(expenses):
    return sum(e["amount"] for e in expenses)

def spent_by_category(expenses, category):
    return sum(e["amount"] for e in expenses if e["category"] == category)

SYSTEM_PROMPT = """
You are a financial assistant.

You are given a list of expenses in JSON format.

Answer the user's question using ONLY the provided data.

Rules:
- Do not make up data
- Only use the expenses provided
- If you can't access or don't see any data in the passed expenses, say "I don't have any data".
- If the answer cannot be determined, say "I don't have enough data".
- Be concise.
- Return a direct answer (no explanations).
- All currencies are in EUR.
"""

def answer_query(question: str, expenses: list, history: list) -> str:
    client = get_client()

    parsed = parse_query(question)

    filtered = filter_by_category(expenses, parsed.get("category"))
    filtered = filter_by_time(filtered, parsed.get("time_range"))

    if parsed["intent"] == "total":
        total = sum(e["amount"] for e in filtered)
        history.append({"role": "user", "content": question})
        history.append({"role": "assistant", "content": f"You spent {total:.2f}"})
        return f"You spent {total:.2f}"

    if parsed["intent"] == "category_total":
        total = sum(e["amount"] for e in filtered)
        history.append({"role": "user", "content": question})
        history.append({"role": "assistant", "content": f"You spent {total:.2f} on {parsed['category']}"})
        return f"You spent {total:.2f} on {parsed['category']}"

    expenses_json = json.dumps(filtered)

    messages = history + [
        {
            "role": "user",
            "content": f"""
Expenses:
{expenses_json}

Question:
{question}
"""
        }
    ]

    response = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=200,
        system=SYSTEM_PROMPT,
        messages=messages
    )

    answer = response.content[0].text.strip()

    history.append({"role": "user", "content": question})
    history.append({"role": "assistant", "content": answer})

    return answer

Sys_prompt_2= """
You are a financial summarizer.

You are given a list of expenses in JSON format.

return a summary of the expenses with only the following information:
- Total spent
- Top cartegory (the category with the highest total spending)
- Amount spent in top category
- Biggest single expense (return merchant and amount)
- Most frequent merchant (return merchant and number of transactions)

Example output:
Total spent: 1234.56 EUR
Top category: Food & Beverages (456.78 EUR)
Biggest single expense: Amazon (123.45 EUR)
Most frequent merchant: Starbucks (5 transactions)

Rules:
- Do not make up data
- Only use the expenses provided
- If the answer cannot be determined, say "I don't have enough data".
- Be concise.
- Return a direct answer (no explanations).
- All currencies are in EUR.
"""

def summarizer(expenses):
    client = get_client()

    expenses_json = json.dumps(expenses)

    response = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=500,
        system=Sys_prompt_2,
        messages=[{"role": "user", "content": f"Expenses:\n{expenses_json}"}]
    )

    return response.content[0].text.strip()