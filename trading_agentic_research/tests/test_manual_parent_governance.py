from __future__ import annotations

import json
from pathlib import Path

from scripts.research.parent_state import sync_current_parent_state
from scripts.research.manual_parent_governance import enforce_manual_parent


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def test_sync_preserves_current_parent_when_new_best_exists(tmp_path: Path) -> None:
    state = tmp_path / "state"
    cfg = tmp_path / "configs" / "generated"
    cfg.mkdir(parents=True)
    write_json(cfg / "AUTO.json", {"strategy_id": "AUTO_STRAT", "hypothesis_id": "AUTO_STRAT"})
    write_json(cfg / "NEW.json", {"strategy_id": "NEW_STRAT", "hypothesis_id": "NEW_STRAT"})
    write_json(tmp_path / "configs" / "strategy_registry.json", {"strategies": [
        {"strategy_id": "AUTO_STRAT", "config_path": "configs/generated/AUTO.json"},
        {"strategy_id": "NEW_STRAT", "config_path": "configs/generated/NEW.json"},
    ]})
    write_json(state / "champion_runs.json", {
        "best_champion_run_id": "EXP_054",
        "current_parent_run_id": "AUTO_002",
        "champion_runs": [
            {"run_id": "AUTO_002", "strategy_id": "AUTO_STRAT", "hypothesis_id": "AUTO_STRAT"},
            {"run_id": "EXP_054", "strategy_id": "NEW_STRAT", "hypothesis_id": "NEW_STRAT"},
        ],
    })
    write_json(state / "current_parent.json", {
        "current_parent_run_id": "AUTO_002",
        "current_parent_strategy_id": "AUTO_STRAT",
        "current_parent_hypothesis_id": "AUTO_STRAT",
        "current_parent_config_path": "configs/generated/AUTO.json",
    })

    result = sync_current_parent_state(
        state_dir="state",
        strategy_registry_path="configs/strategy_registry.json",
        generated_configs_dir="configs/generated",
        repo_root=tmp_path,
    )

    assert result["current_parent_run_id"] == "AUTO_002"
    assert result["best_champion_run_id"] == "EXP_054"
    assert result["pending_parent_candidate_run_id"] == "EXP_054"
    assert result["parent_promotion_blocked"] is True


def test_manual_parent_governance_repairs_parent(tmp_path: Path) -> None:
    state = tmp_path / "state"
    cfg = tmp_path / "configs" / "generated"
    cfg.mkdir(parents=True)
    write_json(cfg / "AUTO.json", {"strategy_id": "AUTO_STRAT", "hypothesis_id": "AUTO_STRAT"})
    write_json(cfg / "NEW.json", {"strategy_id": "NEW_STRAT", "hypothesis_id": "NEW_STRAT"})
    write_json(tmp_path / "configs" / "strategy_registry.json", {"strategies": [
        {"strategy_id": "AUTO_STRAT", "config_path": "configs/generated/AUTO.json"},
        {"strategy_id": "NEW_STRAT", "config_path": "configs/generated/NEW.json"},
    ]})
    write_json(state / "champion_runs.json", {
        "best_champion_run_id": "EXP_054",
        "current_parent_run_id": "EXP_054",
        "champion_runs": [
            {"run_id": "AUTO_002", "strategy_id": "AUTO_STRAT", "hypothesis_id": "AUTO_STRAT"},
            {"run_id": "EXP_054", "strategy_id": "NEW_STRAT", "hypothesis_id": "NEW_STRAT"},
        ],
    })
    write_json(state / "candidate_under_review.json", {"official_parent_run_id": "AUTO_002"})
    write_json(state / "current_parent.json", {
        "current_parent_run_id": "EXP_054",
        "current_parent_strategy_id": "NEW_STRAT",
        "current_parent_hypothesis_id": "NEW_STRAT",
        "current_parent_config_path": "configs/generated/NEW.json",
    })

    result = enforce_manual_parent(
        state_dir="state",
        strategy_registry="configs/strategy_registry.json",
        repo_root=tmp_path,
    )

    assert result["status"] == "ok"
    assert result["official_parent"] == "AUTO_002"
    current = json.loads((state / "current_parent.json").read_text(encoding="utf-8"))
    assert current["current_parent_run_id"] == "AUTO_002"
    assert current["pending_parent_candidate_run_id"] == "EXP_054"
    assert current["parent_promotion_blocked"] is True
