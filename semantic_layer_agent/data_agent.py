"""The Voltway data agent: answers questions about the fleet data by combining four MCP servers.

    DataHub   catalogue: what data exists, what it means, which columns are personal data
    Cube      semantic layer: governed metrics (fleet size, kWh/100 km, cost per kWh, ...)
    DuckDB    query & compute: SQL across the Postgres tables and the energy_prices file
    Postgres  the source database: exact schemas, EXPLAIN, read-only SQL

Text-to-SQL is done by the model following the workflow in SYSTEM_PROMPT, with middleware (middleware/) around it:
a router picks the starting layer for each question (Cube or DataHub, see middleware/routing.py), temporary model
and MCP failures are retried (and the model can fall back to FALLBACK_MODEL), email addresses are redacted, SQL must
be a single read-only statement, tool errors go back to the model so it can fix its query, and every run has a step
limit. Every run is traced to LangSmith when LANGSMITH_TRACING=true (to the destination set in the repo-root .env).

Conversations (thread_id) are saved by a LangGraph checkpointer, chosen with CHECKPOINTER:
    postgres (default)  the agent_state database in the stack's Postgres: survives restarts
    memory              in this process only: for tests, evals, or running without the database
"""

import asyncio
import json
import logging
import os
import sys
from contextlib import AsyncExitStack
from pathlib import Path

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain.agents.middleware import ModelCallLimitMiddleware, ToolCallLimitMiddleware
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver

from middleware import (ReadOnlySqlGuard, RouteDecision, RouteToLayer, ToolErrorsToModel, email_masking,
                        model_fallback, model_retry, redact, tool_retry)

HERE = Path(__file__).resolve().parent
load_dotenv(HERE / ".env")         # this project: stack passwords and ports
load_dotenv(HERE.parent / ".env")  # repo root: OPENAI_API_KEY / OPENAI_BASE_URL (LiteLLM)
for noisy in ("httpx", "mcp", "langchain_mcp_adapters"):
    logging.getLogger(noisy).setLevel(logging.WARNING)

AGENT_MODEL = os.getenv("AGENT_MODEL", "gpt-5.4")  # a model name registered in your LiteLLM gateway, or an OpenAI model
ROUTER_MODEL = os.getenv("ROUTER_MODEL", "gpt-4o-mini")  # small, fast model that picks Cube or DataHub per question
FALLBACK_MODEL = os.getenv("FALLBACK_MODEL", "")  # used if AGENT_MODEL keeps failing; empty = no fallback
CHECKPOINTER = os.getenv("CHECKPOINTER", "postgres")  # postgres | memory


def agent_state_url() -> str:
    """Where conversations are saved: the agent_state database, owned by the agent_app role (see
    docker/postgres/init/04_agent_state.sh). It's separate from the fleet data, which the agent can only read."""
    return os.getenv("AGENT_STATE_DB_URL") or (
        f"postgresql://agent_app:{os.getenv('AGENT_DB_PASSWORD', 'agent')}"
        f"@localhost:{os.getenv('POSTGRES_PORT', '5432')}/agent_state")


def mcp_connections() -> dict:
    """The four MCP servers. MCP_SERVERS (comma-separated) picks a subset, e.g. while DataHub is down."""
    connections = {
        "datahub": {
            "transport": "stdio",
            "command": "uvx",
            "args": ["mcp-server-datahub@0.8.0"],
            "env": {**os.environ, "DATAHUB_GMS_URL": os.getenv("DATAHUB_GMS_URL", "http://localhost:8080"),
                    "DATAHUB_GMS_TOKEN": os.getenv("DATAHUB_GMS_TOKEN", "")},
        },
        "cube": {
            "transport": "stdio",
            "command": sys.executable,
            "args": [str(HERE / "mcp_servers" / "cube_mcp_server.py")],
            "env": {**os.environ},
        },
        "duckdb": {
            "transport": "streamable_http",
            "url": f"http://localhost:{os.getenv('DUCKDB_MCP_PORT', '8001')}/mcp",
        },
        "postgres": {
            "transport": "streamable_http",
            "url": f"http://localhost:{os.getenv('POSTGRES_MCP_PORT', '8002')}/mcp",
        },
    }
    wanted = [s.strip() for s in os.getenv("MCP_SERVERS", ",".join(connections)).split(",") if s.strip()]
    return {name: connections[name] for name in wanted}


