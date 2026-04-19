# 💸 AI Expense Tracker (LLM-Powered CLI Assistant)

An intelligent expense tracking application that uses LLMs to extract, structure, and analyze financial data from natural language input.

---

## 🚀 Features

* 🧠 **Natural Language Input**

  * "coffee 5 at Starbucks yesterday"
  * Automatically converted into structured data

* 📊 **Smart Querying**

  * Ask questions like:

    * "How much did I spend on food?"
    * "What are my expenses this month?"

* 🔄 **Conversational Memory**

  * Supports multi-turn queries:

    * "How much on food?"
    * "And transport?"

* ⚡ **Hybrid AI Architecture**

  * Uses LLMs for:

    * extraction
    * intent classification
    * query understanding
  * Uses Python for:

    * filtering
    * aggregation
    * validation

---

## 🏗️ Architecture

User Input
→ Intent Classification (LLM)
→
• Expense → Extraction (LLM) → Validation → Storage
• Query → Query Parsing (LLM) → Filtering (Python) →
  • Simple → Computation (Python)
  • Complex → LLM Answer

---

## 🧠 Key Concepts Demonstrated

* Prompt engineering with structured outputs
* Few-shot learning for reliability
* LLM + deterministic code hybrid systems
* Context injection (RAG-style pattern)
* Multi-turn conversational memory
* Input validation for AI systems

---

## 🛠️ Tech Stack

* Python
* Anthropic Claude API
* dotenv
* JSON-based storage

---

## ▶️ Run Locally

```bash
git clone <your-repo>
cd expense-tracker

python -m venv .venv
source .venv/bin/activate  # or Windows equivalent

pip install -r requirements.txt
```

Create `.env`:

```env
ANTHROPIC_API_KEY=your_key_here
```

Run:

```bash
python cli.py
```

---

## 💬 Example Usage

```
> expense
coffee 4.5 at Starbucks yesterday
✅ Saved

> query
How much did I spend on food?
→ You spent 45.50

And transport?
→ You spent 60.00
```

---

## 📌 Future Improvements

* Web UI (Streamlit)
* Database integration (PostgreSQL / Supabase)
* Data visualization (charts)
* Smarter time parsing (last week, last 3 months)
* Expense categorization tuning

---

## 👤 Author

Your Name
Master’s in Electromechanical Engineering
Interested in AI Systems & Applied LLMs
