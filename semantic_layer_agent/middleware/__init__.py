"""Middleware for the Voltway data agent, in the order data_agent.py applies them (outermost first):

    RouteToLayer       routing.py      picks the starting layer (cube / datahub / direct) for each question
    model_fallback     retries.py      switches to FALLBACK_MODEL if the agent model keeps failing (optional)
    model_retry        retries.py      retries model calls that failed for a temporary reason
    email_masking      pii.py          redacts email addresses in tool results and answers
    ReadOnlySqlGuard   sql_guard.py    rejects SQL that isn't a single read-only statement
    ToolErrorsToModel  tool_errors.py  turns tool exceptions into messages the model can recover from
    tool_retry         retries.py      retries tool calls when an MCP server couldn't be reached

The step limits (ModelCallLimitMiddleware, ToolCallLimitMiddleware) come with LangChain.
"""

from .pii import email_masking, redact
from .retries import model_fallback, model_retry, tool_retry
from .routing import RouteDecision, RouteToLayer
from .sql_guard import ReadOnlySqlGuard
from .tool_errors import ToolErrorsToModel

__all__ = ["RouteDecision", "RouteToLayer", "ReadOnlySqlGuard", "ToolErrorsToModel", "email_masking", "redact",
           "model_fallback", "model_retry", "tool_retry"]