SYSTEM_PROMPT = """You are Voltway's data analyst. You answer questions about the company's electric sales fleet
in Portugal (vehicles, drivers, depots, trips, charging, maintenance, electricity prices) using real data.

Your tools:
- DataHub catalogue (search, get_entities, list_schema_fields, get_lineage, ...): what data exists and what it
  means: table and column descriptions, glossary terms (business definitions), tags such as `pii`.
- Cube semantic layer (cube_meta, cube_query, cube_sql): governed metrics with agreed definitions.
- DuckDB (execute_query, list_tables, list_columns): SQL engine for answers. The Postgres tables are attached as
  `voltway.fleet.<table>`; the daily electricity tariff and grid CO2 file is `files.energy_prices`.
  Use DuckDB SQL syntax.
- Postgres (postgres_list_tables, postgres_describe_table, postgres_execute_sql, postgres_explain_query): the
  source database (schema `fleet`, Postgres syntax).
  Use it to check exact column types and constraints. Prefer DuckDB for answering questions.

A routing step has already decided where you start for each question (Cube for metrics, DataHub for everything
else); when it applies, its note is at the end of these instructions and your first tools are limited to that layer.

How to answer a data question:
1. If the question asks for a business metric (fleet size, energy efficiency / kWh per 100 km, charging cost per
   kWh, public charging share, downtime, maintenance cost, distance, trip or session counts), call cube_meta and
   answer with cube_query when the semantic layer covers it. Its definitions are the official ones.
2. Otherwise, or when the metric isn't in Cube (e.g. combining tables Cube doesn't join, or the energy_prices file),
   find the right tables in DataHub (search, then get_entities / list_schema_fields) and read their descriptions,
   join keys and glossary terms. Check exact column names with DuckDB list_columns before writing SQL.
3. Write one read-only SELECT (WITH is fine) in DuckDB syntax, fully qualified (voltway.fleet.trips). Aggregate in
   SQL rather than fetching raw rows. Ratios like kWh/100 km are SUM/SUM, not AVG of per-row ratios.
4. Run it with DuckDB execute_query. If it fails, read the error, fix the SQL and try again (at most 3 attempts).
5. Sanity-check the result (units, row counts, plausible ranges) before answering.

Rules:
- Never invent numbers: every figure in your answer must come from a tool result in this conversation.
- Columns tagged `pii` (driver names, emails) are personal data: aggregate by depot or region instead, and only
  show names if the user explicitly asks for individual drivers. Never show email addresses.
- You can only read data. If asked to change data, explain that you have read-only access.
- If the question is ambiguous (which period? which depot?), state the assumption you made.

Answer format: a short direct answer first (with units and the period covered), then a small table if useful,
then "How I got this": the Cube query or SQL you ran, and which tables or metrics it used."""


class McpSessions:
    """Keeps one session per MCP server open for the agent's lifetime (instead of a new session, and for the
    stdio servers a new process, on every tool call). The stdio transport must be opened and closed by the
    same asyncio task, so a background task owns the sessions until stop()."""

    def __init__(self, connections: dict):
        self.connections = connections
        self.tools = []
        self.server_of = {}  # tool name -> MCP server name
        self._ready = asyncio.Event()
        self._stop = asyncio.Event()
        self._task = None

    async def _run(self):
        client = MultiServerMCPClient(self.connections)
        async with AsyncExitStack() as stack:
            for name in self.connections:
                session = await stack.enter_async_context(client.session(name))
                server_tools = await load_mcp_tools(session, server_name=name)
                self.tools += server_tools
                self.server_of.update({tool.name: name for tool in server_tools})
            self._ready.set()
            await self._stop.wait()

    async def start(self) -> list:
        self._task = asyncio.create_task(self._run())
        ready = asyncio.create_task(self._ready.wait())
        await asyncio.wait([ready, self._task], return_when=asyncio.FIRST_COMPLETED)
        ready.cancel()
        if self._task.done():
            self._task.result()  # a server failed to start: raise its real error
        return self.tools

    async def stop(self):
        self._stop.set()
        if self._task:
            await asyncio.gather(self._task, return_exceptions=True)


