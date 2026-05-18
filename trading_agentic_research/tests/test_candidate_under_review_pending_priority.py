import json
from pathlib import Path

from scripts.research.candidate_under_review import refresh_candidate_under_review


def write_json(path: Path, payload: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_candidate_under_review_prefers_pending_parent_candidate(tmp_path):
    state = tmp_path / "state"
    runs = tmp_path / "runs"
    cfg = tmp_path / "configs" / "generated" / "HYP_PENDING.json"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    write_json(cfg, {"strategy_id": "HYP_PENDING", "hypothesis_id": "HYP_PENDING"})
    write_json(state / "champion_runs.json", {
        "official_parent_run_id": "AUTO_002",
        "current_parent_run_id": "AUTO_002",
        "best_champion_run_id": "EXP_999",
        "pending_parent_candidate_run_id": "EXP_999",
        "baseline_candidate_run_id": "EXP_052",
        "champion_runs": [{"run_id": "AUTO_002", "strategy_id": "AUTO"}],
    })
    write_json(state / "current_parent.json", {"current_parent_run_id": "AUTO_002"})
    write_json(runs / "EXP_999" / "run_manifest.json", {
        "strategy_id": "HYP_PENDING",
        "hypothesis_id": "HYP_PENDING",
        "strategy_config_path": "configs/generated/HYP_PENDING.json",
    })
    write_json(runs / "EXP_999" / "audit.json", {"decision": "promoted_candidate"})

    out = refresh_candidate_under_review(
        state_dir=state,
        runs_dir=runs,
        repo_root=tmp_path,
        generated_configs_dir="configs/generated",
    )
    assert out["candidate_run_id"] == "EXP_999"
    assert out["status"] == "active"
