import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).parent.parent), str(Path(__file__).parent)]

import fakes  # noqa: E402,F401  (must load before the agents: sets the fake models)
import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def runs_in_tmp(tmp_path, monkeypatch):
    from core import state
    from evals import run_evals

    monkeypatch.setattr(state, "RUNS_DIR", tmp_path)
    monkeypatch.setattr(run_evals, "RUNS_DIR", tmp_path)
    monkeypatch.setattr(run_evals, "RESULTS", tmp_path / "results.md")
