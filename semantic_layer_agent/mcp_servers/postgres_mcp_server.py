"""Read-only MCP server for the Voltway Postgres database.

Tools: postgres_list_tables, postgres_describe_table, postgres_execute_sql, postgres_explain_query
(prefixed so they don't clash with the DuckDB server's list_tables). Every query runs in a READ ONLY transaction
with a timeout, as the read-only `analyst` role, and returns at most MAX_ROWS rows.

Runs in Docker over streamable HTTP (docker/postgres-mcp/Dockerfile), or locally over stdio:
    DATABASE_URI=postgresql://analyst:analyst@localhost:5432/voltway python mcp_servers/postgres_mcp_server.py --stdio
"""

import json
import os
import sys
from datetime import date, datetime
from decimal import Decimal

import psycopg
from mcp.server.fastmcp import FastMCP

DATABASE_URI = os.getenv("DATABASE_URI", "postgresql://analyst:analyst@localhost:5432/voltway")
MAX_ROWS = int(os.getenv("MAX_ROWS", "500"))
TIMEOUT_MS = int(os.getenv("STATEMENT_TIMEOUT_MS", "30000"))

mcp = FastMCP("postgres", host=os.getenv("HOST", "0.0.0.0"), port=int(os.getenv("PORT", "8000")), log_level="WARNING")


def _json(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)


def _run(sql: str, params: tuple | None = None) -> tuple[list[str], list[tuple], bool]:
    """Run one statement in a read-only transaction; return (columns, rows, truncated)."""
    with psycopg.connect(DATABASE_URI, autocommit=False) as conn:
        conn.execute("SET TRANSACTION READ ONLY")
        conn.execute(f"SET LOCAL statement_timeout = {TIMEOUT_MS}")
        cur = conn.execute(sql, params)
        columns = [c.name for c in cur.description or []]
        rows = cur.fetchmany(MAX_ROWS + 1) if cur.description else []
        conn.rollback()
    return columns, rows[:MAX_ROWS], len(rows) > MAX_ROWS


@mcp.tool()
def postgres_list_tables(schema: str = "fleet") -> str:
    """List the tables and views in a schema with their descriptions and approximate row counts."""
    columns, rows, _ = _run(
        """SELECT c.relname AS table, CASE c.relkind WHEN 'v' THEN 'view' ELSE 'table' END AS type,
                  c.reltuples::bigint AS approx_rows, obj_description(c.oid) AS description
           FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
           WHERE n.nspname = %s AND c.relkind IN ('r', 'v', 'p') ORDER BY 1""", (schema,))
    return json.dumps([dict(zip(columns, r)) for r in rows], indent=1, default=_json)


@mcp.tool()
def postgres_describe_table(table: str, schema: str = "fleet") -> str:
    """Columns of a table (name, type, nullable, description), its primary key and foreign keys."""
    cols, rows, _ = _run(
        """SELECT a.attname AS column, format_type(a.atttypid, a.atttypmod) AS type, NOT a.attnotnull AS nullable,
                  col_description(a.attrelid, a.attnum) AS description
           FROM pg_attribute a
           WHERE a.attrelid = to_regclass(format('%%I.%%I', %s::text, %s::text)) AND a.attnum > 0 AND NOT a.attisdropped
           ORDER BY a.attnum""", (schema, table))
    if not rows:
        raise ValueError(f"Table {schema}.{table} not found. Use postgres_list_tables to see the tables.")
    _, keys, _ = _run(
        """SELECT contype, pg_get_constraintdef(oid) FROM pg_constraint
           WHERE conrelid = to_regclass(format('%%I.%%I', %s::text, %s::text)) AND contype IN ('p', 'f', 'u', 'c')""",
        (schema, table))
    return json.dumps({
        "table": f"{schema}.{table}",
        "columns": [dict(zip(cols, r)) for r in rows],
        "constraints": [{"type": {"p": "primary key", "f": "foreign key", "u": "unique", "c": "check"}[t], "definition": d}
                        for t, d in keys],
    }, indent=1, default=_json)


@mcp.tool()
def postgres_execute_sql(sql: str) -> str:
    """Run one read-only SQL query (Postgres syntax, tables as fleet.<table>) and return the rows as JSON,
    at most 500 rows. Aggregate in SQL instead of fetching raw rows."""
    columns, rows, truncated = _run(sql)
    return json.dumps({"columns": columns, "rows": [list(r) for r in rows], "row_count": len(rows),
                       "truncated": truncated}, default=_json)


@mcp.tool()
def postgres_explain_query(sql: str) -> str:
    """Show the Postgres query plan for a SELECT without running it (EXPLAIN)."""
    _, rows, _ = _run(f"EXPLAIN {sql}")
    return "\n".join(r[0] for r in rows)


if __name__ == "__main__":
    mcp.run(transport="stdio" if "--stdio" in sys.argv else "streamable-http")
