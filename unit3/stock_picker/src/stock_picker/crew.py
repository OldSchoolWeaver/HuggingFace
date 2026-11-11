import os
from typing import List

from crewai import LLM, Agent, Crew, Process, Task
from crewai.memory import Memory
from crewai.project import CrewBase, agent, crew, task
from crewai_tools import SerperDevTool
from pydantic import BaseModel, Field

from stock_picker.tools.stock_metrics import StockMetricsTool


class TrendingCompany(BaseModel):
    """ A publicly traded company that is in the news and attracting attention """
    name: str = Field(description="Company name")
    ticker: str = Field(description="Stock ticker symbol on a public exchange, confirmed with the 'Get stock metrics' tool")
    reason: str = Field(description="Reason this company is trending in the news")

class TrendingCompanyList(BaseModel):
    """ List of multiple trending companies that are in the news """
    companies: List[TrendingCompany] = Field(description="List of 5-6 publicly traded companies trending in the news")

class TrendingCompanyResearch(BaseModel):
    """ Detailed research on a company. Metrics come from the 'Get stock metrics' tool; use "unknown" when it has no value. """
    name: str = Field(description="Company name")
    ticker: str = Field(description="Stock ticker symbol")
    market_position: str = Field(description="Current market position and competitive analysis")
    future_outlook: str = Field(description="Future outlook and growth prospects")
    investment_potential: str = Field(description="Investment potential and suitability for investment")
    EPS: str = Field(description="Earnings per share")
    Revenue_growth: str = Field(description="Revenue growth")
    Gross_profit_margin: str = Field(description="Gross profit margin")
    Return_on_equity: str = Field(description="Return on equity")
    Price_to_earnings: str = Field(description="Price to earnings ratio")
    Moving_average_convergence_divergence: str = Field(description="MACD line, signal and histogram, or \"unknown\"")
    Momentum: str = Field(description="10-day momentum")
    Simple_moving_average_30: str = Field(description="Simple moving average 30")
    Simple_moving_average_50: str = Field(description="Simple moving average 50")
    Simple_moving_average_100: str = Field(description="Simple moving average 100")
    Simple_moving_average_200: str = Field(description="Simple moving average 200")
    metrics_as_of: str = Field(description="Date of the price data the metrics are based on")


class TrendingCompanyResearchList(BaseModel):
    """ A list of detailed research on all the companies """
    research_list: List[TrendingCompanyResearch] = Field(description="Comprehensive research on all trending companies")


# Hard limits so a run can't loop forever (crewAI's default is 25 steps per agent per task, no time limit,
# and in hierarchical mode every delegation starts a coworker with its own 25). One step = one LLM call,
# usually followed by one tool call. Override any of them in .env, e.g. RESEARCHER_MAX_ITER=25.
def limit(name: str, default: int) -> int:
    return int(os.getenv(name, default))


def structured_llm(model: str, schema: type[BaseModel]) -> LLM:
    """An LLM whose every call must return `schema` JSON when it answers with text (tool calls still work).

    With output_pydantic, crewAI first makes a structured call; if the model answers with a tool call instead, crewAI
    falls back to a plain call. If that plain call returns text, gpt-4o-mini sometimes copies the JSON schema from the
    prompt, and the task fails with "Field required ... {'description': ..., 'additionalProperties': False}".
    Setting response_format on the LLM makes the fallback (and the forced final answer at max_iter) structured too."""
    return LLM(model=model, response_format=schema)


def build_memory() -> Memory:
    """Memory with an explicit embedding model. crewAI's default OpenAI embedder is text-embedding-ada-002,
    which many OpenAI projects can't use (403 model_not_found). Override with EMBEDDING_MODEL."""
    return Memory(embedder={
        "provider": "openai",
        "config": {"model_name": os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")},
    })


@CrewBase
class StockPicker():
    """StockPicker crew"""

    agents_config = 'config/agents.yaml'
    tasks_config = 'config/tasks.yaml'

    def __init__(self):
        self.memory = build_memory()  # one memory shared by the whole crew

    @agent
    def trending_company_finder(self) -> Agent:
        return Agent(config=self.agents_config['trending_company_finder'],
                     llm=structured_llm(self.agents_config['trending_company_finder']['llm'], TrendingCompanyList),
                     tools=[SerperDevTool(), StockMetricsTool()], memory=self.memory,
                     max_iter=limit("FINDER_MAX_ITER", 12),               # a few searches + 1 batched ticker check
                     max_execution_time=limit("FINDER_MAX_SECONDS", 300))

    @agent
    def financial_researcher(self) -> Agent:
        return Agent(config=self.agents_config['financial_researcher'],
                     llm=structured_llm(self.agents_config['financial_researcher']['llm'], TrendingCompanyResearchList),
                     tools=[SerperDevTool(), StockMetricsTool()], memory=self.memory,
                     max_iter=limit("RESEARCHER_MAX_ITER", 18),           # 1 batched metrics call + ~2 searches per company
                     max_execution_time=limit("RESEARCHER_MAX_SECONDS", 600))

    @agent
    def stock_picker(self) -> Agent:
        return Agent(config=self.agents_config['stock_picker'],
                     memory=self.memory,
                     max_iter=limit("PICKER_MAX_ITER", 5),                # no tools: it only writes the decision
                     max_execution_time=limit("PICKER_MAX_SECONDS", 300))

    @task
    def find_trending_companies(self) -> Task:
        return Task(
            config=self.tasks_config['find_trending_companies'],
            output_pydantic=TrendingCompanyList,
        )

    @task
    def research_trending_companies(self) -> Task:
        return Task(
            config=self.tasks_config['research_trending_companies'],
            output_pydantic=TrendingCompanyResearchList,
        )

    @task
    def pick_best_company(self) -> Task:
        return Task(
            config=self.tasks_config['pick_best_companies'],
        )

    @crew
    def crew(self) -> Crew:
        """Creates the StockPicker crew"""

        manager = Agent(
            config=self.agents_config['manager'],
            allow_delegation=True,
            max_iter=limit("MANAGER_MAX_ITER", 6),  # per task: delegate once, maybe one follow-up, then answer
        )

        return Crew(
            agents=self.agents,
            tasks=self.tasks,
            process=Process.sequential,
            verbose=True,
            manager_agent=manager,
            memory=self.memory,
            tracing=os.getenv("STOCK_PICKER_TRACING", "true").lower() == "true",  # app.py turns it off for the web app
        )