class DataAgent:
    """Owns the MCP sessions and the agent. Use `async with DataAgent() as agent:` or start()/stop()."""

    def __init__(self, model=None, router=None, checkpointer: str | BaseCheckpointSaver | None = None):
        """checkpointer: "postgres", "memory", a ready LangGraph checkpointer, or None for CHECKPOINTER."""
        # Retries are done by model_retry (visible in traces), so the client's own retries are turned off.
        self.model = model or ChatOpenAI(model=AGENT_MODEL, max_retries=0)
        self.router = router  # default: ROUTER_MODEL with structured output, created in start()
        self.checkpointer = checkpointer or CHECKPOINTER
        self.sessions = McpSessions(mcp_connections())
        self.tools = []
        self.agent = None
        self.metrics_overview = ""
        self._pool = None  # Postgres connection pool, when the checkpointer is "postgres"
        self.db_connect_timeout = 10  # seconds to wait for the agent_state database at start

    async def _open_checkpointer(self) -> BaseCheckpointSaver:
        if isinstance(self.checkpointer, BaseCheckpointSaver):
            return self.checkpointer
        if self.checkpointer == "memory":
            return InMemorySaver()
        if self.checkpointer != "postgres":
            raise ValueError(f"CHECKPOINTER must be postgres or memory, not {self.checkpointer!r}")
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        from psycopg.rows import dict_row
        from psycopg_pool import AsyncConnectionPool

        # The settings AsyncPostgresSaver needs: autocommit, no prepared statements, rows as dicts.
        self._pool = AsyncConnectionPool(agent_state_url(), min_size=1, max_size=5, open=False,
                                         kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row})
        try:
            await self._pool.open(wait=True, timeout=self.db_connect_timeout)
        except Exception as error:  # noqa: BLE001
            await self._pool.close()
            self._pool = None
            raise RuntimeError(
                "Couldn't connect to the agent_state database that stores conversations. Run ./scripts/setup.sh "
                "(it creates the database), or set CHECKPOINTER=memory to keep conversations in memory.") from error
        saver = AsyncPostgresSaver(self._pool)
        await saver.setup()  # creates or migrates the checkpoint tables; safe to run every start
        return saver

    async def _load_metrics_overview(self) -> str:
        """The Cube metrics, one per line, for the router. Empty if the Cube server isn't available."""
        cube_meta = next((t for t in self.tools if t.name == "cube_meta"), None)
        if cube_meta is None:
            return ""
        try:
            result = await cube_meta.ainvoke({})
            text = result if isinstance(result, str) else "".join(
                part.get("text", "") if isinstance(part, dict) else str(part) for part in result)
            lines = []
            for cube in json.loads(text)["cubes"]:
                for measure in cube["measures"]:
                    description = " ".join((measure.get("description") or "").split())
                    lines.append(f"- {measure['name']}: {description}" if description else f"- {measure['name']}")
            return "\n".join(lines)
        except Exception:  # noqa: BLE001 - the router still works without the list, just less precisely
            return ""

    async def start(self):
        checkpointer = await self._open_checkpointer()  # first: fails fast if the database isn't there
        self.tools = await self.sessions.start()
        self.metrics_overview = await self._load_metrics_overview()
        router = self.router or ChatOpenAI(model=ROUTER_MODEL, temperature=0).with_structured_output(RouteDecision)
        fallbacks = [ChatOpenAI(model=FALLBACK_MODEL, max_retries=0)] if FALLBACK_MODEL else []
        self.agent = create_agent(
            self.model,
            tools=self.tools,
            system_prompt=SYSTEM_PROMPT,
            # Outermost first: for a model call, routing -> fallback -> retry -> email masking -> the model;
            # for a tool call, SQL guard -> errors to the model -> retry -> the MCP tool.
            middleware=[
                RouteToLayer(router, self.metrics_overview, self.sessions.server_of),
                *model_fallback(*fallbacks),
                model_retry(),
                email_masking(),
                ReadOnlySqlGuard(),
                ToolErrorsToModel(),
                tool_retry(),
                ModelCallLimitMiddleware(run_limit=25),
                ToolCallLimitMiddleware(run_limit=40),
            ],
            checkpointer=checkpointer,  # remembers each conversation (thread_id) for follow-up questions
            name="voltway_data_agent",
        )
        return self

    async def stop(self):
        await self.sessions.stop()
        if self._pool is not None:
            await self._pool.close()

    async def __aenter__(self):
        return await self.start()

    async def __aexit__(self, *exc):
        await self.stop()

    @staticmethod
    def _config(thread_id: str, tags: list[str] | None = None, metadata: dict | None = None) -> dict:
        """Run config: the conversation thread, plus the name, tags and metadata each LangSmith trace gets."""
        return {
            "configurable": {"thread_id": thread_id},
            "run_name": "voltway_data_agent",
            "tags": ["voltway", f"model:{AGENT_MODEL}", *(tags or [])],
            "metadata": {"thread_id": thread_id, "agent_model": AGENT_MODEL, "router_model": ROUTER_MODEL,
                         **(metadata or {})},
        }

    async def ask(self, question: str, thread_id: str = "default") -> str:
        """Ask a question and return the final answer."""
        result = await self.agent.ainvoke({"messages": [{"role": "user", "content": question}]}, self._config(thread_id))
        return result["messages"][-1].text

    async def run(self, question: str, thread_id: str = "default", tags: list[str] | None = None,
                  metadata: dict | None = None) -> dict:
        """Ask a question and return everything that happened: answer, route, tool calls (with their MCP server),
        SQL sent, and tool errors. Used by the evaluations."""
        out = {"answer": "", "route": None, "route_reason": None, "tool_calls": [], "sql": [], "tool_errors": []}
        async for event in self.stream(question, thread_id, tags=tags, metadata=metadata):
            if event[0] == "route":
                out["route"], out["route_reason"] = event[1], event[2]
            elif event[0] == "tool_call":
                _, name, args, _ = event
                out["tool_calls"].append({"name": name, "server": self.sessions.server_of.get(name), "args": args})
                if isinstance(args.get("sql"), str):
                    out["sql"].append(args["sql"])
            elif event[0] == "tool_result" and event[3]:
                out["tool_errors"].append({"name": event[1], "error": event[2][:500]})
            elif event[0] == "answer":
                out["answer"] = event[1]
        return out

    async def stream(self, question: str, thread_id: str = "default", tags: list[str] | None = None,
                     metadata: dict | None = None):
        """Yield ("route", route, reason), ("tool_call", name, args, call_id),
        ("tool_result", name, text, is_error, call_id) and, at the end, ("answer", text) as the agent works.
        Tool results and the answer are email-redacted, like what the model sees and what's saved."""
        config = self._config(thread_id, tags, metadata)
        answer = None
        async for update in self.agent.astream({"messages": [{"role": "user", "content": question}]}, config,
                                               stream_mode="updates"):
            for node, values in update.items():
                if not isinstance(values, dict):
                    continue
                if values.get("route"):
                    yield ("route", values["route"], values.get("route_reason", ""))
                # Only the model and tools steps add messages. Middleware steps (e.g. email masking) send the
                # whole, rewritten message list again: reading those would repeat every step.
                if node not in ("model", "tools"):
                    continue
                for message in values.get("messages", []):
                    if message.type == "ai" and message.tool_calls:
                        for call in message.tool_calls:
                            yield ("tool_call", call["name"], call["args"], call["id"])
                    elif message.type == "tool":
                        yield ("tool_result", message.name, redact(message.text),
                               getattr(message, "status", "") == "error", message.tool_call_id)
                    elif message.type == "ai" and message.text:
                        answer = redact(message.text)  # the last one is the final answer
        if answer:
            yield ("answer", answer)


async def main():
    question = " ".join(sys.argv[1:]) or "Which vehicle model is the most energy efficient, in kWh per 100 km?"
    async with DataAgent() as agent:
        print(f"Tools: {', '.join(sorted(t.name for t in agent.tools))}\n")
        print(await agent.ask(question))


if __name__ == "__main__":
    asyncio.run(main())
