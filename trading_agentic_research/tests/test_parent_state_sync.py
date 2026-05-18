import json
from pathlib import Path

from scripts.research.parent_state import sync_current_parent_state, resolve_current_parent_config_path


def test_sync_current_parent_uses_best_champion_and_resolves_config(tmp_path):
    state = tmp_path / "state"
    configs = tmp_path / "configs" / "generated"
    state.mkdir(parents=True)
    configs.mkdir(parents=True)
    (configs / "HYP_PARENT.json").write_text(json.dumps({"strategy_id": "HYP_PARENT", "hypothesis_id": "HYP_PARENT"}), encoding="utf-8")
    (tmp_path / "configs").mkdir(exist_ok=True)
    (tmp_path / "configs" / "strategy_registry.json").write_text(
        json.dumps({"strategies": [{"strategy_id": "HYP_PARENT", "config_path": "configs/generated/HYP_PARENT.json"}]}),
        encoding="utf-8",
    )
    (state / "champion_runs.json").write_text(
        json.dumps(
            {
                "best_champion_run_id": "AUTO_002",
                "current_parent_run_id": "EXP_001",
                "champion_runs": [
                    {"run_id": "AUTO_002", "strategy_id": "HYP_PARENT", "hypothesis_id": "HYP_PARENT"}
                ],
                "promotion_candidates": [],
                "secondary_candidates": [],
                "defensive_secondary_candidates": [],
            }
        ),
        encoding="utf-8",
    )

    payload = sync_current_parent_state(
        state_dir="state",
        strategy_registry_path="configs/strategy_registry.json",
        generated_configs_dir="configs/generated",
        repo_root=tmp_path,
    )

    assert payload["current_parent_run_id"] == "AUTO_002"
    assert payload["current_parent_strategy_id"] == "HYP_PARENT"
    assert payload["current_parent_config_path"] == "configs/generated/HYP_PARENT.json"
    assert resolve_current_parent_config_path(state_dir="state", repo_root=tmp_path) == "configs/generated/HYP_PARENT.json"
