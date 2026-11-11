"""Executor: manages the workflow by executing each step of the plan."""
import json
import re
from typing import Dict, List

from aisuite import Agent

from core.config import model_for, run_agent
from core.state import current_run

from .researcher import research_agent
from .reviewer import editor_agent
from .writer import writer_agent

AGENTS = {"research_agent": research_agent, "writer_agent": writer_agent, "editor_agent": editor_agent}
MAX_REVISIONS = 2
EXECUTOR_ID = "executor"  # trace id that the agents' work is nested under

ROUTER_INSTRUCTIONS = """You are the Executor of a research team. Decide which agent should handle a step:
- research_agent: searches the web and records facts from golden (trusted) sources
- editor_agent: reviews the findings and their sources, approves them or asks for a revision
- writer_agent: drafting, expanding or summarizing text, including the final report
Reply with ONLY JSON: {"agent": "research_agent" | "editor_agent" | "writer_agent", "task": "<instruction for that agent>"}"""


def choose_agent(step: str, model: str, **run_options) -> tuple[str, str]:
    """1. Decide which agent should handle the step (keyword fallback if the model's answer isn't valid JSON)."""
    router = Agent(name="Executor", model=model, instructions=ROUTER_INSTRUCTIONS)
    answer = run_agent(router, f"Step: {step}", turns=1, **run_options)
    try:
        choice = json.loads(re.search(r"\{.*\}", answer, re.DOTALL).group(0))
        if choice.get("agent") in AGENTS:
            return choice["agent"], choice.get("task") or step
    except (AttributeError, ValueError):
        pass
    if re.search(r"\b(review|edit|check|verify|fact-check)", step, re.IGNORECASE):
        return "editor_agent", step
    if re.search(r"\b(write|draft|expand|summari[sz]e|report)", step, re.IGNORECASE):
        return "writer_agent", step
    return "research_agent", step


def build_context(question: str, history: List[Dict]) -> str:
    """2. Build context from the outputs of the previous steps."""
    parts = [f"## Research question\n{question}"]
    for n, h in enumerate(history, 1):
        parts.append(f"## Step {n} - {h['agent']}: {h['task']}\n{h['output']}")
    return "\n\n".join(parts)


def executor_agent(plan_steps: List[str], model: str = model_for("executor"), log=None, **run_options) -> List[Dict]:
    """
    Executes each step of the plan with the right agent and collects the results in a shared history.

    Args:
        plan_steps (List[str]): Steps produced by planner_agent.
        model (str): Language model used to decide which agent handles each step.
        log: Optional callable(text) that writes the Executor's decisions to the trace log.

    Returns:
        List[Dict]: The shared history, one {"step", "agent", "task", "output"} per executed step.
    """
    run, note = current_run(), log or (lambda text: None)
    history = run.history  # shared: stored in the run, saved to run.json
    steps = [(step, None) for step in plan_steps]  # (step, agent if the Executor already decided it)
    revisions, i = 0, 0

    while i < len(steps):
        step, agent_name = steps[i]
        # 1. decide which agent handles the step
        agent_name, task = (agent_name, step) if agent_name else choose_agent(step, model, **run_options)
        note(f"Step {i + 1}/{len(steps)} → **{agent_name}**: {task}")
        # 2-3. build context from previous outputs and send the enriched task to the agent
        enriched_task = f"{build_context(run.question, history)}\n\n## Your task\n{task}"
        reviews_before = len(run.reviews)
        try:
            output = AGENTS[agent_name](enriched_task, parent_run_id=EXECUTOR_ID, **run_options)
        except Exception as exc:  # noqa: BLE001 - record the failure and carry on
            output = f"ERROR: {agent_name} failed: {exc}"
            note(f"⚠️ {output}")
        # 4. collect and store the result in the shared history
        history.append({"step": step, "agent": agent_name, "task": task, "output": output})

        # Extra: if the editor asked for changes, add a research + review round (max 2)
        if len(run.reviews) > reviews_before and run.reviews[-1]["verdict"] == "revise" and revisions < MAX_REVISIONS:
            revisions += 1
            steps[i + 1:i + 1] = [(f"Fix these review comments: {run.reviews[-1]['feedback']}", "research_agent"),
                                  ("Review the revised findings.", "editor_agent")]
            note(f"Editor asked for changes → added revision round {revisions}")
        i += 1

    if not run.report:  # the plan never reached the writer, or it didn't save
        note("No report saved yet → asking writer_agent")
        enriched_task = f"{build_context(run.question, history)}\n\n## Your task\nWrite and save the final report."
        output = writer_agent(enriched_task, parent_run_id=EXECUTOR_ID, **run_options)
        history.append({"step": "Write the final report.", "agent": "writer_agent", "task": "Write the final report.", "output": output})
    return history
