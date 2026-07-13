from tracker.categories import CATEGORIES

def validate_expense(data: dict) -> dict:

    if not isinstance(data.get("amount"), (int, float)):
        raise ValueError("Invalid amount")

    if not isinstance(data.get("merchant"), str):
        raise ValueError("Invalid merchant")

    if data.get("category") not in CATEGORIES:
        data["category"] = "Other"

    if data.get("date") is not None and not isinstance(data.get("date"), str):
        data["date"] = None

    return data