"""The production harness: email masking, retries, fallback and the checkpointer choice.

The Postgres test runs only when TEST_AGENT_STATE_DB_URL points at an agent_state database, e.g.
  TEST_AGENT_STATE_DB_URL=postgresql://agent_app:agent@localhost:5433/agent_state uv run pytest tests
"""

import asyncio
import os
import uuid

import httpx
import openai
import pytest
from langchain.agents import create_agent
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import ToolException, tool
from langgraph.checkpoint.memory import InMemorySaver

import data_agent
from middleware import ToolErrorsToModel, email_masking, model_fallback, model_retry, redact, tool_retry

EMAIL = "ana.silva@voltway.pt"


# ---------------------------------------------------------------- email masking

def test_redact():
    assert redact(f"Write to {EMAIL} or rui.m+fleet@mail.example.com.") == \
        "Write to [REDACTED_EMAIL] or [REDACTED_EMAIL]."
    assert redact("No personal data: 37 vehicles, v2.1") == "No personal data: 37 vehicles, v2.1"


@tool
def lookup_driver(name: str) -> str:
    """Look up a driver."""
    return f"Ana Silva, {EMAIL}, Porto"


class ScriptedModel(GenericFakeChatModel):
    """Calls lookup_driver first, then answers with the email it was given. Records what it saw."""

    seen: list = []

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.seen.append(messages[-1].content)
        if messages[-1].type == "human":
            message = AIMessage("", tool_calls=[{"name": "lookup_driver", "args": {"name": "Ana"}, "id": "t1"}])
        else:
            message = AIMessage(f"Her email is {EMAIL}.")
        return ChatResult(generations=[ChatGeneration(message=message)])


def test_model_never_sees_emails_and_none_are_saved():
    model = ScriptedModel(messages=iter([]), seen=[])
    agent = create_agent(model, tools=[lookup_driver], middleware=[email_masking()], checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "t"}}
    result = asyncio.run(agent.ainvoke({"messages": [("user", "Ana's email?")]}, config))
    assert model.seen[-1] == "Ana Silva, [REDACTED_EMAIL], Porto"          # the tool result, as the model read it
    assert result["messages"][-1].content == "Her email is [REDACTED_EMAIL]."
    saved = asyncio.run(agent.aget_state(config)).values["messages"]
    assert not any(EMAIL in str(m.content) for m in saved)


def test_stream_redacts_and_shows_each_step_once(monkeypatch):
    """DataAgent.stream (what the app shows): emails redacted, and no step repeated by the masking middleware."""
    monkeypatch.setenv("MCP_SERVERS", "")

    async def run():
        agent = data_agent.DataAgent(model=ScriptedModel(messages=iter([]), seen=[]), router=_Router(),
                                     checkpointer="memory")

        async def fake_sessions():
            agent.sessions.server_of = {"lookup_driver": "postgres"}
            return [lookup_driver]

        agent.sessions.start = fake_sessions
        await agent.start()
        return [event async for event in agent.stream("Ana's email?", thread_id="t")]

    events = asyncio.run(run())
    kinds = [e[0] for e in events]
    assert kinds == ["route", "tool_call", "tool_result", "answer"]
    assert events[2][2] == "Ana Silva, [REDACTED_EMAIL], Porto"
    assert events[3] == ("answer", "Her email is [REDACTED_EMAIL].")


class _Router:
    async def ainvoke(self, messages):
        from middleware import RouteDecision
        return RouteDecision(route="direct", reason="test")


# ---------------------------------------------------------------- retries and fallback

def test_tool_retry_only_on_connection_problems():
    calls = {"flaky": 0, "bad_sql": 0}

    @tool
    def flaky() -> str:
        """Fails once with a dropped connection, then works."""
        calls["flaky"] += 1
        if calls["flaky"] == 1:
            raise httpx.ConnectError("connection reset")
        return "rows"

    @tool
    def bad_sql() -> str:
        """Always fails with a SQL error (a ToolException): retrying wouldn't help."""
        calls["bad_sql"] += 1
        raise ToolException("Parser Error: syntax error at or near SELEC")

    class CallsBoth(GenericFakeChatModel):
        def bind_tools(self, tools, **kwargs):
            return self

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            if messages[-1].type == "human":
                message = AIMessage("", tool_calls=[{"name": "flaky", "args": {}, "id": "a"},
                                                    {"name": "bad_sql", "args": {}, "id": "b"}])
            else:
                message = AIMessage("done")
            return ChatResult(generations=[ChatGeneration(message=message)])

    agent = create_agent(CallsBoth(messages=iter([])), tools=[flaky, bad_sql],
                         middleware=[ToolErrorsToModel(), tool_retry()])
    messages = asyncio.run(agent.ainvoke({"messages": [("user", "go")]}))["messages"]
    results = {m.name: m for m in messages if m.type == "tool"}
    assert calls == {"flaky": 2, "bad_sql": 1}                       # retried once / not retried
    assert results["flaky"].content == "rows"
    assert results["bad_sql"].status == "error" and "syntax error" in results["bad_sql"].content


