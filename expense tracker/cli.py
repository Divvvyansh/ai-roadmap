
from tracker.claude_client import get_client
from tracker.extractor import extract_expense
from tracker.storage import save_expense, load_expenses
from tracker.llm_query import answer_query
from rich import print

def expense_extractor(text: str):
    return(extract_expense(text))

def save_expense_data(expense: dict):
    save_expense(expense)

def test_api():
    client = get_client()

    response = client.messages.create(
        model="claude-sonnet-4-0",
        max_tokens=100,
        messages=[
            {"role": "user", "content": "Say hello in one word"}
        ]
    )
    print(response.content[0].text)

def main():
    while True:
        user_input = input("Type 'expense' if you want to add an expense or 'query' to ask about your expenses (or 'exit' to quit): ")

        if user_input.lower() == 'query':
            expenses = load_expenses()
            history = []
            print("ExpenseAI: Ask me anything about your spending. (type 'back' to exit query mode)")
            while True:
                question = input("You: ")
                if question.lower() == 'back':
                    break
                answer = answer_query(question, expenses, history)
                print("ExpenseAI:", answer)
        
        elif user_input.lower() == 'expense':
            try:
                expense = expense_extractor(user_input)
                print("ExpenseAI:", expense)
                if expense:
                    user_input = input("ExpenseAI: Do you want to save this expense? (yes/no): ")
                    if user_input.lower() == 'yes':
                        save_expense_data(expense)
                        print("[bold green]Expense saved successfully[/bold green]")
                    elif user_input.lower() == 'no':
                        print("ExpenseAI: Expense not saved.")
                    else:
                        print("ExpenseAI: Invalid input. Expense not saved.")
            except Exception as e:
                print("Error extracting expense:", e)

        elif user_input.lower() == 'exit':
            break
        
        else:
            print("ExpenseAI: Sorry, I didn't understand that. Please enter 'expense' or 'query'.")


if __name__ == "__main__":
   main()