# EngineeringTeamAgent Crew

Welcome to the EngineeringTeamAgent Crew project, powered by [crewAI](https://crewai.com). This template is designed to help you set up a multi-agent AI system with ease, leveraging the powerful and flexible framework provided by crewAI. Our goal is to enable your agents to collaborate effectively on complex tasks, maximizing their collective intelligence and capabilities.

## Installation

Ensure you have Python >=3.10 <3.14 installed on your system. This project uses [UV](https://docs.astral.sh/uv/) for dependency management and package handling, offering a seamless setup and execution experience.

First, if you haven't already, install uv:

```bash
pip install uv
```

Next, navigate to your project directory and install the dependencies:

(Optional) Lock the dependencies and install them by using the CLI command:
```bash
crewai install
```
### Customizing

**Add `OPENAI_API_KEY` and `ANTHROPIC_API_KEY` to a `.env` file** (this folder or the repo root). The backend engineer runs on Claude, the other agents on OpenAI models (see `config/agents.yaml`).

- Modify `src/engineering_team_agent/config/agents.yaml` to define your agents
- Modify `src/engineering_team_agent/config/tasks.yaml` to define your tasks
- Modify `src/engineering_team_agent/crew.py` to add your own logic, tools and specific args
- Modify `src/engineering_team_agent/main.py` to add custom inputs for your agents and tasks

## Running the Project

To kickstart your crew of AI agents and begin task execution, run this from the root folder of your project:

```bash
$ crewai run
```

This command initializes the engineering_team_agent Crew, assembling the agents and assigning them tasks as defined in your configuration.

The agents write the design, the backend, the Gradio UI and the tests into `sandbox/`, which is reset at the start of each run.

## Using LiteLLM (optional)

You can send every LLM call of the crew through a [LiteLLM](https://docs.litellm.ai) gateway instead of straight to
OpenAI and Anthropic. The gateway keeps the real provider keys, and its UI shows each request, its tokens and its
cost per agent key. You can also set a budget on the key.

**No code changes are needed.** crewAI reads the gateway address from environment variables:

| Agent | Model (`config/agents.yaml`) | Variable that sets its address | Name LiteLLM receives |
|-------|------------------------------|--------------------------------|-----------------------|
| Engineering Lead, Frontend Engineer | `openai/gpt-5.4` | `OPENAI_BASE_URL` | `gpt-5.4` |
| Test Engineer | `openai/gpt-4o-mini` | `OPENAI_BASE_URL` | `gpt-4o-mini` |
| Backend Engineer | `anthropic/claude-sonnet-5` | `ANTHROPIC_BASE_URL` | `claude-sonnet-5` |

The Backend Engineer keeps its native Anthropic path (LiteLLM's `/v1/messages` endpoint), so `max_tokens` in
`crew.py` and the fix in `patch.py` still apply. Context7 is an MCP server, not an LLM, so it is still called directly.

### 1. Start the gateway

The repo root has `docker-compose.quickstart.yml` (LiteLLM plus the Postgres database where it stores models, keys and
spend). `LITELLM_MASTER_KEY` and `LITELLM_SALT_KEY` go in the root `.env`. Never regenerate the salt key: it encrypts
the provider keys stored in the database.

```bash
cd ..   # repo root
docker compose -f docker-compose.quickstart.yml up -d
```

The admin UI is at <http://localhost:4000/ui> (user `admin`, password: your `LITELLM_MASTER_KEY`).

### 2. Register the models

The names must match the table above, because crewAI drops the `openai/` and `anthropic/` prefix before sending. Leave
the API base empty: a wrong one (e.g. `http://localhost…`) makes the container call itself and fails with
`OpenAIException - Connection error`.

```bash
set -a; source .env; set +a   # in the repo root: loads LITELLM_MASTER_KEY and the provider keys
add_model () {  # $1 = name the agents use, $2 = provider/model, $3 = real provider key
  curl -s -X POST http://localhost:4000/model/new -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
    -H "Content-Type: application/json" \
    -d "{\"model_name\": \"$1\", \"litellm_params\": {\"model\": \"$2\", \"api_key\": \"$3\"}}"; echo
}
add_model gpt-5.4         openai/gpt-5.4            "$OPENAI_API_KEY"
add_model claude-sonnet-5 anthropic/claude-sonnet-5 "$ANTHROPIC_API_KEY"
add_model gpt-4o-mini     openai/gpt-4o-mini        "$OPENAI_API_KEY"
```

### 3. Create a key for the crew

```bash
export LITELLM_ENG_KEY=$(curl -s -X POST http://localhost:4000/key/generate \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" -H "Content-Type: application/json" \
  -d '{"key_alias": "engineering-team", "models": ["gpt-5.4", "claude-sonnet-5", "gpt-4o-mini"], "max_budget": 10}' \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['key'])")
```

`max_budget` is in US dollars; change or drop it.

### 4. Run the crew through the gateway

```bash
cd engineering_team_agent
OPENAI_BASE_URL=http://localhost:4000/v1 \
OPENAI_API_KEY=$LITELLM_ENG_KEY \
ANTHROPIC_BASE_URL=http://localhost:4000 \
ANTHROPIC_API_KEY=$LITELLM_ENG_KEY \
crewai run
```

- The Anthropic URL has no `/v1`, because the Anthropic SDK adds `/v1/messages` itself. The OpenAI one needs it.
- Always change the address and the key together: LiteLLM accepts only its own keys, so a real OpenAI or Anthropic
  key sent to it gets a 401.
- crewAI loads `.env` without overriding variables already set, so these values win for this run only. Without them,
  the crew calls OpenAI and Anthropic directly, as before.
- Don't put these variables in the repo-root `.env`: the other apps read it too and would also be routed through
  the gateway. To make the gateway the default for this crew only, put the four lines in `engineering_team_agent/.env`
  (then LiteLLM must be running for every run).

### 5. Check it

Open **Logs** in the LiteLLM UI: each request should come from the `engineering-team` key, with `gpt-5.4` for the
design and frontend tasks, `claude-sonnet-5` for the backend and `gpt-4o-mini` for the tests.

| Problem | Fix |
|---------|-----|
| 401 on the Backend Engineer | Use `ANTHROPIC_AUTH_TOKEN=$LITELLM_ENG_KEY` instead of `ANTHROPIC_API_KEY` (sent as a Bearer token). |
| `model not found` / `not allowed` | The model name in LiteLLM doesn't match the table, or it's missing from the key's `models`. |
| 403 on `gpt-5.4` | Your OpenAI project has no access to the model; LiteLLM uses the same OpenAI key. |
| `Connection error` | Check the model's API base in the UI (step 2). If it's empty, the container can't reach the provider (proxy, VPN or corporate TLS inspection). |

## Understanding Your Crew

The engineering_team_agent Crew is composed of multiple AI agents, each with unique roles, goals, and tools. These agents collaborate on a series of tasks, defined in `config/tasks.yaml`, leveraging their collective skills to achieve complex objectives. The `config/agents.yaml` file outlines the capabilities and configurations of each agent in your crew.

## Support

For support, questions, or feedback regarding the EngineeringTeamAgent Crew or crewAI.
- Visit our [documentation](https://docs.crewai.com)
- Reach out to us through our [GitHub repository](https://github.com/joaomdmoura/crewai)
- [Join our Discord](https://discord.com/invite/X4JWnZnxPb)
- [Chat with our docs](https://chatg.pt/DWjSBZn)

Let's create wonders together with the power and simplicity of crewAI.
