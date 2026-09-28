"""Data Analyst MCP server — Week 1, Step 2.

Run in the Inspector:  .venv/bin/mcp dev server.py
"""

import sqlite3
from pathlib import Path

from mcp.server import MCPServer

DB_PATH = Path(__file__).parent / "data" / "chinook.db"
MAX_ROWS = 100  # tune this once you've seen what a real result looks like

mcp = MCPServer("data-analyst")

def connect() -> sqlite3.Connection:
    return sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)


@mcp.tool()
def list_tables() -> str:
    """List every table in the database with its row count."""

    out_str = "The following is the list of tables and their corresponding row counts:\n"
    conn = connect()
    query = "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';"
    cursor = conn.cursor()
    rows = cursor.execute(query).fetchall()
    if not rows:
        conn.close()
        return "No tables found in the database."
    for row in rows:
        table_name = row[0]
        count_query = f'SELECT COUNT(*) FROM "{table_name}";'
        count = cursor.execute(count_query).fetchone()[0]
        out_str += f"{table_name}: {count} rows\n"
    conn.close()
    return out_str.strip()


@mcp.tool()
def get_schema(table: str) -> str:
    """Return the CREATE TABLE statement for one table, including its foreign keys."""

    out_str = f"The following is the schema create query for the table : {table} \n"
    conn = connect()
    query = "SELECT sql FROM sqlite_master WHERE type='table' AND name=?;"
    cursor = conn.cursor()
    try:
        row = cursor.execute(query, (table,)).fetchone()
    except sqlite3.Error as e:
        conn.close()
        return f"An error occurred while retrieving the schema: {e}"
    if not row:
        conn.close()
        return "The specified table does not exist in the database. Check the table name using the list_tables() tool."
    out_str += f"{row[0]}\n"
    conn.close()
    return out_str.strip()


@mcp.tool(description= f"""Run a read-only SQL query against the Chinook database and return the rows.
    It can only-run queries to retrieve data, and will return at most {MAX_ROWS} rows. 
    If the query returns more than 100 rows, only the first 100 will be returned, and a note will be added to the output indicating that the result was truncated.
    If an error occurs while executing the query, an error message will be returned instead of the rows.
    """)
def run_query(sql: str) -> str:
    conn = connect()
    cursor = conn.cursor()
    try:
        cursor.execute(sql)
        # description is only populated after execute(), and is None for statements
        # that return no result set at all.
        columns = [d[0] for d in cursor.description] if cursor.description else []
        rows = cursor.fetchmany(MAX_ROWS + 1)
        if not rows:
            return f"The query returned no rows. Columns would have been: {' | '.join(columns)}"

        truncated = len(rows) > MAX_ROWS
        rows = rows[:MAX_ROWS]

        lines = [" | ".join(columns)]
        lines += [" | ".join("NULL" if v is None else str(v) for v in row) for row in rows]
        result_str = "\n".join(lines)

        if truncated:
            result_str += (
                f"\n\nNote: truncated to the first {MAX_ROWS} rows; more rows matched. "
                "Any total, max or ranking computed from this is incomplete - "
                "re-run with an aggregate or a LIMIT instead."
            )
        return result_str
    except sqlite3.Error as e:
        return f"An error occurred while executing the query: {e}"
    finally:
        conn.close()

if __name__ == "__main__":
    mcp.run()
