---
title: Research Agents
emoji: 🔬
colorFrom: indigo
colorTo: green
sdk: gradio
sdk_version: 5.23.1
app_file: app.py
pinned: false
tags:
  - aisuite
  - multi-agent
  - research
  - evals
---

# 🔬 Research Agents

Ask a research question. Five [aisuite](https://github.com/andrewyng/aisuite) agents plan the research,
search the web using **only golden (trusted) sources**, fact-check the findings and write a cited report.
Every model call and tool call is recorded in a trace log you can read in the app.

## How it works

```
 question ──▶ planner_agent(topic, model) ──▶ ["Research …", "Research …", "Review …", "Write …"]
                                                        │
                                                        ▼
                                      executor_agent(plan_steps, model)
                     for each step:  1. decide which agent handles it
                                     2. build context from the outputs of previous steps
                                     3. send the enriched task to that agent
                                     4. store the result in the shared history
                                                        │
                    ┌───────────────────────────────────┼───────────────────────────────────┐
                    ▼                                   ▼                                   ▼
             research_agent                       editor_agent                        writer_agent
              (Researcher)                         (Reviewer)                           (Writer)
     web_search · fetch_page · record_source   check_source · submit_review           save_draft
```

1. **`planner_agent(topic, model) -> List[str]`** asks the model for a Python list of 4-7 executable steps
   and parses it (falls back to a safe default plan if the answer isn't a valid list).
2. **`executor_agent(plan_steps, model) -> List[Dict]`** manages the workflow. For each step it:
   1. decides which agent (`research_agent`, `writer_agent` or `editor_agent`) should handle it, by asking the
      model for `{"agent": ..., "task": ...}` (keyword fallback if the answer isn't valid JSON);
   2. builds context from the outputs of the previous steps (`build_context`);
   3. sends the enriched task to the selected agent;
   4. collects and stores the result in the shared history (`{"step", "agent", "task", "output"}`).

   Extra: if `editor_agent` answers "revise", the Executor inserts a research step with the feedback and a new
   review step (at most 2 rounds). If no report was saved at the end, it calls `writer_agent`.
3. **`research_agent`** searches, reads pages and calls `record_source` for every fact. `record_source` only
   accepts **golden** sources: on the trusted list *and* actually retrieved (so invented URLs are rejected).
4. **`editor_agent`** (the Reviewer) checks every claim has a source, every source is golden and the quotes
   support the claims, then approves or asks for a revision.
5. **`writer_agent`** executes writing tasks (drafting, expanding or summarizing text) and returns the text.
   It saves each version with `save_draft`, which refuses citations to sources that were never recorded; the
   latest saved draft is the report.

## Files

| File | Purpose |
|------|---------|
| `app.py` | Gradio app. **Research** tab: live trace, report, downloadable files. **Evals** tab. |
| `agents/planner.py` | **Planner**: `planner_agent(topic, model) -> List[str]` and the list parser. |
| `agents/executor.py` | **Executor**: `executor_agent(plan_steps, model)` plus `choose_agent` (step 1) and `build_context` (step 2). |
| `agents/researcher.py` | **Researcher**: `research_agent(task, model)` and its tools `web_search`, `fetch_page`, `record_source`. |
| `agents/reviewer.py` | **Reviewer**: `editor_agent(task, model)` and its tools `check_source`, `submit_review`. |
| `agents/writer.py` | **Writer**: `writer_agent(task, model)` for drafting, expanding or summarizing, and its tool `save_draft`. |
| `core/config.py` | Model per agent, max turns, `run_agent` (runs an aisuite Agent) and `@safe_tool` (aisuite stops the whole run if a tool raises, so tools return errors instead). |
| `core/state.py` | The run state: plan, **shared history**, sources, reviews, report; and `list_sources` (used by three agents). |
| `core/golden.py` | Golden-record logic: `is_golden(url)` and `score_sources` (precision, grounding, recall). |
| `core/trusted_sources.yaml` | The golden-source policy: trusted domains, suffix rules (`.gov`, `.edu` …) and blocked domains. |
| `core/tracing.py` | `TraceLogger`: records every step of every agent plus the Executor's decisions (see below). |
| `core/pipeline.py` | `run_research()`: Planner → Executor with the trace logger, then saves the run folder. |
| `evals/golden_dataset.jsonl` | Eval questions with the golden references the Researcher should find. |
| `evals/run_evals.py` | Runs the Researcher on the dataset and scores it. |
| `tests/` | Offline tests with a scripted fake model and fake search. No token needed. |

## Trace log

`TraceLogger` is an aisuite **trace sink**: aisuite calls its `emit()` for every step (agent started, model
answered, tool called, tool result, error, agent finished). The same logger is passed to every agent run, and
`note()` adds the Planner's step list and the Executor's routing decisions, with each agent's work nested
under the step it belongs to. Each run folder `runs/<run>/` contains:

- `report.md`: the report plus a **Source check** table (golden ✅/❌, retrieved ✅/❌, rejected sources)
- `trace.md`: readable timeline · `trace.jsonl`: raw events · `run.json`: plan, shared history, reviews, sources

## Golden-record evals

`python -m evals.run_evals` runs the **Researcher** on each question in `evals/golden_dataset.jsonl` and
checks: 100% of sources golden, 100% actually retrieved, the expected reference sources found (per-question
`min_recall`), and at least 2 sources. Results go to `evals/results.md` (also shown in the app's Evals tab).

## Configuration (Space → Settings → Variables and secrets)

| Name | Default | Purpose |
|------|---------|---------|
| `HF_TOKEN` (secret) | - | Required. |
| `MODEL_ID` | `huggingface:Qwen/Qwen3-Coder-480B-A35B-Instruct` | Model for all agents (`provider:model`, must support tool calling). |
| `PLANNER_MODEL`, `RESEARCHER_MODEL`, … | `MODEL_ID` | Override one agent's model. |
| `RESEARCHER_MAX_TURNS`, … | 3-14 | Tool-call rounds per agent. |
| `MODEL_TIMEOUT` | `180` | Seconds per model call. |

## Run locally

```bash
pip install -r requirements.txt -r requirements-dev.txt
pytest -q                   # offline tests
export HF_TOKEN=hf_xxx
python app.py               # the app
python -m evals.run_evals   # evals (calls the model)
```

## Deploy

```bash
./deploy_space.sh all unit2      # -> MiguelBayanSoares/Research_Agent
```

Runs are saved in `runs/`, which the Space clears on restart: download reports you want to keep.
One run at a time; other users wait in the queue.
