"""Settings shared by all agents (all overridable with environment variables / Space variables)."""
import functools
import os

# aisuite model strings are "provider:model". MODEL_ID sets all agents; PLANNER_MODEL etc. override one.
DEFAULT_MODEL = "huggingface:Qwen/Qwen3-Coder-480B-A35B-Instruct"


def model_for(agent: str) -> str:
    model = os.getenv(f"{agent.upper()}_MODEL") or os.getenv("MODEL_ID") or DEFAULT_MODEL
    # aisuite needs "provider:model"; a plain Hub id like "Qwen/Qwen3-..." means Hugging Face
    return model if ":" in model.split("/")[0] else f"huggingface:{model}"


def max_turns(agent: str, default: int) -> int:
    """How many tool-call rounds an agent may take, e.g. RESEARCHER_MAX_TURNS=20."""
    return int(os.getenv(f"{agent.upper()}_MAX_TURNS", default))


def safe_tool(func):
    """aisuite aborts the whole run when a tool raises, so return errors to the model instead."""

    @functools.wraps(func)  # keep name, signature and docstring: aisuite builds the tool schema from them
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001
            return f"ERROR in {func.__name__}: {type(exc).__name__}: {exc}"

    return wrapper


def run_agent(agent, task: str, turns: int, client=None, trace_sinks=None, parent_run_id=None) -> str:
    """Run an aisuite Agent on a task and return its final answer as text."""
    from aisuite import Runner

    result = Runner.run_sync(agent, task, client=client, max_turns=max_turns(agent.name, turns),
                             trace_sinks=trace_sinks, parent_run_id=parent_run_id)
    return str(result.final_output or "")
