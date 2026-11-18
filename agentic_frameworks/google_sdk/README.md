# Google ADK: the board worker

A worker agent built with Google's **Agent Development Kit** ([ADK](https://google.github.io/adk-docs/) 2.14). It is
handed one goal on a shared SQLite todo board and sees it through: it breaks the goal into steps on the board, does
the work with file tools from an MCP server, ticks each step off, and closes the goal.

The goal it's seeded with: *read `notes.txt`, translate it into natural Spanish, and write it to `spanish.txt`.*

```
worker.py ──seeds──► board.sqlite ◄──show_todos / plan_steps / complete_task──┐
    │                                                                          │
    └──runs──► task_worker (LlmAgent, gpt-4o-mini via the LiteLLM gateway) ────┘
                    │
                    └──read/write files──► filesystem MCP server ──► workspace/ (notes.txt → spanish.txt)
```

## Quick start

```bash
cd agentic_frameworks/google_sdk
uv sync                              # Python 3.13, google-adk[mcp], litellm, rich

uv run worker.py                     # seed a fresh goal and run the worker; prints the board and spanish.txt
uv run worker.py --seed-only         # only seed the board...
uv run adk web                       # ...then drive the worker from ADK's web UI (http://localhost:8000)
```

You need:
- **The LiteLLM gateway** running on `localhost:4000`. The agent loads the repo-root `.env`, which points
  `OPENAI_BASE_URL` at the gateway and holds the LiteLLM key in `OPENAI_API_KEY`.
- **Node.js (`npx`)**: the filesystem MCP server is started with `npx -y @modelcontextprotocol/server-filesystem`.

## Files

| File | What it is |
|------|------------|
| `task_worker/agent.py` | The agent: its instructions, its board tools and the filesystem MCP toolset |
| `board.py` | The SQLite todo board: goals, steps, statuses and results (`board.sqlite`, git-ignored) |
| `worker.py` | Seeds the board with the goal, runs the agent, then prints the board and the result |
| `quiet.py` | `silence()`: hides warnings and library logs so the agent's own trace is readable |
| `workspace/` | The only folder the agent's file tools can reach: `notes.txt` in, `spanish.txt` out |
| `task_worker/.adk/` | Created by `adk web`: its saved chat sessions (`session.db`, git-ignored) |
| `google-lab.ipynb` | Your notebook |

## How it works

**The board** (`board.py`) is one SQLite table of todos. A goal has no parent; a step points to its goal. Each
todo goes `pending → in_progress → done`, with a short result when done. WAL mode and a busy timeout let several
agents use the same board at once, which matters when more workers share it.

**The agent** (`task_worker/agent.py`) is one `LlmAgent` with two kinds of tools:
- **Board tools**, plain Python functions: `show_todos` (read the board), `plan_steps` (add steps under a goal),
  `complete_task` (mark a step or goal done). ADK describes them to the model from their names, type hints and
  docstrings.
- **File tools**, from the **filesystem MCP server** via `McpToolset`. The server is started with `workspace/` as its
  only allowed folder, so the agent can read and write files there and nowhere else.

The agent code lives in `task_worker/`, outside `workspace/`, so the agent can't read or change its own code.

**The model:** `model="gpt-4o-mini"` is a plain string. ADK 2.14 recognises OpenAI model names and uses its built-in
OpenAI client, which reads `OPENAI_BASE_URL` and `OPENAI_API_KEY`, so requests go through the LiteLLM gateway with no
wrapper. For a model the gateway serves under another name, use `LiteLlm(model="openai/<name>")` from
`google.adk.models.lite_llm` (the `litellm` dependency).

**A run** (`worker.py`):
1. `seed()` resets the board, deletes the old `spanish.txt` and adds the goal.
2. It marks the goal in progress and starts the agent with `InMemoryRunner(...).run_debug(...)`, which prints every
   step: model replies, tool calls and results.
3. The agent reads the board, plans its steps, reads `notes.txt`, writes `spanish.txt`, ticks the steps and closes
   the goal.
4. `worker.py` prints the board (done steps struck through in green) and the Spanish text.

`adk web` and `adk run` find the same agent through `task_worker/__init__.py`, which imports `agent` (where
`root_agent` is defined).
