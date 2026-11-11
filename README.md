# 🤗 Hugging Face Agents Course

Agent apps built while following the Hugging Face Agents Course. Each app lives in its own folder and is
deployed as its own Hugging Face Space.

## Apps

| App | Folder | Framework | Space |
|-----|--------|-----------|-------|
| 🛒 **Weekly Meal Planner** - plans a week of meals with recipes and one shopping list grouped by aisle | [`shopping_agent/`](shopping_agent/) | smolagents | [MiguelBayanSoares/shopping_list](https://huggingface.co/spaces/MiguelBayanSoares/shopping_list) |
| 🔬 **Research Agents** - five agents research a question using only trusted (golden) sources and write a cited report, with a full trace log and evals | [`research_agent/`](research_agent/) | aisuite | [MiguelBayanSoares/Research_Agent](https://huggingface.co/spaces/MiguelBayanSoares/Research_Agent) |
| 📈 **Financial Agents** - a **Financial Researcher** crew (cited company report) and a **Stock Picker** crew (trending listed companies, real market metrics, three picks) | [`financial_researcher_agent/`](financial_researcher_agent/) | crewAI | [MiguelBayanSoares/Financial_Researcher](https://huggingface.co/spaces/MiguelBayanSoares/Financial_Researcher) |

Each app's `README.md` explains how it works and what every file does. The YAML block at the top of that README
is also the Space's configuration.

> The financial apps are AI-generated research for learning purposes only: not financial advice.

## Repository layout

```
.
├── shopping_agent/               # 🛒 Space: shopping_list
├── research_agent/               # 🔬 Space: Research_Agent
├── financial_researcher_agent/   # 📈 Space: Financial_Researcher
│   ├── app.py                    #    one Gradio app with two tabs
│   ├── financial_researcher/     #    crewAI project (runs on its own with `crewai run`)
│   └── stock_picker/             #    crewAI project (runs on its own with `crewai run`)
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

1. Create the folder at the repo root with an `app.py`, a `requirements.txt` and a `README.md` that starts with
   the Space configuration block (`sdk`, `sdk_version`, `app_file`, …).
2. Create the Space on huggingface.co and add the secrets it needs (Settings → Variables and secrets).
3. Add a line to `app_target()` and `KNOWN_APPS` in `deploy_space.sh`, and a matrix entry in
   `.github/workflows/deploy-spaces.yml`.

## Running an app locally

Each app has its own dependencies, so give each one its own virtual environment:

```bash
cd research_agent                   # or shopping_agent / financial_researcher_agent
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python app.py                       # opens on http://127.0.0.1:7860
```

The Research Agents and Financial Agents apps read API keys from the `.env` file at the repo root. The Meal
Planner doesn't load `.env`, so export its keys first: `export $(grep -v '^#' ../.env | xargs)`.

| Key | Used by |
|-----|---------|
| `HF_TOKEN` | Meal Planner, Research Agents (Hugging Face Inference Providers) |
| `MODEL_ID` | Optional: overrides the default model of the Meal Planner and the Research Agents |
| `OPENAI_API_KEY` | Financial Agents (`gpt-4o-mini`, memory embeddings) |
| `SERPER_API_KEY` | Financial Agents (web search) |

On a Space, add the same keys as **secrets** instead; `.env` is never pushed.
