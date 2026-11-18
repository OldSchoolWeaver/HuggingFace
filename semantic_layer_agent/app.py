"""Gradio chat for the Voltway data agent. Run from this folder: uv run python app.py

Left: the conversation (questions and answers).
Right: the "Agent steps" panel. It fills in live as the agent works: the routing decision and every tool call,
with its layer, status and duration. Click a row to see that step's full arguments (the Cube query or SQL) and
its result.
"""

import asyncio
import json
import time
import uuid

import gradio as gr

from data_agent import DataAgent

EXAMPLES = [
    "How many vehicles are in service, by depot region?",
    "Which vehicle model is the most energy efficient, in kWh per 100 km?",
    "What share of our charging energy came from public networks each quarter, and what did it cost per kWh?",
    "On which days in March was the depot tariff highest, and how much did we charge at depots on those days?",
    "Which vehicles had the most maintenance downtime, and what did it cost?",
    "What tables do we have about charging, and what do the columns mean?",
]

COLUMNS = ["#", "Step", "Layer", "Status", "Time (s)"]  # "#" is question.step, e.g. 2.3 = 3rd step of the 2nd question
LAYERS = {"cube": "Cube", "datahub": "DataHub", "duckdb": "DuckDB", "postgres": "Postgres"}
ROUTES = {"cube": "Cube semantic layer", "datahub": "DataHub catalogue", "direct": "no data layer needed"}
STATUS = {"running": "⏳", "ok": "✅", "error": "🔴", "done": "🧭"}
STATUS_TEXT = {"running": "running", "ok": "ok", "error": "error", "done": "decided"}


_agent: DataAgent | None = None
_lock = asyncio.Lock()


async def get_agent() -> DataAgent:
    """Start the agent (and its MCP servers) once, on the first question."""
    global _agent
    async with _lock:
        if _agent is None:
            _agent = await DataAgent().start()
    return _agent


# ---------------------------------------------------------------- the steps panel
# Every step is a dict kept in a gr.State for the whole conversation:
#   {"q": 1, "n": 2, "kind": "tool", "name": "cube_query", "layer": "cube", "status": "ok",
#    "started": 1.4, "took": 0.3, "args": {...}, "result": "..."}

def table(steps: list[dict]) -> list[list]:
    """One table row per step, newest first. Time is when the step started and, once done, how long it took."""
    return [[f"{s['q']}.{s['n']}", s["name"], LAYERS.get(s["layer"], s["layer"] or ""), STATUS[s["status"]],
             f"{s['started']}" if s["took"] is None else f"{s['started']} +{s['took']}"] for s in reversed(steps)]


def summary(steps: list[dict]) -> str:
    """One line about the latest question: route, tool calls per layer, errors, total time."""
    if not steps:
        return "*Ask a question to see the steps the agent takes.*"
    q = steps[-1]["q"]
    current = [s for s in steps if s["q"] == q]
    route = next((s for s in current if s["kind"] == "route"), None)
    tools = [s for s in current if s["kind"] == "tool"]
    per_layer = {}
    for s in tools:
        per_layer[s["layer"]] = per_layer.get(s["layer"], 0) + 1
    errors = sum(s["status"] == "error" for s in tools)
    elapsed = max((s["started"] + (s["took"] or 0) for s in current), default=0)
    parts = [f"**Question {q}**",
             f"route **{route['name'].removeprefix('Route: ')}**" if route else "no route",
             f"{len(tools)} tool call{'s' * (len(tools) != 1)}"
             + (f" ({', '.join(f'{n} {LAYERS.get(k, k)}' for k, n in per_layer.items())})" if per_layer else ""),
             f"{errors} error{'s' * (errors != 1)}" if errors else "no errors",
             f"{elapsed:.1f}s"]
    return " · ".join(parts)


def detail(step: dict | None) -> str:
    """The full content of one step, as Markdown."""
    if step is None:
        return "*Click a row to see the step's arguments and result.*"
    if step["kind"] == "route":
        return f"### 🧭 {step['name']}\n\n{step['result']}"
    args = dict(step["args"] or {})
    sql = args.pop("sql", None)
    parts = [f"### 🔧 {step['name']}  \n{LAYERS.get(step['layer'], step['layer'])} · "
             f"{STATUS[step['status']]} {STATUS_TEXT[step['status']]}"
             + (f" · {step['took']}s" if step["took"] is not None else "")]
    if sql:
        parts.append(f"**SQL**\n```sql\n{sql}\n```")
    if args or not sql:
        parts.append(f"**Arguments**\n```json\n{json.dumps(args, indent=2, ensure_ascii=False)}\n```")
    if step["result"] is not None:
        result = step["result"]
        try:  # pretty-print JSON results (Cube, DataHub)
            result, lang = json.dumps(json.loads(result), indent=2, ensure_ascii=False), "json"
        except (ValueError, TypeError):
            lang = ""
        if len(result) > 6000:
            result = result[:6000] + "\n… (truncated)"
        parts.append(f"**{'Error' if step['status'] == 'error' else 'Result'}**\n```{lang}\n{result}\n```")
    return "\n\n".join(parts)


