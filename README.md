# 🤗 Hugging Face Agents Course

Agent apps built while following the Hugging Face Agents Course. Each app lives in its own folder; the web apps
are each deployed as their own Hugging Face Space.

## Apps

| App | Folder | Framework | Space |
|-----|--------|-----------|-------|
| 🛒 **Weekly Meal Planner** - plans a week of meals with recipes and one shopping list grouped by aisle | [`shopping_agent/`](shopping_agent/) | smolagents | [MiguelBayanSoares/shopping_list](https://huggingface.co/spaces/MiguelBayanSoares/shopping_list) |
| 🔬 **Research Agents** - five agents research a question using only trusted (golden) sources and write a cited report, with a full trace log and evals | [`research_agent/`](research_agent/) | aisuite | [MiguelBayanSoares/Research_Agent](https://huggingface.co/spaces/MiguelBayanSoares/Research_Agent) |
| 📈 **Financial Agents** - a **Financial Researcher** crew (cited company report) and a **Stock Picker** crew (trending listed companies, real market metrics, three picks) | [`financial_researcher_agent/`](financial_researcher_agent/) | crewAI | [MiguelBayanSoares/Financial_Researcher](https://huggingface.co/spaces/MiguelBayanSoares/Financial_Researcher) |
| 🛠️ **Engineering Team** - a lead, a backend, a frontend and a test engineer design, build and test a small Python app with a Gradio UI in a Docker sandbox | [`engineering_team_agent/`](engineering_team_agent/) | crewAI | — (runs locally) |

Each app's `README.md` explains how it works and what every file does. The YAML block at the top of that README
is also the Space's configuration.

> The financial apps are AI-generated research for learning purposes only: not financial advice.

## Frameworks and tools

| | 🛒 Meal Planner | 🔬 Research Agents | 📈 Financial Agents | 🛠️ Engineering Team |
|---|---|---|---|---|
| **Agent framework** | [smolagents](https://github.com/huggingface/smolagents) 1.26 (`CodeAgent`) | [aisuite](https://github.com/andrewyng/aisuite) 0.2 (`Agent`, `Runner`) | [crewAI](https://crewai.com) 1.14.4 (two crews, sequential) | [crewAI](https://crewai.com) 1.14.2 (one crew, sequential) |
| **Agents** | 1 | 5: planner, executor, researcher, reviewer, writer | 2 + 3: researcher, analyst / news analyst, researcher, picker | 4: lead, backend, frontend, test engineer |
| **LLM** | `Qwen/Qwen3-Coder-480B-A35B-Instruct` via Hugging Face Inference Providers (`MODEL_ID`) | same model via aisuite's Hugging Face provider (`MODEL_ID`, or one per agent) | OpenAI `gpt-4o-mini`; memory embeddings `text-embedding-3-small` | OpenAI `gpt-5.4` (lead, frontend), Anthropic `claude-sonnet-5` (backend), OpenAI `gpt-4o-mini` (tests) |
| **Tools** | DuckDuckGo search, webpage reader, meal plan tool | DuckDuckGo search (`ddgs`), webpage reader, golden-source checks | Serper web search; Yahoo Finance metrics (`yfinance`) | sandbox file read/write/run; [Context7](https://context7.com) MCP for library docs |
| **UI** | Gradio 5.23 (smolagents `GradioUI`) | Gradio 5.23 | Gradio 6.31 (two tabs, live log) | none: `crewai run` in the terminal |
| **Runs on** | Hugging Face Space | Hugging Face Space | Hugging Face Space | your machine; generated code runs in Docker (`uv`, Python 3.13) |
| **Also** | | trace log of every agent and tool call; evals against trusted sources | Pydantic structured outputs; crew memory; step and time limits | optional [LiteLLM](https://docs.litellm.ai) gateway (see below) |

### LiteLLM gateway (optional)

`docker-compose.quickstart.yml` starts a [LiteLLM](https://docs.litellm.ai) proxy with a Postgres database on
<http://localhost:4000>. It holds the real OpenAI/Anthropic keys and logs every request with its tokens and cost
per key. The crewAI apps can use it without code changes: set `OPENAI_BASE_URL` / `ANTHROPIC_BASE_URL` to the
gateway and the API keys to a LiteLLM key for that run. The full steps are in
[`engineering_team_agent/README.md`](engineering_team_agent/README.md#using-litellm-optional). It only runs locally,
so the Spaces can't use it.

```bash
docker compose -f docker-compose.quickstart.yml up -d   # needs LITELLM_MASTER_KEY and LITELLM_SALT_KEY in .env
```

## Repository layout

```
.
├── shopping_agent/               # 🛒 Space: shopping_list
├── research_agent/               # 🔬 Space: Research_Agent
├── financial_researcher_agent/   # 📈 Space: Financial_Researcher
│   ├── app.py                    #    one Gradio app with two tabs
│   ├── financial_researcher/     #    crewAI project (runs on its own with `crewai run`)
│   └── stock_picker/             #    crewAI project (runs on its own with `crewai run`)
├── engineering_team_agent/       # 🛠️ crewAI project, runs locally (`crewai run`)
├── docker-compose.quickstart.yml # optional LiteLLM gateway + Postgres
├── course/                       # course material that isn't part of any app
├── deploy_space.sh               # deploy an app to its Space and/or the repo to GitHub
├── .github/workflows/
│   └── deploy-spaces.yml         # automatic deploy on every push to main
└── .env                          # local API keys (git-ignored, never pushed)
```

## Deploying

A Space builds from the root of its own git repo, so each app folder is pushed **as the root** of its Space
(with `git subtree split`). Only committed changes are deployed.

**Manually**, from the repo root:

```bash
./deploy_space.sh shopping_agent               # -> MiguelBayanSoares/shopping_list
./deploy_space.sh research_agent               # -> MiguelBayanSoares/Research_Agent
./deploy_space.sh financial_researcher_agent   # -> MiguelBayanSoares/Financial_Researcher
./deploy_space.sh github                       # the whole repo -> GitHub
./deploy_space.sh all research_agent           # GitHub first, then that Space
./deploy_space.sh --help
```

**Automatically:** every push to `main` on GitHub runs `.github/workflows/deploy-spaces.yml`, which deploys every
app to its Space. It needs an `HF_TOKEN` repository secret with write access.

Authentication: the script uses `$HF_TOKEN` / `$GITHUB_TOKEN` when set, otherwise your git credentials.

### Adding a new app

1. Create the folder at the repo root with an `app.py` and a `README.md` that starts with the Space configuration
   block (`sdk`, `sdk_version`, `app_file`, …). Make it a uv project and generate its `requirements.txt`:
   `uv init --bare --no-workspace --python 3.13`, `uv add "gradio[oauth,mcp]==<sdk_version>" …`, then
   `./deploy_space.sh reqs <folder>`. Always pass `--no-workspace`, or uv joins the folder to a parent project and
   the apps end up sharing one environment.
2. Create the Space on huggingface.co and add the secrets it needs (Settings → Variables and secrets).
3. Add a line to `app_target()` and `KNOWN_APPS` in `deploy_space.sh`, and a matrix entry in
   `.github/workflows/deploy-spaces.yml`.

## Running an app locally

Every app is a [uv](https://docs.astral.sh/uv/) project with its own environment, because their dependencies
conflict (Gradio 5.23 vs 6.31, different crewAI versions). Install uv once (`brew install uv`), then:

```bash
cd research_agent                   # or shopping_agent / financial_researcher_agent
uv run python app.py                # creates the folder's .venv from uv.lock on the first run; http://127.0.0.1:7860
```

- `uv run` keeps `.venv` in sync with `uv.lock` before every run, so there's no venv to activate or forget.
- Each folder's `pyproject.toml` lists the direct dependencies, `uv.lock` pins every package, and `.python-version`
  sets the local Python (3.13; each Space uses the version in its README). Change dependencies with `uv add` / `uv remove` in the folder.
- Spaces install `requirements.txt`, not `uv.lock`. After changing dependencies, regenerate it with
  `./deploy_space.sh reqs <folder>` and commit; `deploy_space.sh` refuses to deploy if they don't match.
- `sidekick_agent/` (work in progress, a notebook so far): run `uv sync` in it, then open `lab.ipynb` in VS Code or
  Cursor and pick `sidekick_agent/.venv` as the kernel.
- `./sync_envs.sh` deletes and rebuilds every app's `.venv` from its `uv.lock` (or only the folders you name; `--dry-run` to
  preview). Use it after changing Python or when an environment is broken.
- `.venv/` is git-ignored everywhere. Without uv, `pip install -r requirements.txt` in a venv still works.

The Engineering Team is a crewAI project instead: `cd engineering_team_agent && crewai install && crewai run`
(needs Docker running). See its README.

The Research Agents and Financial Agents apps read API keys from the `.env` file at the repo root. The Meal
Planner doesn't load `.env`, so export its keys first: `export $(grep -v '^#' ../.env | xargs)`.

| Key | Used by |
|-----|---------|
| `HF_TOKEN` | Meal Planner, Research Agents (Hugging Face Inference Providers) |
| `MODEL_ID` | Optional: overrides the default model of the Meal Planner and the Research Agents |
| `OPENAI_API_KEY` | Financial Agents (`gpt-4o-mini`, memory embeddings), Engineering Team (lead, frontend and test engineers) |
| `SERPER_API_KEY` | Financial Agents (web search) |
| `ANTHROPIC_API_KEY` | Engineering Team (backend engineer) |
| `LITELLM_MASTER_KEY`, `LITELLM_SALT_KEY` | LiteLLM gateway (`docker-compose.quickstart.yml`). Never regenerate the salt key. |

On a Space, add the same keys as **secrets** instead; `.env` is never pushed.
