from contextlib import AsyncExitStack
from .accounts_client import read_accounts_resource, read_strategy_resource
from .tracers import make_trace_id
from agents import (
    Agent,
    OpenAIChatCompletionsModel,
    Runner,
    Tool,
    set_default_openai_api,
    set_default_openai_client,
    set_tracing_export_api_key,
    trace,
)
from openai import AsyncOpenAI
from dotenv import load_dotenv
import os
import json
from prompts.templates import (
    researcher_instructions,
    trader_instructions,
    trade_message,
    rebalance_message,
    research_tool,
)
from .mcp_config import trader_mcp_servers, researcher_mcp_servers

load_dotenv(override=True)  # finds the repo-root .env: the LiteLLM proxy settings and the tracing key

MAX_TURNS = 30

# ---------------------------------------------------------------- models: everything goes through LiteLLM
#
# The code never talks to a model provider directly. Every model call goes to the LiteLLM proxy, with one
# LiteLLM key. LiteLLM holds the real provider keys (OpenAI, Google, DeepSeek, xAI, ...) and picks the provider
# from the model name:
#
#   agent ── "gemini-3.5-flash" + LiteLLM key ──► LiteLLM (localhost:4000) ── Google key ──► Gemini
#
# To use a model, register it in LiteLLM (UI: Models → Add Model) under a public name, then pass that name,
# e.g. Trader("Ray", model_name="gemini-3.5-flash"). Nothing in this file changes per provider.

# os.environ[...] (not getenv): fail loudly if the proxy settings are missing, instead of silently calling
# OpenAI directly with whatever default the openai library would pick.
LITELLM_BASE_URL = os.environ["OPENAI_BASE_URL"]  # the proxy, e.g. http://localhost:4000
LITELLM_API_KEY = os.environ["OPENAI_API_KEY"]    # a LiteLLM key, not a real OpenAI key

# The one client for every model.
gateway = AsyncOpenAI(base_url=LITELLM_BASE_URL, api_key=LITELLM_API_KEY)

# Also make it the Agents SDK's default client, so any agent created with a plain model name goes through the
# proxy too. use_for_tracing=False: traces must not be sent with the LiteLLM key (OpenAI would reject it).
set_default_openai_client(gateway, use_for_tracing=False)

# Speak the classic Chat Completions API: LiteLLM serves it for every provider. (The SDK's default, the newer
# Responses API, isn't available for every model behind the proxy.)
set_default_openai_api("chat_completions")

# Traces go straight to OpenAI (platform.openai.com/traces), not through LiteLLM, so they need a real OpenAI key.
set_tracing_export_api_key(os.environ["OPENAI_TRACING_API_KEY"])


def get_model(model_name: str) -> OpenAIChatCompletionsModel:
    """The model called `model_name` in LiteLLM, reached through the proxy.

    The name is passed to LiteLLM unchanged, so any public name works, including names with a "/" such as
    "gemini/gemini-3.5-flash" (which the Agents SDK would otherwise read as an unknown provider prefix).
    """
    return OpenAIChatCompletionsModel(model=model_name, openai_client=gateway)


async def get_researcher(mcp_servers, model_name) -> Agent:
    researcher = Agent(
        name="Researcher",
        instructions=researcher_instructions(),
        model=get_model(model_name),
        mcp_servers=mcp_servers,
    )
    return researcher


async def get_researcher_tool(mcp_servers, model_name) -> Tool:
    researcher = await get_researcher(mcp_servers, model_name)
    return researcher.as_tool(tool_name="Researcher", tool_description=research_tool())


class Trader:
    def __init__(self, name: str, lastname="Trader", model_name="gpt-5.4-mini"):
        self.name = name
        self.lastname = lastname
        self.agent = None
        self.model_name = model_name
        self.do_trade = True

    async def create_agent(self, trader_mcp_servers, researcher_mcp_servers) -> Agent:
        tool = await get_researcher_tool(researcher_mcp_servers, self.model_name)
        self.agent = Agent(
            name=self.name,
            instructions=trader_instructions(self.name),
            model=get_model(self.model_name),
            tools=[tool],
            mcp_servers=trader_mcp_servers,
        )
        return self.agent

    async def get_account_report(self) -> str:
        account = await read_accounts_resource(self.name)
        account_json = json.loads(account)
        account_json.pop("portfolio_value_time_series", None)
        return json.dumps(account_json)

    async def run_agent(self, trader_mcp_servers, researcher_mcp_servers):
        self.agent = await self.create_agent(trader_mcp_servers, researcher_mcp_servers)
        account = await self.get_account_report()
        strategy = await read_strategy_resource(self.name)
        message = (
            trade_message(self.name, strategy, account)
            if self.do_trade
            else rebalance_message(self.name, strategy, account)
        )
        await Runner.run(self.agent, message, max_turns=MAX_TURNS)

    async def run_with_mcp_servers(self):
        async with AsyncExitStack() as stack:
            trader_servers = [
                await stack.enter_async_context(server) for server in trader_mcp_servers()
            ]
            researcher_servers = [
                await stack.enter_async_context(server)
                for server in researcher_mcp_servers(self.name)
            ]
            await self.run_agent(trader_servers, researcher_servers)

    async def run_with_trace(self):
        trace_name = f"{self.name}-trading" if self.do_trade else f"{self.name}-rebalancing"
        trace_id = make_trace_id(f"{self.name.lower()}")
        with trace(trace_name, trace_id=trace_id):
            await self.run_with_mcp_servers()

    async def run(self):
        try:
            await self.run_with_trace()
        except Exception as e:
            print(f"Error running trader {self.name}: {e}")
        self.do_trade = not self.do_trade