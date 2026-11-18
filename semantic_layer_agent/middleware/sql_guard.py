"""ReadOnlySqlGuard: rejects any SQL that isn't a single read-only statement, before it reaches a database."""

import sqlglot
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage
from sqlglot import exp


class ReadOnlySqlGuard(AgentMiddleware):
    """Checks SQL before it reaches DuckDB or Postgres: exactly one statement, and read-only (SELECT/WITH, plus
    DESCRIBE/SHOW/SUMMARIZE for exploring). Both databases are read-only anyway; this gives the model a clear,
    immediate error to fix instead of a database permission error."""

    SQL_TOOLS = {"execute_query": "duckdb", "postgres_execute_sql": "postgres", "postgres_explain_query": "postgres"}
    # Statement types that only read. sqlglot parses SHOW and SUMMARIZE into their own types in recent versions,
    # and into a generic Command in older ones (handled by READ_ONLY_COMMANDS).
    READ_ONLY_TYPES = tuple(t for t in (exp.Query, exp.Describe, getattr(exp, "Show", None),
                                        getattr(exp, "Summarize", None)) if t is not None)
    READ_ONLY_COMMANDS = ("DESCRIBE", "SHOW", "SUMMARIZE")
    WRITES = (exp.Insert, exp.Update, exp.Delete, exp.Create, exp.Drop, exp.Merge, exp.TruncateTable)

    def check(self, sql: str, dialect: str) -> str | None:
        """Return why the SQL isn't allowed, or None if it's fine."""
        try:
            statements = [s for s in sqlglot.parse(sql, read=dialect) if s is not None]
        except sqlglot.errors.ParseError as error:
            return f"SQL syntax error: {str(error).splitlines()[0]}"
        if len(statements) != 1:
            return f"Send exactly one SQL statement per call (got {len(statements)})."
        statement = statements[0]
        if isinstance(statement, self.READ_ONLY_TYPES):
            if any(isinstance(node, self.WRITES) for node in statement.walk()):  # e.g. a DELETE hidden in a CTE
                return "Only read-only queries are allowed."
            return None
        if isinstance(statement, exp.Command) and statement.this.upper() in self.READ_ONLY_COMMANDS:
            return None
        return f"Only read-only queries are allowed (SELECT/WITH), not {statement.key.upper()}."

    async def awrap_tool_call(self, request, handler):
        call = request.tool_call
        dialect = self.SQL_TOOLS.get(call["name"])
        sql = (call.get("args") or {}).get("sql")
        if dialect and isinstance(sql, str):
            problem = self.check(sql, dialect)
            if problem:
                return ToolMessage(content=f"Query rejected: {problem} Fix the SQL and try again.",
                                   tool_call_id=call["id"], name=call["name"], status="error")
        return await handler(request)
