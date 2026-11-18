"""Checks that every service of the data stack answers. --wait N keeps retrying for up to N seconds.

    uv run python scripts/check_stack.py [--wait 300]
"""

import os
import socket
import sys
import time
from pathlib import Path

import httpx
import psycopg
from dotenv import load_dotenv

PROJECT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT / ".env")


def postgres() -> str:
    uri = f"postgresql://analyst:{os.getenv('ANALYST_PASSWORD', 'analyst')}@localhost:{os.getenv('POSTGRES_PORT', '5432')}/voltway"
    with psycopg.connect(uri, connect_timeout=3) as conn:
        trips = conn.execute("SELECT count(*) FROM fleet.trips").fetchone()[0]
    return f"{trips} trips"


def http(url: str) -> str:
    response = httpx.get(url, timeout=5)
    response.raise_for_status()
    return f"HTTP {response.status_code}"


def port(number: str) -> str:
    with socket.create_connection(("localhost", int(number)), timeout=3):
        return "listening"


CHECKS = {
    "Postgres": postgres,
    "Cube API": lambda: http(f"http://localhost:{os.getenv('CUBE_PORT', '4001')}/readyz"),
    "DuckDB MCP": lambda: port(os.getenv("DUCKDB_MCP_PORT", "8001")),
    "Postgres MCP": lambda: port(os.getenv("POSTGRES_MCP_PORT", "8002")),
    "DataHub GMS": lambda: http(f"{os.getenv('DATAHUB_GMS_URL', 'http://localhost:8080')}/health"),
    "DataHub UI": lambda: http(f"http://localhost:{os.getenv('DATAHUB_MAPPED_FRONTEND_PORT', '9002')}/"),
}


def run_checks() -> dict[str, str | None]:
    """Return {service: None if OK, else the error}."""
    results = {}
    for name, check in CHECKS.items():
        try:
            results[name] = None, check()
        except Exception as error:  # noqa: BLE001
            results[name] = f"{type(error).__name__}: {error}"[:120], None
    return results


def main() -> None:
    wait = int(sys.argv[sys.argv.index("--wait") + 1]) if "--wait" in sys.argv else 0
    deadline = time.time() + wait
    while True:
        results = run_checks()
        failing = [name for name, (error, _) in results.items() if error]
        if not failing or time.time() > deadline:
            break
        print(f"   waiting for: {', '.join(failing)}")
        time.sleep(10)
    for name, (error, detail) in results.items():
        print(f"{'❌' if error else '✅'} {name:<13} {error or detail}")
    sys.exit(1 if failing else 0)


if __name__ == "__main__":
    main()
