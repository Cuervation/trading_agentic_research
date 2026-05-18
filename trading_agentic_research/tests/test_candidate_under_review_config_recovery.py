import json
from pathlib import Path

from scripts.research.candidate_under_review import refresh_candidate_under_review


def write_json(path: Path, payload: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_candidate_under_review_recovers_config_from_manifest(tmp_path):
    state = tmp_path / "state"
    runs = tmp_path / "runs"
    configs = tmp_path / "configs" / "generated"
    cfg = configs / "HYP_REFINE_AUTO002_TOPN_6_V1.json"
    write_json(cfg, {"strategy_id": "HYP_REFINE_AUTO002_TOPN_6_V1", "hypothesis_id": "HYP_REFINE_AUTO002_TOPN_6_V1", "entry_rule": {"top_n": 6}})
    write_json(state / "current_parent.json", {"current_parent_run_id": "AUTO_002", "current_parent_config_path": "configs/generated/HYP_AUTO_TIME_SERIES_MOMENTUM_SEED.json"})
    write_json(state / "champion_runs.json", {"baseline_candidate_run_id": "EXP_044", "promotion_candidates": []})
    write_json(runs / "EXP_044" / "run_manifest.json", {"strategy_id": "HYP_REFINE_AUTO002_TOPN_6_V1", "hypothesis_id": "HYP_REFINE_AUTO002_TOPN_6_V1", "strategy_config_path": "configs/generated/HYP_REFINE_AUTO002_TOPN_6_V1.json"})
    write_json(runs / "EXP_044" / "audit.json", {"decision": "promoted_candidate", "can_move_parent": True})

    result = refresh_candidate_under_review(state_dir=state, runs_dir=runs, repo_root=tmp_path)
    assert result["status"] == "active"
    assert result["candidate_run_id"] == "EXP_044"
    assert result["strategy_config_path"] == "configs/generated/HYP_REFINE_AUTO002_TOPN_6_V1.json"


def test_candidate_under_review_rebuilds_config_from_hypothesis_bank(tmp_path):
    state = tmp_path / "state"
    runs = tmp_path / "runs"
    generated = tmp_path / "configs" / "generated"
    registry = tmp_path / "configs" / "strategy_registry.json"
    bank = tmp_path / "bibliography" / "hypothesis_bank.jsonl"
    parent = generated / "PARENT.json"
    write_json(parent, {"strategy_id": "PARENT", "hypothesis_id": "PARENT", "entry_rule": {"top_n": 15}, "exit_rule": {"rank_threshold": 20}})
    write_json(state / "current_parent.json", {"current_parent_run_id": "AUTO_002", "current_parent_config_path": "configs/generated/PARENT.json"})
    write_json(state / "champion_runs.json", {"baseline_candidate_run_id": "EXP_044", "promotion_candidates": []})
    write_json(runs / "EXP_044" / "run_manifest.json", {"strategy_id": "HYP_REFINE_AUTO002_TOPN_6_V1", "hypothesis_id": "HYP_REFINE_AUTO002_TOPN_6_V1"})
    write_json(runs / "EXP_044" / "audit.json", {"decision": "promoted_candidate", "can_move_parent": True})
    bank.parent.mkdir(parents=True, exist_ok=True)
    bank.write_text(json.dumps({
        "hypothesis_id": "HYP_REFINE_AUTO002_TOPN_6_V1",
        "family": "time_series_momentum_refinement",
        "bibliography_basis": [{"source_id": "x"}],
        "empirical_basis": [{"run_id": "AUTO_002"}],
        "strategy_overrides": {"strategy_id": "HYP_REFINE_AUTO002_TOPN_6_V1", "entry_rule": {"top_n": 6}},
    }) + "\n", encoding="utf-8")

    result = refresh_candidate_under_review(
        state_dir=state,
        runs_dir=runs,
        repo_root=tmp_path,
        strategy_registry_path=registry,
        generated_configs_dir=generated,
        hypothesis_bank_path=bank,
    )
    assert result["status"] == "active"
    assert (generated / "HYP_REFINE_AUTO002_TOPN_6_V1.json").exists()
