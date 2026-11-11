"""Reviewer (the workflow's editor_agent): fact-checks the findings, then approves them or asks for a revision."""
from aisuite import Agent

from core.config import model_for, run_agent, safe_tool
from core.golden import is_golden, normalize_url
from core.state import current_run, list_sources


@safe_tool
def check_source(url: str) -> str:
    """Check whether a URL is a golden source and whether the Researcher actually retrieved it.

    Args:
        url: The URL to check.
    """
    retrieved = normalize_url(url) in {normalize_url(u) for u in current_run().seen_urls}
    return f"golden={is_golden(url)} retrieved={retrieved}"


@safe_tool
def submit_review(verdict: str, feedback: str) -> str:
    """Record your decision.

    Args:
        verdict: "approve" if the findings are ready for the report, otherwise "revise".
        feedback: What must be fixed or added (for "revise"), or why it is good (for "approve").
    """
    if verdict not in ("approve", "revise"):
        return 'ERROR: verdict must be "approve" or "revise".'
    current_run().reviews.append({"verdict": verdict, "feedback": feedback})
    return f"Review recorded: {verdict}."


INSTRUCTIONS = (
    "You are the Reviewer (the team's editor), a strict fact-checker. Call list_sources() and check that: "
    "every finding cites source ids; every source is golden and retrieved (use check_source when in doubt); "
    "the quotes really support the claims; the research question is fully covered. "
    "Then call submit_review(verdict, feedback) with 'approve' or 'revise' and specific feedback, "
    "and reply with the verdict and feedback."
)


def editor_agent(task: str, model: str = model_for("reviewer"), **run_options) -> str:
    """
    Reviews (edits) the findings so far: checks sources and claims, then approves or asks for a revision.

    Args:
        task (str): The review step, enriched with context from previous steps.
        model (str): Language model to use.

    Returns:
        str: The verdict ("approve" or "revise") with feedback.
    """
    agent = Agent(name="Reviewer", model=model, instructions=INSTRUCTIONS,
                  tools=[list_sources, check_source, submit_review])
    return run_agent(agent, task, turns=6, **run_options)
