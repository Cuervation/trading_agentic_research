from __future__ import annotations

import json
from pathlib import Path

from scripts.research.manual_parent_governance import enforce_manual_parent_governance
from scripts.research.parent_state import sync_current_parent_state
from scripts.research.candidate_under_review import refresh_candidate_under_review


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def test_manual_lock_prevents_best_champion_from_becoming_parent(tmp_path: Path) -> None:
    state = tmp_path / "state"
    configs = tmp_path / "configs" / "generated"
    configs.mkdir(parents=True)
    write_json(configs / "PARENT_STRAT.json", {"strategy_id": "PARENT_STRAT", "hypothesis_id": "PARENT_STRAT"})
    write_json(configs / "NEW_BEST_STRAT.json", {"strategy_id": "NEW_BEST_STRAT", "hypothesis_id": "NEW_BEST_STRAT"})
    write_json(tmp_path / "configs" / "strategy_registry.json", {
        "strategies": [
            {"strategy_id": "PARENT_STRAT", "config_path": "configs/generated/PARENT_STRAT.json"},
            {"strategy_id": "NEW_BEST_STRAT", "config_path": "configs/generated/NEW_BEST_STRAT.json"},
        ]
    })
    write_json(state / "champion_runs.json", {
        "best_champion_run_id": "EXP_999",
        "current_parent_run_id": "AUTO_002",
        "champion_runs": [
            {"run_id": "AUTO_002", "strategy_id": "PARENT_STRAT", "hypothesis_id": "PARENT_STRAT"},
            {"run_id": "EXP_999", "strategy_id": "NEW_BEST_STRAT", "hypothesis_id": "NEW_BEST_STRAT"},
        ],
        "promotion_candidates": [],
    })

    result = enforce_manual_parent_governance(
        state_dir=state,
        strategy_registry_path=tmp_path / "configs" / "strategy_registry.json",
        official_parent="AUTO_002",
        repo_root=tmp_path,
    )
    assert result["status"] == "ok"
    assert result["pending_parent_candidate_run_id"] == "EXP_999"

    synced = sync_current_parent_state(
        state_dir=state,
        strategy_registry_path=tmp_path / "configs" / "strategy_registry.json",
        generated_configs_dir=tmp_path / "configs" / "generated",
        prefer_best_champion=True,
        repo_root=tmp_path,
    )
    assert synced["current_parent_run_id"] == "AUTO_002"
    assert synced["pending_parent_candidate_run_id"] == "EXP_999"
    assert synced["current_parent_config_path"] == "configs/generated/PARENT_STRAT.json"


def test_candidate_under_review_prefers_pending_parent_candidate(tmp_path: Path) -> None:
    state = tmp_path / "state"
    runs = tmp_path / "runs"
    cfg = tmp_path / "configs" / "generated" / "NEW_BEST_STRAT.json"
    write_json(cfg, {"strategy_id": "NEW_BEST_STRAT", "hypothesis_id": "NEW_BEST_STRAT", "entry_rule": {"top_n": 7}})
    write_json(tmp_path / "configs" / "strategy_registry.json", {
        "strategies": [
            {"strategy_id": "NEW_BEST_STRAT", "config_path": "configs/generated/NEW_BEST_STRAT.json"},
        ]
    })
    write_json(state / "current_parent.json", {
        "current_parent_run_id": "AUTO_002",
        "pending_parent_candidate_run_id": "EXP_999",
    })
    write_json(state / "champion_runs.json", {
        "current_parent_run_id": "AUTO_002",
        "best_champion_run_id": "EXP_999",
        "baseline_candidate_run_id": "EXP_052",
        "champion_runs": [
            {"run_id": "EXP_999", "strategy_id": "NEW_BEST_STRAT", "hypothesis_id": "NEW_BEST_STRAT"},
        ],
        "promotion_candidates": [
            {"run_id": "EXP_052", "strategy_id": "OLD_CANDIDATE", "hypothesis_id": "OLD_CANDIDATE"},
        ],
    })
    write_json(runs / "EXP_999" / "run_manifest.json", {
        "strategy_id": "NEW_BEST_STRAT",
        "hypothesis_id": "NEW_BEST_STRAT",
        "strategy_config_path": "configs/generated/NEW_BEST_STRAT.json",
    })
    write_json(runs / "EXP_999" / "audit.json", {"decision": "promoted_candidate", "can_move_parent": True})

    result = refresh_candidate_under_review(
        state_dir=state,
        runs_dir=runs,
        repo_root=tmp_path,
        strategy_registry_path=tmp_path / "configs" / "strategy_registry.json",
        generated_configs_dir=tmp_path / "configs" / "generated",
        hypothesis_bank_path=tmp_path / "bibliography" / "hypothesis_bank.jsonl",
    )
    assert result["status"] == "active"
    assert result["candidate_run_id"] == "EXP_999"
    assert result["strategy_config_path"] == "configs/generated/NEW_BEST_STRAT.json"
