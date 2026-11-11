"""Golden-record evals for the Researcher.

Runs the Researcher alone on each question in golden_dataset.jsonl and checks its recorded sources:
  * golden precision = 100%  (every cited source is on the trusted list)
  * grounded         = 100%  (every cited URL was really retrieved, none invented)
  * expected recall >= the question's min_recall (found the reference sources we expect)
  * at least 2 sources

    python -m evals.run_evals            # all cases (needs HF_TOKEN)
    python -m evals.run_evals who-air-pollution transformer-paper

Writes evals/results.md and exits with 1 if any case fails.
"""
import json
import sys
from pathlib import Path

from core.golden import score_sources
from core.pipeline import make_client
from core.state import RUNS_DIR, start_run
from core.tracing import TraceLogger

HERE = Path(__file__).parent
RESULTS = HERE / "results.md"


def load_cases() -> list[dict]:
    return [json.loads(line) for line in (HERE / "golden_dataset.jsonl").read_text().splitlines() if line.strip()]


def score_case(case: dict, sources: list[str], seen_urls: set[str]) -> dict:
    s = score_sources(sources, seen_urls, case["expected_sources"])
    failed = [name for name, ok in [
        ("golden", s["golden_precision"] == 1.0),
        ("grounded", s["grounded_rate"] == 1.0),
        ("recall", s["expected_recall"] >= case["min_recall"]),
        ("min 2 sources", s["cited"] >= 2),
    ] if not ok]
    return {"id": case["id"], **s, "failed": failed, "passed": not failed}


def run_case(case: dict, client=None) -> dict:
    from agents import research_agent

    run = start_run(case["question"], RUNS_DIR / "evals")
    logger = TraceLogger(run.dir)
    try:
        research_agent(f"## Research question\n{case['question']}", client=client or make_client(), trace_sinks=[logger])
    except Exception as exc:  # noqa: BLE001
        run.error = str(exc)
    logger.save(f"Eval - {case['id']}")
    run.save()
    return score_case(case, [s["url"] for s in run.sources], run.seen_urls)


def to_markdown(results: list[dict]) -> str:
    rows = "\n".join(
        f"| {r['id']} | {'✅' if r['passed'] else '❌ ' + ', '.join(r['failed'])} | {r['cited']} | "
        f"{r['golden_precision']:.0%} | {r['grounded_rate']:.0%} | {r['expected_recall']:.0%} | {', '.join(r['expected_missing']) or '-'} |"
        for r in results
    )
    passed = sum(r["passed"] for r in results)
    return (f"# Researcher evals: {passed}/{len(results)} passed\n\n"
            "| Case | Result | Sources | Golden | Retrieved | Recall | Missing |\n|---|---|---|---|---|---|---|\n" + rows + "\n")


def run_evals(case_ids: list[str] | None = None, client=None, progress=print) -> list[dict]:
    results = []
    for case in load_cases():
        if not case_ids or case["id"] in case_ids:
            progress(f"Running {case['id']}…")
            results.append(run_case(case, client))
    RESULTS.write_text(to_markdown(results))
    return results


if __name__ == "__main__":
    from dotenv import find_dotenv, load_dotenv

    load_dotenv(find_dotenv(usecwd=True))  # HF_TOKEN from the nearest .env
    results = run_evals(sys.argv[1:])
    print(RESULTS.read_text())
    sys.exit(0 if all(r["passed"] for r in results) else 1)
