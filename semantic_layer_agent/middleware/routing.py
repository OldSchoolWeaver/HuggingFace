"""Routing middleware: decides, for every question, which layer the agent must start from.

    cube      a business metric the semantic layer defines (fleet size, kWh/100 km, cost per kWh, ...)
    datahub   anything else about the data: what exists, what it means, personal data, or numbers that need
              tables or files the semantic layer doesn't cover (then SQL via DuckDB)
    direct    no data lookup needed: greetings, a follow-up the conversation already answers, requests the
              agent must refuse (changing data)

How it works:
  1. before_agent (once per question): a small, fast router model reads the question, the recent conversation
     and the list of Cube metrics, and returns a structured RouteDecision. It's saved in the agent state
     (`route`, `route_reason`), so it shows up in the stream, in LangSmith traces and in the evaluations.
  2. wrap_model_call (first model call of the question only): the model is given only the chosen layer's tools,
     with tool_choice="any", so its first step must be a Cube or a DataHub call. From the second call on it has
     every tool again, so it can still fall back (e.g. Cube can't answer, go to DataHub + SQL).
"""

from typing import Any, Literal, NotRequired

from langchain.agents.middleware import AgentMiddleware, AgentState
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field

Route = Literal["cube", "datahub", "direct"]


class RouteDecision(BaseModel):
    """Where the agent should start for this question."""

    route: Route = Field(description="cube, datahub or direct (see the instructions)")
    reason: str = Field(description="One short sentence explaining the choice")


class RoutingState(AgentState):
    route: NotRequired[str]
    route_reason: NotRequired[str]


ROUTER_PROMPT = """You route questions for Voltway's data agent (an electric sales fleet in Portugal) to the right
layer of the data stack. Answer with one route:

- "cube": the question asks for a business metric that the semantic layer below defines, optionally broken down by
  its dimensions or filtered by time (e.g. fleet size, energy efficiency in kWh per 100 km, charging cost per kWh,
  public charging share, downtime, maintenance cost, distance, trip or charging session counts).
- "datahub": everything else that needs data. Questions about what data exists or what it means, which columns are
  personal data, and numbers the semantic layer does not define: anything using the daily electricity tariff or grid
  CO2 (the energy_prices file), metrics that combine facts the semantic layer can't join (e.g. charging cost per km
  driven), or lists of individual rows.
- "direct": no data lookup is needed: greetings, questions about you, a follow-up the conversation already answers,
  or a request to change or delete data (the agent only reads data and must refuse).

If a follow-up refers to an earlier question ("and by region?"), route it like that question.

Metrics defined in the semantic layer (Cube):
{metrics}"""

TOOLS_NOTE = {
    "cube": ("Routing decision: this is a metric question, so start with the Cube semantic layer (cube_meta, then "
             "cube_query). Its definitions are the official ones. Use the other tools only if Cube can't answer."),
    "datahub": ("Routing decision: start with the DataHub catalogue (search, get_entities, list_schema_fields) to find "
                "the right data and understand it, then write SQL for DuckDB if numbers are needed."),
}


def _text(message) -> str:
    content = getattr(message, "content", "")
    return content if isinstance(content, str) else getattr(message, "text", str(content))


class RouteToLayer(AgentMiddleware):
    """Classifies each question (cube / datahub / direct) and makes the agent's first step use that layer."""

    state_schema = RoutingState

    def __init__(self, router, metrics_overview: str, server_of: dict[str, str], history_messages: int = 6):
        """router: a chat model with structured output (RouteDecision), or anything with an async ainvoke(messages).
        metrics_overview: the Cube metrics, one per line. server_of: tool name -> MCP server name."""
        super().__init__()
        self.router = router
        self.system_prompt = ROUTER_PROMPT.format(metrics=metrics_overview or "(the semantic layer isn't available)")
        self.server_of = server_of
        self.history_messages = history_messages

    async def abefore_agent(self, state: RoutingState, runtime) -> dict[str, Any] | None:
        messages = state["messages"]
        question = next((_text(m) for m in reversed(messages) if m.type == "human"), "")
        earlier = [m for m in messages[:-1] if m.type in ("human", "ai") and _text(m)][-self.history_messages:]
        conversation = "\n".join(f"{'User' if m.type == 'human' else 'Agent'}: {_text(m)[:400]}" for m in earlier)
        prompt = (f"Earlier in the conversation:\n{conversation}\n\n" if conversation else "") + f"Question: {question}"
        try:
            decision = await self.router.ainvoke([SystemMessage(self.system_prompt), HumanMessage(prompt)])
        except Exception as error:  # noqa: BLE001 - routing must never block an answer
            return {"route": "unrouted", "route_reason": f"Router failed ({type(error).__name__}); no restriction."}
        return {"route": decision.route, "route_reason": decision.reason}

    @staticmethod
    def _first_model_call(messages: list) -> bool:
        """True if the model hasn't answered yet since the latest user message."""
        for message in reversed(messages):
            if message.type == "human":
                return True
            if isinstance(message, AIMessage):
                return False
        return True

    async def awrap_model_call(self, request, handler):
        route = request.state.get("route")
        if route in TOOLS_NOTE and self._first_model_call(request.messages):
            allowed = [t for t in request.tools if self.server_of.get(getattr(t, "name", "")) == route]
            if allowed:  # e.g. empty when that MCP server is switched off: then don't restrict
                base = _text(request.system_message) if request.system_message else ""
                request = request.override(
                    tools=allowed,
                    tool_choice="any",
                    system_message=SystemMessage(f"{base}\n\n{TOOLS_NOTE[route]}".strip()),
                )
        return await handler(request)
