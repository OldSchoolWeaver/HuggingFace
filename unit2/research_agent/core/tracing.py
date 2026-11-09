"""TraceLogger - records every step of every agent: model calls, tool calls, tool results, errors.

aisuite sends a TraceEvent for each step of a run to the "trace sinks" passed to Runner.run.
The same TraceLogger is passed to every agent run, so it captures all five agents;
note() adds the Executor's own decisions (which step goes to which agent). It writes trace.jsonl (raw events) and trace.md (readable timeline) to the run folder.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

ICONS = {"note": "📋", "run.started": "▶️", "run.completed": "⏹️", "model.response": "🧠", "model.error": "💥",
         "tool.started": "🔧", "tool.completed": "✅", "tool.failed": "❌"}


def _short(value, n=200) -> str:
    text = " ".join((value if isinstance(value, str) else json.dumps(value, default=str)).split())
    return text if len(text) <= n else text[:n] + "…"


class TraceLogger:
    def __init__(self, run_dir: Path):
        self.jsonl = run_dir / "trace.jsonl"
        self.md = run_dir / "trace.md"
        self.events: list[dict] = []
        self.depth: dict[str, int] = {}  # trace_id -> nesting level (Executor = 0)

    def emit(self, event) -> None:  # called by aisuite for every step
        e = event.to_dict()
        self.depth.setdefault(e["trace_id"], self.depth.get(e.get("parent_run_id"), -1) + 1)
        self.events.append(e)
        with self.jsonl.open("a") as f:
            f.write(json.dumps(e, default=str) + "\n")

    def note(self, agent: str, text: str, trace_id: str = "executor") -> None:
        """Log a step that isn't an aisuite event, e.g. the Executor's routing decisions."""
        e = {"event_type": "note", "trace_id": trace_id, "agent_name": agent, "parent_run_id": None,
             "timestamp": datetime.now(timezone.utc).isoformat(), "data": {"text": text}}
        self.depth.setdefault(trace_id, 0)
        self.events.append(e)
        with self.jsonl.open("a") as f:
            f.write(json.dumps(e) + "\n")

    def describe(self, e: dict) -> str | None:
        kind, d = e["event_type"], e.get("data") or {}
        if kind == "note":
            return d["text"]
        if kind == "run.started":
            return f"started ({d.get('model')}): {_short(d.get('input'))}"
        if kind == "run.completed":
            return f"finished: {_short((d.get('run') or {}).get('final_output', ''))}"
        if kind == "model.response":
            calls = (d.get("response") or {}).get("tool_calls") or []
            if calls:
                return "calls " + ", ".join(f"`{c['name']}`" for c in calls)
            return f"answers: {_short((d.get('response') or {}).get('text_preview', ''))}"
        if kind == "tool.started":
            return f"`{d.get('tool_name')}`({_short(d.get('arguments', {}))})"
        if kind == "tool.completed":
            result = d.get("result_preview") or ""
            try:
                result = json.loads(result)  # aisuite stores the result JSON-encoded
            except ValueError:  # preview was truncated mid-JSON
                pass
            return f"`{d.get('tool_name')}` → {_short(result)}"
        if kind in ("tool.failed", "model.error"):
            return f"{d.get('tool_name', 'model')} error: {_short(d.get('error'))}"
        return None  # model.send, tool.allowed: not worth a line

    def timeline(self) -> str:
        if not self.events:
            return "_No steps yet._"
        t0 = datetime.fromisoformat(self.events[0]["timestamp"])
        lines = []
        for e in list(self.events):
            text = self.describe(e)
            if text:
                secs = (datetime.fromisoformat(e["timestamp"]) - t0).total_seconds()
                indent = "&nbsp;" * 6 * self.depth.get(e["trace_id"], 0)
                lines.append(f"`{secs:5.1f}s` {indent}{ICONS.get(e['event_type'], '')} **{e['agent_name']}** · {text}")
        return "  \n".join(lines)

    def count(self, event_type: str) -> int:
        return sum(e["event_type"] == event_type for e in self.events)

    def summary(self) -> str:
        return f"{self.count('run.started')} agent runs · {self.count('model.send')} model calls · {self.count('tool.started')} tool calls"

    def save(self, title: str) -> None:
        self.md.write_text(f"# {title}\n\n{self.summary()}\n\n{self.timeline()}\n")
