"""Shared setup for the unit tests. They need no Docker stack, no MCP servers and no API keys."""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # import middleware/ and data_agent.py
os.environ["LANGSMITH_TRACING"] = "false"                           # never send test runs to LangSmith
