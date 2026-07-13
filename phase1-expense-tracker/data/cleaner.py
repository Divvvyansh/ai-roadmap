import json

with open("expenses.json", "r") as f:
    content = f.read()

# Split manually
items = content.replace("}{", "}\n{").split("\n")

cleaned = [json.loads(item) for item in items]

with open("data/expenses.json", "w") as f:
    for item in cleaned:
        f.write(json.dumps(item) + "\n")