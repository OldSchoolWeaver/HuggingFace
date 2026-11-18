# Pydantic AI: the board worker

The Day 2 version of the board worker, built with [Pydantic AI](https://ai.pydantic.dev) 2.70. Same job as the
Google ADK one in [`../google_sdk`](../google_sdk/): take one goal from a SQLite todo board, plan its steps on the
board, do the work with file tools from an MCP server, tick each step off and close the goal.

The goal it's seeded with: *read `notes.txt`, translate it into natural Spanish, and write it to `spanish.txt`.*

## Quick start

```bash
cd agentic_frameworks/pydanticAI
uv sync                                   # Python 3.13, pydantic-ai-slim[openai,mcp], rich, python-dotenv

uv run worker.py                          # Day 2: seed the goal, run the worker, print the board and spanish.txt
uv run worker.py <taskId> <boardPath>     # Day 5: work one task on a shared board, then exit
```

You need:
- **The LiteLLM gateway** on `localhost:4000`. `worker.py` loads the repo-root `.env`, where `OPENAI_BASE_URL` points
  at the gateway and `OPENAI_API_KEY` holds the LiteLLM key.
- **Node.js (`npx`)**: the filesystem MCP server is started with `npx -y @modelcontextprotocol/server-filesystem`.

Settings (all optional, see `.env.example`): `WORKER_MODEL` (default `gpt-5.4-mini`), `BOARD_PATH`, and
`PYDANTIC_AI_NO_BANNER=1` to hide the observability banner.

## Files

| File | What it is |
|------|------------|
| `worker.py` | The agent, its board tools, the filesystem MCP toolset, and the two ways to run it |
| `board.py` | The SQLite todo board (the same file as in `google_sdk`); `board.sqlite` is git-ignored |
| `workspace/` | The only folder the file tools can reach: `notes.txt` in, `spanish.txt` out |

## How it works

```python
worker = Agent("openai-chat:gpt-5.4-mini", instructions=INSTRUCTIONS,
               tools=[show_todos, plan_steps, complete_task],   # plain functions: the board
               toolsets=[filesystem])                           # MCPToolset: the file tools
async with worker:                                              # starts (and later stops) the MCP server
    result = await worker.run(message)
```

- **The model:** `"openai-chat:<name>"` means "an OpenAI-compatible chat API". Pydantic AI's OpenAI client reads
  `OPENAI_BASE_URL` and `OPENAI_API_KEY`, so requests go through the LiteLLM gateway with no extra code.
- **Board tools** are plain functions. Pydantic AI builds each tool's description from its name, type hints and
  docstring.
- **File tools** come from the filesystem MCP server, wrapped in `MCPToolset` with a FastMCP `StdioTransport`. The
  server only allows the work folder, so the agent can't touch files elsewhere. `async with worker:` starts the
  server once for the whole run.
- **Two modes:** run bare, it seeds its own goal in `workspace/`. Given `<taskId> <boardPath>` (Day 5), it reads
  `BOARD_PATH` *before* importing `board`, works only that task on the shared board, and writes files next to the
  board file.

## ADK and Pydantic AI side by side

| | Google ADK (`../google_sdk`) | Pydantic AI (this folder) |
|---|---|---|
| Agent | `LlmAgent(model=..., instruction=..., tools=[...])` | `Agent(model, instructions=..., tools=[...], toolsets=[...])` |
| Model via the gateway | `"gpt-4o-mini"` (ADK's OpenAI client) | `"openai-chat:gpt-5.4-mini"` |
| MCP tools | `McpToolset(StdioConnectionParams(...))` | `MCPToolset(StdioTransport(...))` |
| Running it | A `Runner` with a session service; `run_debug` prints each step | `await agent.run(message)`; the result has the output and all messages |
| Dev UI | `adk web` | none built in (Logfire for traces) |

## Troubleshooting

**`Client failed to connect: Failed to initialize server session`** means the filesystem MCP server didn't start in
time. The MCP client starts it with a minimal environment (`PATH`, `HOME` and a few others, so your API keys aren't
passed to `npx`). Check that `npx` is on your `PATH`, and run
`npx -y @modelcontextprotocol/server-filesystem workspace` once by hand, so the package is downloaded before the
60-second start-up limit. If `npx` needs proxy settings to reach the npm registry, add `env=dict(os.environ)` to
`StdioTransport(...)`, but be aware that it passes every environment variable, keys included, to the server.
