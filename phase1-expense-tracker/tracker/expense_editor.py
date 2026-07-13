
def expense_editor(expense: dict) -> dict:
    print("ExpenseAI: Here is the generated expense:")
    for key, value in expense.items():
        print(f"{key}: {value}")
    
    while True:
        user_input = input("ExpenseAI: Which field do you want to edit? (e.g., amount, category, merchant) Or type 'done' to finish editing: ")
        if user_input.lower() == 'amount':
            new_amount = input("ExpenseAI: Enter the new amount: ")
            try:
                expense["amount"] = float(new_amount)
                print("ExpenseAI: Amount updated.")
            except ValueError:
                print("ExpenseAI: Invalid amount. Please enter a numeric value.")
        elif user_input.lower() == 'category':
            new_category = input("ExpenseAI: Enter the new category: ")
            expense["category"] = new_category
            print("ExpenseAI: Category updated.")
        elif user_input.lower() == 'merchant':
            new_merchant = input("ExpenseAI: Enter the new merchant: ")
            expense["merchant"] = new_merchant
            print("ExpenseAI: Merchant updated.")
        elif user_input.lower() == 'done':
            print("ExpenseAI: Finished editing.")
            break
        else:
            print("ExpenseAI: Invalid field. Please enter 'amount', 'category', or 'merchant'.")
    return expense