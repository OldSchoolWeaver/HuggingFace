"""Writer: drafts, expands or summarizes text. The latest saved draft becomes the report."""
import re

from aisuite import Agent

from core.config import model_for, run_agent, safe_tool
from core.state import current_run, list_sources


@safe_tool
def save_draft(markdown: str) -> str:
    """Save your text. The latest saved draft is what the user reads as the report.

    Args:
        markdown: The full text in markdown, with [S#] citations and a References section.
    """
    run = current_run()
    unknown = set(re.findall(r"\[(S\d+)\]", markdown)) - {s["id"] for s in run.sources}
    if unknown:
        return f"ERROR: {', '.join(sorted(unknown))} are not recorded sources. Cite only ids from list_sources()."
    run.report = markdown.strip()
    return "Draft saved."


INSTRUCTIONS = (
    "You are the Writer. You execute writing tasks: drafting, expanding or summarizing text.\n"
    "- Draft: write from the research findings in your context.\n"
    "- Expand or summarize: rework the latest draft in your context as asked.\n"
    "A full report has a # title, an Executive summary, sections per theme, Limitations, and References "
    "listing each cited source as '[S1] Title - URL'. Use ONLY facts from the findings and recorded sources "
    "(call list_sources()), cite inline with [S#], never invent facts or sources. "
    "Always call save_draft(markdown) with your complete text, then reply 'Saved.'"
)


def writer_agent(task: str, model: str = model_for("writer"), **run_options) -> str:
    """
    Executes writing tasks, such as drafting, expanding, or summarizing text.

    Args:
        task (str): The writing step, enriched with context from previous steps.
        model (str): Language model to use.

    Returns:
        str: The text written in this step (the saved draft), or the model's reply if nothing was saved.
    """
    run = current_run()
    before = run.report
    agent = Agent(name="Writer", model=model, instructions=INSTRUCTIONS, tools=[list_sources, save_draft])
    reply = run_agent(agent, task, turns=4, **run_options)
    return run.report if run.report != before else reply
