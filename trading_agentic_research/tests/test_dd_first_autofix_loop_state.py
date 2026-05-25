from pathlib import Path

from scripts.run_dd_first_autofix_loop import _load_loop_state, _save_loop_state


def test_dd_first_autofix_loop_state_roundtrip(tmp_path):
    state_dir = tmp_path / "state"
    state = _load_loop_state(str(state_dir))
    state["completed_real_runs"] = 2
    state["failed_attempts"] = 1
    _save_loop_state(str(state_dir), state)

    loaded = _load_loop_state(str(state_dir))

    assert loaded["completed_real_runs"] == 2
    assert loaded["failed_attempts"] == 1
    assert "last_updated_at" in loaded
