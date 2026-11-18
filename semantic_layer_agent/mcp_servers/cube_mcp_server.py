"""MCP server for the Cube semantic layer (Cube Core REST API).

Cube Core has no official MCP server, so this small one exposes the three things the agent needs:
the model (cubes, measures, dimensions and their business definitions), running a semantic query,
and showing the SQL Cube generates for it. Run by the agent over stdio: python mcp_servers/cube_mcp_server.py
"""

import json
import os
import time
from pathlib import Path

import httpx
import jwt
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

PROJECT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT / ".env")
load_dotenv(PROJECT.parent / ".env")

CUBE_API_URL = os.getenv("CUBE_API_URL", f"http://localhost:{os.getenv('CUBE_PORT', '4001')}/cubejs-api/v1")
CUBE_API_SECRET = os.getenv("CUBEJS_API_SECRET", "local-dev-cube-secret-change-me-0123456789")
WAIT_SECONDS = 60
MAX_ROWS = 500

mcp = FastMCP("cube", log_level="WARNING")


def _headers() -> dict:
    """Cube REST API auth: a JWT signed with the API secret (ignored in dev mode, required otherwise)."""
    now = int(time.time())
    token = jwt.encode({"iat": now, "exp": now + 3600}, CUBE_API_SECRET, algorithm="HS256")
    return {"Authorization": token, "Content-Type": "application/json"}


def _call(method: str, path: str, payload: dict | None = None) -> dict:
    """Call the Cube API, waiting while Cube answers "Continue wait" (it is still running the query)."""
    deadline = time.time() + WAIT_SECONDS
    with httpx.Client(timeout=30) as client:
        while True:
            if method == "GET":
                response = client.get(f"{CUBE_API_URL}/{path}", headers=_headers())
            else:
                response = client.post(f"{CUBE_API_URL}/{path}", headers=_headers(), json=payload)
            body = response.json()
            if body.get("error") == "Continue wait" and time.time() < deadline:
                time.sleep(1)
                continue
            if response.status_code >= 400 or "error" in body:
                raise ValueError(f"Cube API error ({response.status_code}): {body.get('error', body)}")
            return body


@mcp.tool()
def cube_meta() -> str:
    """List the semantic layer: every cube with its measures (metrics) and dimensions, their types
    and business definitions. Call this first to see which governed metrics exist before writing SQL."""
    meta = _call("GET", "meta")
    cubes = []
    for cube in meta.get("cubes", []):
        cubes.append({
            "cube": cube["name"],
            "description": cube.get("description"),
            "measures": [{"name": m["name"], "type": m.get("type"), "description": m.get("description")}
                         for m in cube.get("measures", [])],
            "dimensions": [{"name": d["name"], "type": d.get("type"), "description": d.get("description")}
                           for d in cube.get("dimensions", []) if d.get("public", True) is not False],
        })
    return json.dumps({"cubes": cubes}, indent=1)


@mcp.tool()
def cube_query(query: dict) -> str:
    """Run a semantic query and return the rows. `query` is a Cube REST query, for example:
    {"measures": ["trips.energy_per_100km"], "dimensions": ["vehicles.make_model"],
     "timeDimensions": [{"dimension": "trips.started_at", "granularity": "month",
                         "dateRange": ["2026-01-01", "2026-03-31"]}],
     "filters": [{"member": "depots.region", "operator": "equals", "values": ["Lisboa"]}],
     "order": {"trips.energy_per_100km": "asc"}, "limit": 100}
    Members are always "cube.member". Cube joins cubes for you along the model's joins.
    Numbers come back as strings."""
    query = {"limit": MAX_ROWS, **query}
    query["limit"] = min(int(query["limit"]), MAX_ROWS)
    body = _call("POST", "load", {"query": query})
    return json.dumps({"query": query, "rows": body.get("data", [])}, indent=1, default=str)


@mcp.tool()
def cube_sql(query: dict) -> str:
    """Show the SQL that Cube generates for a semantic query (same format as cube_query), without
    running it. Useful to explain how a metric is calculated."""
    body = _call("POST", "sql", {"query": query})
    sql = body.get("sql", {}).get("sql", body)
    return json.dumps({"sql": sql}, indent=1, default=str)


if __name__ == "__main__":
    mcp.run()
