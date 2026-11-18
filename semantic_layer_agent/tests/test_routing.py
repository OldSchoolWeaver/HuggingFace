"""RouteToLayer: the router's decision, and how it restricts the agent's first step."""

import asyncio

from langchain.agents import create_agent
from langchain.agents.middleware import ModelRequest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool

from middleware import RouteDecision, RouteToLayer

METRICS = "- vehicles.active_count: Vehicles in service\n- trips.kwh_per_100km: Energy efficiency"


class FakeRouter:
    """Stands in for the router model: returns a fixed decision (or fails) and records what it was sent."""

    def __init__(self, route="cube", fail=False):
        self.route, self.fail, self.received = route, fail, []

    async def ainvoke(self, messages):
        self.received.append(messages)
        if self.fail:
            raise RuntimeError("router down")
        return RouteDecision(route=self.route, reason=f"chose {self.route}")


@tool
def cube_meta() -> str:
    """List the Cube metrics."""
    return '{"cubes": []}'


@tool
def search(query: str) -> str:
    """Search the DataHub catalogue."""
    return "fleet.drivers"


@tool
def execute_query(sql: str) -> str:
    """Run SQL in DuckDB."""
    return "37"


TOOLS = [cube_meta, search, execute_query]
SERVER_OF = {"cube_meta": "cube", "search": "datahub", "execute_query": "duckdb"}


def middleware(route="cube", fail=False):
    return RouteToLayer(FakeRouter(route, fail), METRICS, SERVER_OF)


# ---------------------------------------------------------------- abefore_agent: the decision

def decide(mw, messages):
    return asyncio.run(mw.abefore_agent({"messages": messages}, runtime=None))


def test_decision_is_stored_in_state():
    assert decide(middleware("datahub"), [HumanMessage("Which columns are personal data?")]) == {
        "route": "datahub", "route_reason": "chose datahub"}


def test_router_sees_metrics_question_and_history():
    mw = middleware()
    decide(mw, [HumanMessage("Most efficient model?"), AIMessage("The e-208."), HumanMessage("And by region?")])
    system, human = mw.router.received[0]
    assert "trips.kwh_per_100km" in system.content            # the Cube metrics are in the router prompt
    assert human.content.endswith("Question: And by region?")
    assert "User: Most efficient model?" in human.content and "Agent: The e-208." in human.content


def test_router_failure_does_not_block_the_question():
    assert decide(middleware(fail=True), [HumanMessage("hi")])["route"] == "unrouted"


# ---------------------------------------------------------------- awrap_model_call: the restriction

def model_call(mw, route, messages):
    """Run awrap_model_call and return the request the model would actually receive."""
    request = ModelRequest(model=GenericFakeChatModel(messages=iter([])), messages=messages, tools=TOOLS,
                           system_message=SystemMessage("You are Voltway's analyst."), state={"route": route})
    seen = []

    async def handler(req):
        seen.append(req)
        return AIMessage("ok")

    asyncio.run(mw.awrap_model_call(request, handler))
    return seen[0]


def names(request):
    return [t.name for t in request.tools]


def test_cube_route_offers_only_cube_tools_first():
    request = model_call(middleware(), "cube", [HumanMessage("How many vehicles?")])
    assert names(request) == ["cube_meta"]
    assert request.tool_choice == "any"                                   # a tool call is required
    assert request.system_message.content.startswith("You are Voltway's analyst.")
    assert "Routing decision: this is a metric question" in request.system_message.content


def test_datahub_route_offers_only_datahub_tools_first():
    request = model_call(middleware(), "datahub", [HumanMessage("What is in drivers?")])
    assert names(request) == ["search"] and request.tool_choice == "any"


def test_later_calls_get_every_tool():
    messages = [HumanMessage("How many vehicles?"),
                AIMessage("", tool_calls=[{"name": "cube_meta", "args": {}, "id": "c1"}]),
                ToolMessage("{}", tool_call_id="c1")]
    request = model_call(middleware(), "cube", messages)
    assert names(request) == ["cube_meta", "search", "execute_query"] and request.tool_choice is None


def test_direct_and_unrouted_are_not_restricted():
    for route in ("direct", "unrouted", None):
        request = model_call(middleware(), route, [HumanMessage("hi")])
        assert len(request.tools) == 3 and request.tool_choice is None


def test_no_restriction_when_the_layer_has_no_tools():
    mw = RouteToLayer(FakeRouter(), METRICS, {"search": "datahub"})  # Cube server switched off
    assert len(model_call(mw, "cube", [HumanMessage("How many vehicles?")]).tools) == 3


# ---------------------------------------------------------------- inside a real agent

class FakeModel(GenericFakeChatModel):
    """Records which tools each call was offered; calls the first offered tool once, then answers."""

    offered: list = []

    def bind_tools(self, tools, tool_choice=None, **kwargs):
        self.offered.append(([t.name for t in tools], tool_choice))
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        if messages[-1].type == "human":
            first_tool = self.offered[-1][0][0]
            message = AIMessage("", tool_calls=[{"name": first_tool, "args": {}, "id": "t1"}])
        else:
            message = AIMessage("37 vehicles are active.")
        return ChatResult(generations=[ChatGeneration(message=message)])


def test_route_in_a_real_agent():
    model = FakeModel(messages=iter([]), offered=[])
    agent = create_agent(model, tools=TOOLS, system_prompt="You are Voltway's analyst.",
                         middleware=[RouteToLayer(FakeRouter("cube"), METRICS, SERVER_OF)])
    result = asyncio.run(agent.ainvoke({"messages": [HumanMessage("How many vehicles are in service?")]}))
    assert result["route"] == "cube" and result["route_reason"] == "chose cube"
    assert model.offered[0][0] == ["cube_meta"]        # first call: Cube only, tool required
    assert len(model.offered[1][0]) == 3               # second call: every tool
    assert result["messages"][-1].content == "37 vehicles are active."
