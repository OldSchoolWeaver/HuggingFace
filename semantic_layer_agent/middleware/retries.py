"""Retries and fallback for transient failures: a gateway hiccup or a dropped connection shouldn't fail a question.

  model_retry()      retries a model call that failed for a temporary reason (connection, timeout, rate limit,
                     server error), with exponential backoff: after about 1s, then 2s. Other errors (a bad request,
                     a context that's too long) aren't retried: they would fail again.
  model_fallback()   if the agent model still fails, tries FALLBACK_MODEL (if set) instead.
  tool_retry()       retries a tool call that failed because the MCP server couldn't be reached. A tool that ran
                     and returned an error (bad SQL, unknown Cube member) is NOT retried: the model sees the error
                     and fixes its query instead (see ToolErrorsToModel).

Retries happen inside the run, so they show up in the LangSmith trace.
"""

import anyio
import httpx
import openai
from langchain.agents.middleware import ModelFallbackMiddleware, ModelRetryMiddleware, ToolRetryMiddleware
from langchain_core.tools import ToolException

TRANSIENT_MODEL_ERRORS = (openai.APIConnectionError, openai.APITimeoutError, openai.RateLimitError,
                          openai.InternalServerError)
TRANSIENT_TOOL_ERRORS = (httpx.TransportError, anyio.ClosedResourceError, anyio.BrokenResourceError,
                         ConnectionError, TimeoutError)


def is_transient_model_error(error: BaseException) -> bool:
    return isinstance(error, TRANSIENT_MODEL_ERRORS)


def is_transient_tool_error(error: BaseException) -> bool:
    return isinstance(error, TRANSIENT_TOOL_ERRORS) and not isinstance(error, ToolException)


def model_retry(max_retries: int = 2) -> ModelRetryMiddleware:
    # on_failure="error": after the last retry, raise, so model_fallback (outside it) can take over.
    return ModelRetryMiddleware(max_retries=max_retries, retry_on=is_transient_model_error, on_failure="error",
                                initial_delay=1.0, backoff_factor=2.0)


def model_fallback(*models) -> list[ModelFallbackMiddleware]:
    """[] when no fallback model is configured, so it can be spread into the middleware list."""
    return [ModelFallbackMiddleware(*models)] if models else []


def tool_retry(max_retries: int = 2) -> ToolRetryMiddleware:
    # on_failure="error": after the last retry, raise, so ToolErrorsToModel turns it into a message for the model.
    return ToolRetryMiddleware(max_retries=max_retries, retry_on=is_transient_tool_error, on_failure="error",
                               initial_delay=0.5, backoff_factor=2.0)
