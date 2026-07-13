import json

FILE_PATH = "data/expenses.json"

def save_expense(expense: dict):
    try:
        with open(FILE_PATH, "a") as f:
            f.write("\n"+json.dumps(expense))
    except Exception as e:
        raise 

def load_expenses():
    expenses = []
    try:
        with open(FILE_PATH, "r") as f:
            for line in f:
                expenses.append(json.loads(line))
    except FileNotFoundError:
        raise
    return expenses