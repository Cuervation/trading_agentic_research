import json
from pathlib import Path

from scripts.research.sync_strategy_registry import sync_strategy_registry


def test_sync_strategy_registry_registers_current_parent(tmp_path):
    cfg = tmp_path / "configs" / "generated" / "PARENT.json"
    cfg.parent.mkdir(parents=True)
    cfg.write_text(json.dumps({"strategy_id": "PARENT", "strategy_family": "trend_following", "benchmark_ticker": "SPY"}), encoding="utf-8")
    registry = tmp_path / "configs" / "strategy_registry.json"
    registry.write_text(json.dumps({"project_name": "x", "version": 1, "strategies": []}), encoding="utf-8")
    state = tmp_path / "state"
    state.mkdir()
    (state / "current_parent.json").write_text(json.dumps({
        "current_parent_run_id": "AUTO_002",
        "current_parent_strategy_id": "PARENT",
        "current_parent_config_path": "configs/generated/PARENT.json",
    }), encoding="utf-8")
    (state / "champion_runs.json").write_text(json.dumps({"champion_runs": []}), encoding="utf-8")
    result = sync_strategy_registry(registry_path="configs/strategy_registry.json", state_dir="state", repo_root=tmp_path)
    assert "PARENT" in result["updated_strategy_ids"]
    loaded = json.loads(registry.read_text(encoding="utf-8"))
    assert loaded["strategies"][0]["status"] == "current_parent"
