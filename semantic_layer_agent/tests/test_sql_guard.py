"""ReadOnlySqlGuard: which SQL gets through, and what the model sees when it doesn't."""

import asyncio

import pytest
from langchain_core.messages import ToolMessage

from middleware import ReadOnlySqlGuard

guard = ReadOnlySqlGuard()

ALLOWED = [
    "SELECT count(*) FROM fleet.vehicles",
    "select model, avg(battery_kwh) from fleet.vehicles group by model",
    "WITH t AS (SELECT * FROM fleet.trips) SELECT count(*) FROM t",
    "SELECT * FROM fleet.trips t JOIN files.energy_prices p ON p.day = t.started_at::date LIMIT 5",
    "SELECT 1 UNION ALL SELECT 2",
    "DESCRIBE fleet.vehicles",
    "SHOW TABLES",
    "SUMMARIZE fleet.trips",
    "SELECT 1;",  # a trailing semicolon is still one statement
]

REJECTED = [
    ("DELETE FROM fleet.trips", "read-only"),
    ("UPDATE fleet.vehicles SET status = 'retired'", "read-only"),
    ("INSERT INTO fleet.depots VALUES (99, 'x')", "read-only"),
    ("DROP TABLE fleet.trips", "read-only"),
    ("CREATE TABLE x AS SELECT 1", "read-only"),
    ("SELECT 1; DELETE FROM fleet.trips", "exactly one"),
    ("SELECT 1; SELECT 2", "exactly one"),
    ("WITH d AS (DELETE FROM fleet.trips RETURNING *) SELECT * FROM d", "read-only"),
    ("SELEC count(*) FROM fleet.vehicles", ""),  # not valid SQL: rejected one way or another
    # DuckDB statements that aren't writes to tables but change state or touch files: not allowed either
    ("ATTACH 'other.db'", "read-only"),
    ("COPY fleet.drivers TO 'drivers.csv'", "read-only"),
    ("SET threads = 1", "read-only"),
    ("INSTALL httpfs", "read-only"),
    ("PRAGMA enable_profiling", "read-only"),
    ("SUMMARIZE (DELETE FROM fleet.trips RETURNING *)", ""),
]


@pytest.mark.parametrize("sql", ALLOWED)
def test_allows_read_only_queries(sql):
    assert guard.check(sql, "duckdb") is None


@pytest.mark.parametrize("sql,reason", REJECTED)
def test_rejects_writes_and_multiple_statements(sql, reason):
    problem = guard.check(sql, "duckdb")
    assert problem is not None
    assert reason.lower() in problem.lower()


def test_postgres_dialect():
    assert guard.check("SELECT now() - interval '1 day'", "postgres") is None
    assert guard.check("TRUNCATE fleet.trips", "postgres") is not None


class Request:
    """The only part of a ToolCallRequest the guard reads."""

    def __init__(self, name, args):
        self.tool_call = {"name": name, "args": args, "id": "call_1"}


def run(request):
    calls = []

    async def handler(req):
        calls.append(req)
        return ToolMessage(content="rows", tool_call_id="call_1", name=req.tool_call["name"])

    return asyncio.run(guard.awrap_tool_call(request, handler)), calls


def test_rejected_sql_never_reaches_the_database():
    result, calls = run(Request("execute_query", {"sql": "DELETE FROM fleet.trips"}))
    assert calls == []                                   # the MCP tool was not called
    assert result.status == "error"
    assert result.content.startswith("Query rejected:")  # the model is told why, so it can fix the query
    assert result.tool_call_id == "call_1"


def test_allowed_sql_is_passed_through():
    result, calls = run(Request("postgres_execute_sql", {"sql": "SELECT 1"}))
    assert len(calls) == 1 and result.content == "rows"


def test_non_sql_tools_are_not_checked():
    # cube_sql and DataHub tools are not in SQL_TOOLS: the guard leaves them alone
    result, calls = run(Request("cube_query", {"query": {"measures": ["vehicles.count"]}}))
    assert len(calls) == 1
