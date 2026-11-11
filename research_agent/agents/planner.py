"""Planner: turns a research topic into a list of executable steps."""
import ast
import re
from typing import List

from aisuite import Agent

from core.config import model_for, run_agent

DEFAULT_PLAN = [
    "Research the background and key definitions of the topic using golden sources.",
    "Research the main evidence, data and findings, recording a golden source for every fact.",
    "Review the findings: check every claim is supported by a golden, retrieved source.",
    "Write the final report with an executive summary, findings, limitations and references.",
]

INSTRUCTIONS = """You are the Planner of a research team. Your team can execute these kinds of steps:
- research: search the web and record facts from golden (trusted) sources
- review: fact-check the findings and their sources
- write: draft, expand or summarize text (the last step must write the final report)

Return ONLY a Python list of 4-7 strings, one step per string, in execution order. Each step is one
clear, self-contained instruction for exactly one of the kinds above. Include at least one review step
after the research steps, and make the last step writing the final report. No other text.

Example:
["Research the definition and history of X.", "Research the latest data on Y.",
 "Review the findings and sources.", "Write the final report."]"""


def parse_steps(text: str) -> List[str]:
    """Extract the Python list from the model's answer; fall back to DEFAULT_PLAN if it isn't one."""
    match = re.search(r"\[.*\]", text or "", re.DOTALL)
    try:
        steps = ast.literal_eval(match.group(0)) if match else None
    except (ValueError, SyntaxError):
        steps = None
    if not isinstance(steps, list) or not steps or not all(isinstance(s, str) and s.strip() for s in steps):
        return list(DEFAULT_PLAN)
    return [s.strip() for s in steps]


def planner_agent(topic: str, model: str = model_for("planner"), **run_options) -> List[str]:
    """
    Generates a plan as a Python list of steps (strings) for a research workflow.

    Args:
        topic (str): Research topic to investigate.
        model (str): Language model to use.

    Returns:
        List[str]: A list of executable step strings.
    """
    agent = Agent(name="Planner", model=model, instructions=INSTRUCTIONS)
    return parse_steps(run_agent(agent, f"Research topic: {topic}", turns=1, **run_options))
