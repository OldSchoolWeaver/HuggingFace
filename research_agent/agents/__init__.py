"""The research team: one file per agent."""
from core.config import model_for

from .executor import executor_agent
from .planner import planner_agent
from .researcher import research_agent
from .reviewer import editor_agent
from .writer import writer_agent

# role -> model, shown in the app
TEAM = {name: model_for(name) for name in ["executor", "planner", "researcher", "reviewer", "writer"]}
