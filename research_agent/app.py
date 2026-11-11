"""Gradio app: ask a question, watch the agents work live, read the report."""
import os
import threading

import gradio as gr
from dotenv import find_dotenv, load_dotenv

load_dotenv(find_dotenv(usecwd=True))  # local runs: read HF_TOKEN etc. from the nearest .env (repo root)

from agents import TEAM
from core.pipeline import run_research
from evals.run_evals import RESULTS, load_cases, run_evals

EXAMPLES = [
    "What are the main health effects of outdoor air pollution, and what are the WHO guideline values for PM2.5?",
    "How does the EU AI Act regulate high-risk AI systems?",
    "What did the IPCC AR6 report conclude about human influence on climate change?",
]


def in_background(job, errors: list):
    """Start job() in a thread; returns an Event that is set when it finishes (errors go to `errors`)."""
    done = threading.Event()

    def target():
        try:
            job()
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{type(exc).__name__}: {exc}")
        finally:
            done.set()

    threading.Thread(target=target, daemon=True).start()
    return done


def research(question: str):
    if not os.getenv("HF_TOKEN"):
        yield "⚠️ Set the HF_TOKEN secret first.", "", "", None
        return
    live, errors = {}, []
    done = in_background(lambda: live.update(result=run_research(question, on_start=lambda r, log: live.update(logger=log))), errors)
    while not done.wait(1):  # stream the trace while the agents work
        if "logger" in live:
            yield f"⏳ Working… {live['logger'].summary()}", "", live["logger"].timeline(), None
    if errors:
        yield f"💥 {errors[0]}", "", "", None
        return
    run, logger = live["result"]
    report = (run.dir / "report.md").read_text()
    files = [str(run.dir / f) for f in ("report.md", "trace.md", "trace.jsonl", "run.json")]
    yield f"{'✅ Done' if run.report else '⚠️ ' + run.error} · {logger.summary()}", report, logger.timeline(), files


def evaluate(case_ids: list[str]):
    if not os.getenv("HF_TOKEN"):
        yield "⚠️ Set the HF_TOKEN secret first."
        return
    progress, errors = ["Starting…"], []
    done = in_background(lambda: run_evals(case_ids, progress=progress.append), errors)
    while not done.wait(1):
        yield f"⏳ {progress[-1]}"
    yield f"💥 {errors[0]}" if errors else RESULTS.read_text()


with gr.Blocks(title="Research Agents", theme=gr.themes.Soft()) as demo:
    gr.Markdown(
        "# 🔬 Research Agents\nFive [aisuite](https://github.com/andrewyng/aisuite) agents research your question "
        "using only **golden (trusted) sources** and write a cited report. Every step is in the trace log.\n\n"
        + " · ".join(f"**{name.title()}** `{model.split(':', 1)[-1]}`" for name, model in TEAM.items())
    )
    with gr.Tab("🔎 Research"):
        question = gr.Textbox(label="Research question", lines=2)
        go = gr.Button("Run research", variant="primary")
        gr.Examples(EXAMPLES, question, cache_examples=False)
        status = gr.Markdown()
        with gr.Tab("📄 Report"):
            report = gr.Markdown()
        with gr.Tab("🪵 Trace log"):
            trace = gr.Markdown()
        with gr.Tab("⬇️ Files"):
            files = gr.File(file_count="multiple")
        go.click(research, question, [status, report, trace, files], concurrency_limit=1)

    with gr.Tab("🧪 Evals"):
        gr.Markdown("Runs the **Researcher** on fixed questions and checks that every source is golden, really "
                    "retrieved, and that it finds the expected references. Uses inference credits.")
        cases = gr.CheckboxGroup([c["id"] for c in load_cases()], label="Cases (none = all)")
        run_btn = gr.Button("Run evals")
        results = gr.Markdown(RESULTS.read_text() if RESULTS.exists() else "_No results yet._")
        run_btn.click(evaluate, cases, results, concurrency_limit=1)

if __name__ == "__main__":
    demo.queue().launch()
