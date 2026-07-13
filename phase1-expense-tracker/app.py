import streamlit as st
import pandas as pd

from tracker.extractor import extract_expense
from tracker.storage import save_expense, load_expenses
from tracker.llm_query import answer_query, summarizer
from tracker.expense_editor import expense_editor

st.set_page_config(page_title="ExpenseAI", layout="wide")

st.title("💸 ExpenseAI")

# Sidebar navigation
mode = st.sidebar.radio(
    "Choose Mode",
    ["Add Expense", "Query", "Summary"]
)

# Load data
expenses = load_expenses()

# -----------------------------
# 🧾 ADD EXPENSE
# -----------------------------
if mode == "Add Expense":
    st.header("Add Expense")

    user_input = st.text_input("Enter your expense (e.g. coffee 5 at Starbucks yesterday)")

    if "parsed_expense" not in st.session_state:
        st.session_state.parsed_expense = None

    if st.button("Parse Expense"):
        try:
            expense = extract_expense(user_input)

            # Validation (same as CLI)
            if expense["amount"] <= 0:
                raise ValueError("Invalid amount")
            if not expense["merchant"]:
                raise ValueError("Missing merchant")

            st.session_state.parsed_expense = expense

        except Exception as e:
            st.error("⚠️ Couldn't understand that expense. Try rephrasing.")
            st.caption(f"Debug: {e}")

    # Show parsed result + edit
    if st.session_state.parsed_expense:
        st.subheader("Detected Expense")

        exp = st.session_state.parsed_expense

        col1, col2 = st.columns(2)

        with col1:
            amount = st.number_input("Amount", value=float(exp["amount"]))
            merchant = st.text_input("Merchant", value=exp["merchant"])

        with col2:
            category = st.text_input("Category", value=exp["category"])
            date = st.text_input("Date", value=str(exp["date"]))

        updated_expense = {
            "amount": amount,
            "merchant": merchant,
            "category": category,
            "date": None if date in ["None", ""] else date
        }

        col_save, col_cancel = st.columns(2)

        if col_save.button("✅ Save Expense"):
            save_expense(updated_expense)
            st.success("Expense saved successfully")
            st.session_state.parsed_expense = None

        if col_cancel.button("❌ Cancel"):
            st.session_state.parsed_expense = None


# -----------------------------
# 🔍 QUERY MODE (CHAT)
# -----------------------------
elif mode == "Query":
    st.header("Ask about your expenses")

    if not expenses:
        st.warning("📭 No expenses found yet.")
    else:
        if "history" not in st.session_state:
            st.session_state.history = []

        question = st.text_input("Your question")

        if st.button("Ask"):
            answer = answer_query(question, expenses, st.session_state.history)

        st.divider()

        # Chat display
        for msg in st.session_state.history:
            if msg["role"] == "user":
                st.markdown(f"**🧑 You:** {msg['content']}")
            else:
                st.markdown(f"**🤖 AI:** {msg['content']}")


# -----------------------------
# 📊 SUMMARY DASHBOARD
# -----------------------------
elif mode == "Summary":
    st.header("Expense Summary")

    if not expenses:
        st.info("📭 No expenses yet.")
    else:
        df = pd.DataFrame(expenses)

        # ---- Metrics ----
        total = df["amount"].sum()

        category_totals = df.groupby("category")["amount"].sum()
        top_category = category_totals.idxmax()
        top_category_value = category_totals.max()

        biggest_row = df.loc[df["amount"].idxmax()]
        biggest_merchant = biggest_row["merchant"]
        biggest_amount = biggest_row["amount"]

        most_freq_merchant = df["merchant"].value_counts().idxmax()
        most_freq_count = df["merchant"].value_counts().max()

        st.subheader("📊 Insights")

        col1, col2, col3, col4 = st.columns(4)

        col1.metric("💰 Total Spent", f"€{total:.2f}")
        col2.metric("🏆 Top Category", top_category, f"€{top_category_value:.2f}")
        col3.metric("🔥 Biggest Expense", biggest_merchant, f"€{biggest_amount:.2f}")
        col4.metric("🏪 Frequent Merchant", most_freq_merchant, f"{most_freq_count}x")

        st.divider()

        # ---- Chart ----
        st.subheader("📈 Spending by Category")
        st.bar_chart(category_totals)

        st.divider()

        # ---- AI Insights ----
        st.subheader("🤖 AI Insights")
        ai_summary = summarizer(expenses)
        st.write(ai_summary)


