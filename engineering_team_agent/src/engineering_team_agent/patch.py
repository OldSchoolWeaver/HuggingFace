"""Monkey-patches for two CrewAI 1.14.x bugs. Importing this module applies them as a side effect.

1. MCP tool names: HTTPS MCP tool names are sanitized on discovery, but the sanitized name is then sent back to
   the server, so any server tool whose name contains hyphens (e.g. Context7's `resolve-library-id`) becomes
   unreachable.
2. Max iterations + Claude: the forced "final answer" request is sent as an assistant turn (prefill), which current
   Claude models reject with a 400 (see the second patch below). Fixed upstream in crewAI 1.15.

Re-verify both on crewai upgrade.
"""
import asyncio
from typing import Any, cast

from crewai.mcp.tool_resolver import MCPToolResolver
from crewai.tools.base_tool import BaseTool
from crewai.tools.mcp_tool_wrapper import MCPToolWrapper
from crewai.utilities.string_utils import sanitize_tool_name


def _resolve_external(self, mcp_ref: str) -> list[BaseTool]:
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    if "#" in mcp_ref:
        server_url, specific_tool = mcp_ref.split("#", 1)
    else:
        server_url, specific_tool = mcp_ref, None

    server_params = {"url": server_url}
    server_name = self._extract_server_name(server_url)
    sanitized_specific = sanitize_tool_name(specific_tool) if specific_tool else None

    async def _list_mcp_tools() -> list[Any]:
        async with streamablehttp_client(server_url) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return list((await session.list_tools()).tools)

    try:
        mcp_tools = asyncio.run(_list_mcp_tools())
    except Exception as e:
        self._logger.log("warning", f"Failed to connect to MCP server {server_url}: {e}")
        return []

    tools: list[BaseTool] = []
    for mcp_tool in mcp_tools:
        sanitized = sanitize_tool_name(mcp_tool.name)
        if sanitized_specific and sanitized != sanitized_specific:
            continue
        args_schema = None
        if getattr(mcp_tool, "inputSchema", None):
            args_schema = self._json_schema_to_pydantic(sanitized, mcp_tool.inputSchema)
        schema = {
            "description": getattr(mcp_tool, "description", ""),
            "args_schema": args_schema,
        }
        try:
            wrapper = MCPToolWrapper(
                mcp_server_params=server_params,
                tool_name=sanitized,
                tool_schema=schema,
                server_name=server_name,
            )
            # Preserve the unsanitized server-side name so call_tool reaches the real tool.
            wrapper._original_tool_name = mcp_tool.name
            tools.append(wrapper)
        except Exception as e:
            self._logger.log("warning", f"Failed to create MCP tool wrapper for {sanitized}: {e}")

    return cast(list[BaseTool], tools)


MCPToolResolver._resolve_external = _resolve_external

# ---------------------------------------------------------------------------------------------------------------------
# Patch 2: final answer after max_iter is requested as a USER turn (fixed upstream in crewAI 1.15).
#
# When an agent runs out of steps, crewAI 1.14.x appends "give your final answer now" as an *assistant* message and
# calls the model again. A conversation that ends with an assistant turn is a "prefill" request, which current Claude
# models reject: 400 "This model does not support assistant message prefill. The conversation must end with a user
# message." - and crewAI then retries the whole task twice. Every provider accepts a trailing user turn.
# Re-verify (or delete this patch) on crewai upgrade.
# ---------------------------------------------------------------------------------------------------------------------
from crewai.agents import crew_agent_executor as _crew_agent_executor  # noqa: E402
from crewai import lite_agent as _lite_agent  # noqa: E402
from crewai.agents.parser import AgentFinish  # noqa: E402
from crewai.utilities import agent_utils as _agent_utils  # noqa: E402


def _handle_max_iterations_exceeded(formatted_answer, printer, messages, llm, callbacks, verbose=True) -> AgentFinish:
    if verbose:
        printer.print(content="Maximum iterations reached. Requesting final answer.", color="yellow")

    messages.append(
        _agent_utils.format_message_for_llm(_agent_utils.I18N_DEFAULT.errors("force_final_answer"), role="user")
    )
    answer = llm.call(messages, callbacks=callbacks)
    if answer is None or answer == "":
        if verbose:
            printer.print(content="Received None or empty response from LLM call.", color="red")
        raise ValueError("Invalid response from LLM call - None or empty.")

    formatted = _agent_utils.format_answer(answer=answer)
    if isinstance(formatted, AgentFinish):
        return formatted
    return AgentFinish(thought=formatted.thought, output=formatted.text, text=formatted.text)


# The executors import the function by name, so replace it where it is used, not only where it is defined.
for _module in (_agent_utils, _crew_agent_executor, _lite_agent):
    _module.handle_max_iterations_exceeded = _handle_max_iterations_exceeded
