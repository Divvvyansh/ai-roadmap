

import json
import sqlite3
from pathlib import Path

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ResourceError
from typing import Annotated
from pydantic import Field


DB_PATH = Path(__file__).parent / "data" / "chinook.db"
MAX_ROWS = 100  # tune this once you've seen what a real result looks like

mcp = MCPServer("data-analyst")

def connect() -> sqlite3.Connection:
    return sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)


def table_counts() -> list[tuple[str, int]]:
    """Every user table with its row count. Shared by the tool and the resource.
    """
    conn = connect()
    try:
        cursor = conn.cursor()
        names = [
            row[0]
            for row in cursor.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name;"
            )
        ]
        return [
            (name, cursor.execute(f'SELECT COUNT(*) FROM "{name}";').fetchone()[0])
            for name in names
        ]
    finally:
        conn.close()


@mcp.tool()
def list_tables() -> str:
    """List every table in the database with its row count."""

    counts = table_counts()
    if not counts:
        return "No tables found in the database."
    lines = ["The following is the list of tables and their corresponding row counts:"]
    lines += [f"{name}: {count} rows" for name, count in counts]
    return "\n".join(lines)


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
def run_query(
    sql: Annotated[str, Field(description="A single read-only SELECT statement.")]
) -> str:
    conn = connect()
    cursor = conn.cursor()
    try:
        cursor.execute(sql)
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


@mcp.resource("db://tables", mime_type="application/json")
def tables_overview() -> str:
    """Every table in the database with its row count, as JSON.
    """
    return json.dumps(
        [{"table": name, "rows": count} for name, count in table_counts()],
        indent=2,
    )

@mcp.resource("schema://{table}", mime_type="text/plain")
def table_schema(table: str) -> str:
    """CREATE statement plus three sample rows for one table.
    """
    conn = connect()
    try:
        cursor = conn.cursor()
        row = cursor.execute(
            "SELECT name, sql FROM sqlite_master "
            "WHERE type='table' AND name = ? COLLATE NOCASE;",
            (table,),
        ).fetchone()
        if row is None:
            raise ResourceError(f"No such table: {table!r}")

        real_name, create_sql = row
        cursor.execute(f'SELECT * FROM "{real_name}" LIMIT 3;')
        columns = [d[0] for d in cursor.description]
        samples = cursor.fetchall()

        out = [create_sql, "", f"Sample rows ({len(samples)}):", " | ".join(columns)]
        out += [
            " | ".join("NULL" if v is None else str(v) for v in sample)
            for sample in samples
        ]
        return "\n".join(out)
    finally:
        conn.close()


if __name__ == "__main__":
    mcp.run()
