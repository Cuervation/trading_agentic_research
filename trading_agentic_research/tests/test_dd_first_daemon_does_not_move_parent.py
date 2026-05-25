import json

import pytest

from scripts.run_dd_first_autonomous_daemon import _state_snapshot, assert_parent_baseline_unchanged


def test_daemon_parent_baseline_lock_detection(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    (state / "current_parent.json").write_text(json.dumps({"locked": True}), encoding="utf-8")
    (state / "current_baseline.json").write_text(json.dumps({"baseline": "x"}), encoding="utf-8")
    snapshot = _state_snapshot(str(state))

    assert_parent_baseline_unchanged(str(state), snapshot)

    (state / "current_parent.json").write_text(json.dumps({"locked": False}), encoding="utf-8")
    with pytest.raises(RuntimeError):
        assert_parent_baseline_unchanged(str(state), snapshot)
