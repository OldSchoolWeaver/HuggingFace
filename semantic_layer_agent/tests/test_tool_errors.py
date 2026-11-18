"""ToolErrorsToModel: a failing tool becomes an error message instead of crashing the run."""

import asyncio

from langchain_core.messages import ToolMessage

from middleware import ToolErrorsToModel


class Request:
    tool_call = {"name": "cube_query", "args": {}, "id": "call_7"}


def test_exception_becomes_error_message():
    async def failing(_):
        raise RuntimeError("Unknown member: trips.nope")

    result = asyncio.run(ToolErrorsToModel().awrap_tool_call(Request(), failing))
    assert isinstance(result, ToolMessage)
    assert result.status == "error"
    assert result.content == "Tool error: Unknown member: trips.nope"
    assert (result.tool_call_id, result.name) == ("call_7", "cube_query")


def test_exception_without_message_uses_its_type():
    async def failing(_):
        raise TimeoutError()

    result = asyncio.run(ToolErrorsToModel().awrap_tool_call(Request(), failing))
    assert result.content == "Tool error: TimeoutError"


def test_success_is_unchanged():
    expected = ToolMessage(content="ok", tool_call_id="call_7")

    async def ok(_):
        return expected

    assert asyncio.run(ToolErrorsToModel().awrap_tool_call(Request(), ok)) is expected
