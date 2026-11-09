"""Shared state of one research run.

`history` is the shared history the Executor builds: one entry per executed step. The tools also store
what must be exact here: the Researcher's sources, the editor's verdicts and the Writer's report.
Runs are serialized (one at a time), so a module-level current run is safe.
"""
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

RUNS_DIR = Path(__file__).resolve().parent.parent / "runs"


@dataclass
class Run:
    question: str
    dir: Path
    plan: list[str] = field(default_factory=list)  # steps from planner_agent
    history: list[dict] = field(default_factory=list)  # {"step", "agent", "task", "output"} per executed step
    reviews: list[dict] = field(default_factory=list)  # {"verdict", "feedback"} from editor_agent
    sources: list[dict] = field(default_factory=list)  # {"id", "url", "title", "quote", "claim"}
    rejected: list[dict] = field(default_factory=list)  # {"url", "reason"}
    seen_urls: set[str] = field(default_factory=set)  # every URL seen in search results / fetched pages
    report: str = ""
    error: str = ""

    def save(self) -> None:
        data = {**asdict(self), "dir": str(self.dir), "seen_urls": sorted(self.seen_urls)}
        (self.dir / "run.json").write_text(json.dumps(data, indent=2, ensure_ascii=False))


_run: Run | None = None


def start_run(question: str, runs_dir: Path | None = None) -> Run:
    global _run
    slug = re.sub(r"[^a-z0-9]+", "-", question.lower()).strip("-")[:40]
    run_dir = (runs_dir or RUNS_DIR) / f"{datetime.now():%Y%m%d-%H%M%S}-{slug}"
    run_dir.mkdir(parents=True, exist_ok=True)
    _run = Run(question=question, dir=run_dir)
    return _run


def current_run() -> Run:
    if _run is None:
        raise RuntimeError("No research run in progress.")
    return _run


def list_sources() -> str:
    """List all sources recorded in this research run: id, title, URL, claim and supporting quote."""
    sources = current_run().sources
    if not sources:
        return "No sources recorded yet."
    return "\n".join(f"[{s['id']}] {s['title']} - {s['url']}\n  claim: {s['claim']}\n  quote: \"{s['quote']}\"" for s in sources)
