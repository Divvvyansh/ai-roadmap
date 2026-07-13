# Expense Tracker

An expense tracker where an LLM handles the ambiguous parts — parsing "coffee 5 at Starbucks yesterday" into structured data, classifying what a question is actually asking — and plain Python handles the parts that don't need a model: filtering, aggregation, validation.

Phase 1 of a self-directed AI engineering roadmap. The point of this phase was the hybrid split itself: knowing which parts of a feature are a genuine language-understanding problem (worth an LLM call) versus a deterministic lookup (worth a `for` loop), instead of routing everything through the model by default.

## What it does

- **Logs expenses from natural language** — `extract_expense()` sends free text to Claude with a structured-output prompt, then `validate_expense()` checks the result deterministically (amount is numeric, merchant is present, category falls back to "Other" if the model returns something unrecognized) before it's ever saved
- **Answers questions about your spending**, with two tiers of cost: `parse_query()` classifies intent + category + time range via one Claude call, then `total` / `category_total` questions are answered by plain Python summation — no second LLM call needed. Only open-ended questions ("what did I spend the most on this month?") fall through to a Claude call over the filtered data
- **Multi-turn query memory** — follow-up questions like "and transport?" reuse the conversation history
- **Two frontends over the same `tracker/` logic**: a REPL (`cli.py`) and a Streamlit dashboard (`app.py`) with spend-by-category charts and an LLM-generated summary

## Architecture

```text
                                ┌─────────────────────┐
 "coffee 5 at Starbucks" ──────▶│ extract_expense()    │──▶ validate_expense() ──▶ storage.py
                                │ (Claude, structured   │      (deterministic)      (JSONL)
                                │  output prompt)       │
                                └─────────────────────┘

                                ┌─────────────────────┐
 "how much on food?"    ──────▶│ parse_query()         │
                                │ (Claude → intent,     │
                                │  category, time_range)│
                                └──────────┬───────────┘
                                           │
                              filter_by_category/time()
                                     (deterministic)
                                           │
                          ┌────────────────┴────────────────┐
                          ▼                                  ▼
                 intent = total /                    intent = anything else
                 category_total                       (open-ended question)
                          │                                  │
                  sum() in Python                    second Claude call over
                  (no LLM call)                       the filtered expenses
```

| Path | Responsibility |
| --- | --- |
| `tracker/extractor.py` | Claude call that turns free text into `{amount, merchant, category, date}` |
| `tracker/validator.py` | Deterministic checks on the extracted dict — never trusts the model's output shape blindly |
| `tracker/query_parser.py` | Claude call that classifies a question into `intent` / `category` / `time_range` |
| `tracker/filters.py` | Pure Python filtering by category and time range (today/this week/this month/...) |
| `tracker/llm_query.py` | Routes `total`/`category_total` to plain summation; only open-ended questions get a second Claude call. Also generates the spending summary. |
| `tracker/storage.py` | Appends/reads expenses as newline-delimited JSON at `data/expenses.json` |
| `tracker/expense_editor.py` | Lets you correct a field before saving, in case the extraction got something wrong |
| `cli.py` | Terminal REPL: `expense` / `query` / `summary` / `exit` |
| `app.py` | Streamlit UI: add-expense form, chat-style query mode, summary dashboard with charts |

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env   # fill in ANTHROPIC_API_KEY
```

Run the CLI:

```bash
python cli.py
```

Or the Streamlit dashboard:

```bash
streamlit run app.py
```

## Example usage

```text
Type 'expense' if you want to add an expense or 'query' to ask about your expenses.
you can also type 'summary' for a summary of your expenses (or 'exit' to quit): expense
coffee 4.5 at Starbucks yesterday
ExpenseAI: {'amount': 4.5, 'merchant': 'Starbucks', 'category': 'Food & Drink', 'date': '2026-07-12'}
ExpenseAI: Do you want to save this expense? (yes/no): yes
Expense saved successfully

...: query
ExpenseAI: Ask me anything about your spending. (type 'back' to exit query mode)
You: how much did I spend on food?
ExpenseAI: You spent 45.50 on Food & Drink
You: and transport?
ExpenseAI: You spent 60.00 on Transport
```

## Testing

```bash
pytest
```

`tests/test_extractor_cases.py` calls the real Claude API (no mocking) — running it costs a small amount of API usage and requires `ANTHROPIC_API_KEY` to be set.

## Design notes

- **The LLM/Python split is the actual lesson of this phase.** Extraction and intent classification are genuinely ambiguous language problems — worth a model call. Filtering by date range and summing numbers are not, and routing those through an LLM would be slower, costlier, and non-deterministic for no benefit.
- **Validation never trusts the model's output shape.** `validate_expense()` re-checks types and falls back to `"Other"` for an unrecognized category rather than assuming the structured-output prompt was followed exactly.
- **Storage is newline-delimited JSON, not a single JSON array** — appending a line is O(1) and doesn't require reading/rewriting the whole file on every save.
