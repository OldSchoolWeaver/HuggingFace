"""ToolErrorsToModel: turns a tool exception into an error message the model can read and recover from."""

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage


class ToolErrorsToModel(AgentMiddleware):
    """A failing tool call (bad SQL, unknown Cube member, a server hiccup) goes back to the model as an
    error message it can learn from, instead of crashing the run."""

    async def awrap_tool_call(self, request, handler):
        try:
            return await handler(request)
        except Exception as error:  # noqa: BLE001
            message = str(error).strip() or type(error).__name__
            return ToolMessage(content=f"Tool error: {message[:2000]}", tool_call_id=request.tool_call["id"],
                               name=request.tool_call["name"], status="error")
