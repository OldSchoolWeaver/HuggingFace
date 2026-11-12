---
title: Shopping List Agent
emoji: ⚡
colorFrom: pink
colorTo: yellow
sdk: gradio
sdk_version: 5.23.1
app_file: app.py
pinned: false
tags:
  - smolagents
  - agent
  - smolagent
  - tool
  - agent-course
---

# 🛒 Weekly Meal Planner Agent

Tell the agent who you're cooking for and any preferences ("vegetarian dinners for 4, no spicy food").
It plans the week's meals, gives you a full recipe for each one scaled to your household, and builds a
single shopping list grouped by supermarket aisle. Ask follow-ups like *"swap Wednesday for fish"* and it
updates the plan and the list.

## How it works

The core design decision: **the LLM chooses recipes, plain Python does the counting.**
Language models are good at "a varied Mediterranean week" but unreliable at adding
`40 g + 2 oz + 1 tbsp` across seven recipes. So the model only *records* recipes through tools, and
deterministic code handles scaling, unit conversion, merging and grouping.

A request flows like this:

1. You type a message in the chat (`Gradio_UI.py`).
2. The `CodeAgent` (`app.py`) sends the model your message, its instructions and the tool descriptions.
3. The model replies with **Python code** that calls tools, e.g. a loop of `web_search(...)` calls.
   smolagents runs that code and feeds the output back to the model. This repeats (max 15 steps).
4. The model calls `start_meal_plan(...)`, then `add_recipe(...)` once per meal. Recipes are stored in a
   `MealPlan` object (`tools/meal_plan.py`).
5. The model calls `view_meal_plan()` and `build_shopping_list()`. Python produces the markdown.
6. `final_answer(...)` sends that markdown back to the chat.

Because the agent keeps its memory between messages, a follow-up edits the existing plan
(`add_recipe` replaces a slot) instead of starting over.

## Files

| File | Purpose |
|------|---------|
| `README.md` | The YAML block at the top (between the two `---` lines) is the **Space configuration**: which SDK (`gradio`), which version, and which file to run (`app_file: app.py`). The rest is this documentation, shown on the Space page. |
| `pyproject.toml`, `uv.lock`, `.python-version` | The app as a [uv](https://docs.astral.sh/uv/) project: its direct dependencies, the exact version of every package, and the local Python (3.12). Change dependencies with `uv add` / `uv remove`. |
| `requirements.txt` | Packages the Space installs, generated from `uv.lock` (`./deploy_space.sh reqs shopping_agent`); don't edit by hand. `smolagents[toolkit]` and `gradio` are pinned to exact versions so an upgrade can't silently break the app; `ddgs` powers web search; `markdownify` + `requests` power page reading. |
| `app.py` | **Entry point** the Space runs. Creates the model, defines the meal-planner instructions, builds the `CodeAgent` with its tools and launches the UI. |
| `Gradio_UI.py` | The **chat page**: a thin wrapper around smolagents' built-in Gradio UI that adds a title, description and example prompts. |
| `tools/meal_plan.py` | The **heart of the app**: the in-memory weekly plan plus the five tools the agent uses to build it, and the parsing/conversion helpers. |
| `tools/visit_webpage.py` | Tool that downloads a web page, converts it to markdown and truncates it to 10,000 characters so it fits in the model's context. |

### `app.py` in more detail

- **Model** – `InferenceClientModel` calls an LLM through Hugging Face Inference Providers. The model is read
  from the `MODEL_ID` environment variable (default `Qwen/Qwen3-Coder-480B-A35B-Instruct`), so you can switch
  models from the Space settings without changing code. `HF_PROVIDER` optionally forces a provider.
- **Instructions** – `MEAL_PLANNER_INSTRUCTIONS` is the agent's job description: defaults when the user
  doesn't specify (7 days, dinners, 2 people), the step-by-step workflow, the ingredient format, how to
  handle edits to an existing plan, and the rule to never do shopping-list maths itself.
- **Agent** – a `CodeAgent` writes Python to call tools instead of one JSON tool call per step, so it can
  e.g. run five searches in a single loop. `max_steps=15` is a safety cap.

### `Gradio_UI.py` in more detail

- `reset_agent_memory=False` – the agent remembers the conversation, which is what makes follow-up edits work.
- `cache_examples=False` – Spaces would otherwise run the whole agent once per example prompt at startup:
  slow, costs inference credits, and crashes on Gradio 5.x with agent step messages.

### `tools/meal_plan.py` in more detail

| Tool | What it does |
|------|--------------|
| `start_meal_plan(people, notes)` | Clears the plan and sets the household size. |
| `add_recipe(day, meal, title, servings, ingredients, steps, ...)` | Puts a recipe in a day/meal slot (replacing what was there). Ingredients are structured dicts `{name, quantity, unit}`. |
| `remove_recipe(day, meal)` | Empties a slot. |
| `view_meal_plan()` | Overview table + every recipe scaled to the household, with steps. |
| `build_shopping_list()` | Scales all recipes, converts units (oz→g, tbsp→ml…), merges duplicates, rounds counts up (no 1½ onions), groups by aisle and lists staples (salt, oil…) as "check your pantry". |

Helpers that make the tools robust to how the model formats things:
`parse_quantity` reads `"1 ½"`, `"2-3"`, `"¼"`; `normalize_name` strips words like "fresh"/"chopped" and
singularizes plurals so `onion`, `onions` and `onion, chopped` merge; `aisle_for` maps ingredients to aisles.

## Configuration

Set these in the Space under **Settings → Variables and secrets**. The code reads them with `os.getenv`.

| Name | Type | Purpose |
|------|------|---------|
| `HF_TOKEN` | Secret | Required. Hugging Face token used to call the model. |
| `MODEL_ID` | Variable | Optional. Any chat model served by a provider you've enabled, e.g. `openai/gpt-oss-120b`. |
| `HF_PROVIDER` | Variable | Optional. Force a specific provider, e.g. `cerebras` or `together`. |

## Running locally

```bash
export HF_TOKEN=hf_xxx
uv run python app.py   # creates .venv from uv.lock on the first run
```

Without uv: `python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt && python app.py`.

## Deploying

This folder lives inside a multi-app GitHub repo, but a Space needs `app.py` and this README at its root.
The repo's `deploy_space.sh` (or the GitHub Action in `.github/workflows/deploy-spaces.yml`) uses
`git subtree split` to push **only this folder** as the Space's root:

```bash
./deploy_space.sh shopping_agent
```

## Limitations

- One agent and one plan are shared by everyone using the Space, so simultaneous users would overwrite each
  other's plan. Fine for a course project; a per-session agent would fix it.
- Web search can be rate-limited; the agent is told to fall back to its own cooking knowledge when it is.
