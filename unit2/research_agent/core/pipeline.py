"""Runs one research request and saves it to runs/<run>/:
report.md (report + source check) · trace.md · trace.jsonl · run.json"""
import os
import threading

import aisuite as ai

from core.golden import is_golden, normalize_url, score_sources
from core.state import Run, start_run
from core.tracing import TraceLogger

_one_at_a_time = threading.Lock()  # runs share module state (core/state.py)


def make_client() -> ai.Client:
    return ai.Client({"huggingface": {"timeout": int(os.getenv("MODEL_TIMEOUT", "180"))}})


def source_check(run: Run) -> str:
    """Markdown table verifying every recorded source, appended to each report."""
    urls = [s["url"] for s in run.sources]
    score = score_sources(urls, run.seen_urls)
    seen = {normalize_url(u) for u in run.seen_urls}
    rows = "\n".join(
        f"| {s['id']} | {s['url']} | {'✅' if is_golden(s['url']) else '❌'} | {'✅' if normalize_url(s['url']) in seen else '❌'} |"
        for s in run.sources
    )
    rejected = "".join(f"\n- {r['url']}: {r['reason']}" for r in run.rejected)
    return (
        f"## Source check\n\nGolden: **{score['golden_precision']:.0%}** · retrieved: **{score['grounded_rate']:.0%}** "
        f"· {len(urls)} sources\n\n| Id | URL | Golden | Retrieved |\n|---|---|---|---|\n{rows}\n"
        + (f"\n**Rejected during research:**{rejected}\n" if rejected else "")
    )


def run_research(question: str, client=None, on_start=None) -> tuple[Run, TraceLogger]:
    """Planner makes the step list, Executor runs it; everything is traced and saved."""
    from agents import executor_agent, planner_agent  # imported here so tests can set models first

    with _one_at_a_time:
        run = start_run(question)
        logger = TraceLogger(run.dir)
        client = client or make_client()
        if on_start:
            on_start(run, logger)  # lets the app show the trace live
        try:
            run.plan = planner_agent(question, client=client, trace_sinks=[logger])
            logger.note("Planner", "Plan:  \n" + "  \n".join(f"{n}. {s}" for n, s in enumerate(run.plan, 1)), trace_id="plan")
            executor_agent(run.plan, client=client, trace_sinks=[logger], log=lambda text: logger.note("Executor", text))
        except Exception as exc:  # noqa: BLE001 - keep the partial results and trace
            run.error = f"{type(exc).__name__}: {exc}"
        if not run.report:
            run.error = run.error or "The team finished without saving a report."
        report = run.report or "# No report\n\n" + run.error + "\n\n" + "\n\n".join(h["output"] for h in run.history)
        (run.dir / "report.md").write_text(f"{report}\n\n---\n\n{source_check(run)}")
        logger.save(f"Trace - {question}")
        run.save()
    return run, logger