def show_step(steps: list[dict], event: gr.SelectData) -> str:
    """Clicked row -> its step. Rows are newest first, so row i is steps[-1 - i]."""
    row = event.index[0]
    return detail(steps[-1 - row] if 0 <= row < len(steps) else None)


# ---------------------------------------------------------------- chat

async def respond(question: str, history: list, thread_id: str, steps: list[dict]):
    """Stream the answer into the chat and every step into the panel.
    Yields (chat history, cleared textbox, steps state, steps table, summary, step detail)."""
    question = (question or "").strip()
    selected = None  # the step shown in the detail box: the latest one to change

    def update():
        return history, "", steps, table(steps), summary(steps), detail(selected)

    if not question:
        yield update()
        return
    history = history + [{"role": "user", "content": question}]
    steps = list(steps)
    q = (steps[-1]["q"] + 1) if steps else 1
    yield update()
    try:
        agent = await get_agent()
    except Exception as error:  # noqa: BLE001
        history.append({"role": "assistant", "content": f"⚠️ Couldn't start the agent: {error}\n\n"
                        "Is the Docker stack running? See the README (`scripts/setup.sh`)."})
        yield update()
        return

    started = time.perf_counter()
    since = lambda: round(time.perf_counter() - started, 1)  # noqa: E731
    by_call_id: dict[str, dict] = {}
    n = 0
    try:
        async for event in agent.stream(question, thread_id=thread_id):
            if event[0] == "route":
                _, route, reason = event
                n += 1
                selected = {"q": q, "n": n, "kind": "route", "name": f"Route: {ROUTES.get(route, route)}",
                            "layer": route if route in LAYERS else "", "status": "done", "started": since(),
                            "took": None, "args": None, "result": reason or ""}
                steps.append(selected)
            elif event[0] == "tool_call":
                _, name, args, call_id = event
                n += 1
                selected = {"q": q, "n": n, "kind": "tool", "name": name,
                            "layer": agent.sessions.server_of.get(name), "status": "running", "started": since(),
                            "took": None, "args": args, "result": None}
                by_call_id[call_id] = selected
                steps.append(selected)
            elif event[0] == "tool_result":
                _, name, text, is_error, call_id = event
                done = by_call_id.pop(call_id, None)
                if done is not None:
                    selected = done
                    selected.update(status="error" if is_error else "ok", result=text,
                                    took=round(since() - selected["started"], 1))
            else:
                history.append({"role": "assistant", "content": event[1]})
            yield update()
    except Exception as error:  # noqa: BLE001 - e.g. the model and its fallback both kept failing
        history.append({"role": "assistant", "content": f"⚠️ The agent failed: {type(error).__name__}: {error}"})
        yield update()


def new_conversation():
    return [], str(uuid.uuid4()), [], table([]), summary([]), detail(None)


with gr.Blocks(title="Voltway Data Agent") as ui:
    gr.Markdown("# ⚡ Voltway Data Agent\nAsk about the EV fleet. The agent uses the **DataHub** catalogue, the **Cube** "
                "semantic layer and **DuckDB**/**Postgres** SQL. Every step it takes appears on the right.")
    thread_id = gr.State(lambda: str(uuid.uuid4()))
    steps = gr.State([])
    with gr.Row(equal_height=False):
        with gr.Column(scale=3):
            chatbot = gr.Chatbot(height=560, label="Conversation")
            question = gr.Textbox(placeholder="e.g. Which model is the most energy efficient?", show_label=False)
            with gr.Row():
                ask = gr.Button("Ask", variant="primary")
                clear = gr.Button("New conversation")
            gr.Examples(EXAMPLES, question)
        with gr.Column(scale=2):
            gr.Markdown("### 🔍 Agent steps")
            step_summary = gr.Markdown(summary([]))
            step_table = gr.Dataframe(headers=COLUMNS, value=table([]), interactive=False, wrap=True,
                                      column_widths=["11%", "36%", "18%", "13%", "22%"], max_height=300,
                                      label="Route and tool calls (newest first, click a row for details)")
            step_detail = gr.Markdown(detail(None), max_height=420, container=True)

    outputs = [chatbot, question, steps, step_table, step_summary, step_detail]
    ask.click(respond, [question, chatbot, thread_id, steps], outputs, concurrency_id="agent")
    question.submit(respond, [question, chatbot, thread_id, steps], outputs, concurrency_id="agent")
    clear.click(new_conversation, None, [chatbot, thread_id, steps, step_table, step_summary, step_detail])
    step_table.select(show_step, steps, step_detail)

if __name__ == "__main__":
    ui.queue().launch(inbrowser=True, theme=gr.themes.Soft())