def connection_error():
    return openai.APIConnectionError(request=httpx.Request("POST", "http://gateway/v1/chat/completions"))


class FailingModel(GenericFakeChatModel):
    """Raises `error` for the first `failures` calls, then answers `reply`."""

    failures: int = 1
    error: Exception | None = None
    reply: str = "ok"
    calls: int = 0

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.calls += 1
        if self.calls <= self.failures:
            raise self.error
        return ChatResult(generations=[ChatGeneration(message=AIMessage(self.reply))])


def test_model_retry_on_transient_error():
    model = FailingModel(messages=iter([]), failures=1, error=connection_error())
    agent = create_agent(model, tools=[], middleware=[model_retry()])
    result = asyncio.run(agent.ainvoke({"messages": [("user", "hi")]}))
    assert model.calls == 2 and result["messages"][-1].content == "ok"


def test_model_retry_skips_permanent_errors():
    model = FailingModel(messages=iter([]), failures=5, error=ValueError("context too long"))
    agent = create_agent(model, tools=[], middleware=[model_retry()])
    with pytest.raises(ValueError):
        asyncio.run(agent.ainvoke({"messages": [("user", "hi")]}))
    assert model.calls == 1


def test_fallback_model_takes_over():
    primary = FailingModel(messages=iter([]), failures=99, error=connection_error())
    backup = FailingModel(messages=iter([]), failures=0, reply="from the fallback model")
    agent = create_agent(primary, tools=[], middleware=[*model_fallback(backup), model_retry(max_retries=0)])
    result = asyncio.run(agent.ainvoke({"messages": [("user", "hi")]}))
    assert result["messages"][-1].content == "from the fallback model"
    assert model_fallback() == []  # no FALLBACK_MODEL: no middleware at all


# ---------------------------------------------------------------- checkpointer choice

def test_memory_checkpointer(monkeypatch):
    monkeypatch.setenv("MCP_SERVERS", "")
    saver = asyncio.run(data_agent.DataAgent(model=object(), checkpointer="memory")._open_checkpointer())
    assert isinstance(saver, InMemorySaver)


def test_unknown_checkpointer(monkeypatch):
    monkeypatch.setenv("MCP_SERVERS", "")
    with pytest.raises(ValueError, match="postgres or memory"):
        asyncio.run(data_agent.DataAgent(model=object(), checkpointer="redis")._open_checkpointer())


def test_missing_database_gives_a_clear_error(monkeypatch):
    monkeypatch.setenv("MCP_SERVERS", "")
    monkeypatch.setenv("AGENT_STATE_DB_URL", "postgresql://agent_app:agent@127.0.0.1:1/agent_state")
    agent = data_agent.DataAgent(model=object(), checkpointer="postgres")
    agent.db_connect_timeout = 1
    with pytest.raises(RuntimeError, match="CHECKPOINTER=memory"):
        asyncio.run(agent._open_checkpointer())


@pytest.mark.skipif(not os.getenv("TEST_AGENT_STATE_DB_URL"), reason="set TEST_AGENT_STATE_DB_URL to run")
def test_conversation_survives_a_restart(monkeypatch):
    """Save a conversation in Postgres, stop the agent, start a new one: the conversation is still there."""
    monkeypatch.setenv("MCP_SERVERS", "")
    monkeypatch.setenv("AGENT_STATE_DB_URL", os.environ["TEST_AGENT_STATE_DB_URL"])
    thread = f"test:{uuid.uuid4()}"

    async def ask_and_count(question):
        agent = data_agent.DataAgent(model=FailingModel(messages=iter([]), failures=0, reply="noted"),
                                     router=_Router(), checkpointer="postgres")
        await agent.start()
        try:
            await agent.ask(question, thread_id=thread)
            state = await agent.agent.aget_state(agent._config(thread))
            return [m.content for m in state.values["messages"]]
        finally:
            await agent.stop()

    first = asyncio.run(ask_and_count("first question"))
    second = asyncio.run(ask_and_count("second question"))  # a new DataAgent: as after a restart
    assert first == ["first question", "noted"]
    assert second == ["first question", "noted", "second question", "noted"]

