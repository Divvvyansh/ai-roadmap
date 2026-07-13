from datetime import datetime, timedelta

def filter_by_category(expenses, category):
    if not category:
        return expenses
    return [e for e in expenses if e["category"] == category]


def filter_by_time(expenses, time_range):
    if not time_range or time_range == "all_time":
        return expenses

    now = datetime.now()

    if time_range == "today":
        return [e for e in expenses if e["date"] == now.strftime("%Y-%m-%d")]
    
    if time_range == "yesterday":
        yesterday = now - timedelta(days=1)
        return [e for e in expenses if e["date"] == yesterday.strftime("%Y-%m-%d")]

    if time_range == "this_week":
        week_ago = now - timedelta(days=7)
        return [
            e for e in expenses
            if e["date"] and datetime.fromisoformat(e["date"]) >= week_ago
        ]

    if time_range == "last_week":
        week_ago = now - timedelta(days=7)
        two_weeks_ago = now - timedelta(days=14)
        return [
            e for e in expenses
            if e["date"] and two_weeks_ago <= datetime.fromisoformat(e["date"]) < week_ago
        ]

    if time_range == "this_month":
        return [
            e for e in expenses
            if e["date"] and e["date"].startswith(now.strftime("%Y-%m"))
        ]
    
    if time_range == "last_month":
        last_month = (now.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
        return [e for e in expenses if e["date"] and e["date"].startswith(last_month)]

    return expenses