"""Full run with the fake model. Plan: research -> review -> write. The first review asks for changes,
so the Executor inserts 'research again' + 'review' before writing."""
import json

import fakes
from agents.planner import DEFAULT_PLAN, parse_steps
from core.pipeline import run_research
from evals.run_evals import score_case


def test_planner_parses_python_list():
    assert parse_steps("Plan:\n['Research A.', 'Write the report.']") == ["Research A.", "Write the report."]
    assert parse_steps("1. research\n2. write") == DEFAULT_PLAN  # not a list -> safe default
    assert parse_steps("[1, 2]") == DEFAULT_PLAN


def test_full_research_run():
    run, logger = run_research("What are the health effects of air pollution?", client=fakes.fake_client())

    assert run.plan == ["Research the health effects of air pollution.", "Review the findings and sources.", "Write the final report."]
    assert run.report.startswith("# Air pollution and health"), run.error
    assert [r["verdict"] for r in run.reviews] == ["revise", "approve"]
    # shared history: plan steps + the revision round the Executor inserted
    assert [h["agent"] for h in run.history] == ["research_agent", "editor_agent", "research_agent", "editor_agent", "writer_agent"]
    assert "Air pollution is a major health risk [S1]" in run.history[0]["output"]
    assert run.history[-1]["output"] == run.report  # writer_agent returns the text it wrote
    assert [s["url"] for s in run.sources] == [fakes.WHO]  # the blog and the invented URL were rejected
    assert {r["url"] for r in run.rejected} == {"https://medium.com/blog", "https://www.nih.gov/invented"}
    assert "Golden: **100%**" in (run.dir / "report.md").read_text()

    events = [json.loads(line) for line in (run.dir / "trace.jsonl").read_text().splitlines()]
    assert {e["agent_name"] for e in events} == {"Executor", "Planner", "Researcher", "Reviewer", "Writer"}
    assert {"web_search", "record_source", "submit_review", "save_draft"} <= {
        e["data"]["tool_name"] for e in events if e["event_type"] == "tool.started"}
    notes = [e["data"]["text"] for e in events if e["event_type"] == "note"]
    assert any("added revision round 1" in n for n in notes)
    assert "Step 1/3 → **research_agent**" in (run.dir / "trace.md").read_text()


def test_context_is_built_from_previous_outputs():
    from agents.executor import build_context

    ctx = build_context("Q?", [{"agent": "research_agent", "task": "Research X", "output": "- fact [S1]"}])
    assert "## Research question\nQ?" in ctx and "## Step 1 - research_agent: Research X\n- fact [S1]" in ctx


def test_writer_cannot_cite_unrecorded_sources():
    from agents.writer import save_draft
    from core.state import start_run

    run = start_run("q")
    assert save_draft("Claim [S9]").startswith("ERROR") and run.report == ""


def test_eval_scoring():
    case = {"id": "x", "expected_sources": ["who.int"], "min_recall": 1.0}
    assert score_case(case, [fakes.WHO, "https://www.who.int/b"], {fakes.WHO, "https://www.who.int/b"})["passed"]
    result = score_case(case, [fakes.WHO, "https://medium.com/blog"], {fakes.WHO})
    assert result["failed"] == ["golden", "grounded"]
