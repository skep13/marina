import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest


@pytest.fixture(autouse=True)
def _her_state_stays_out_of_the_repo(tmp_path, monkeypatch):
    """Her mood and the like are saved after every exchange; tests keep theirs
    in a temporary folder and start from her usual self."""
    from process import state
    monkeypatch.setattr(state, "_path", lambda: tmp_path / "state.json")
    monkeypatch.setattr(state.shared, "enabled", lambda: False)
    state.forget()
    yield
    state.forget()
