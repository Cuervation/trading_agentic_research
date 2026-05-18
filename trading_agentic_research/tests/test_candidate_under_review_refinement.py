import json
from pathlib import Path

from scripts.research.candidate_under_review import refresh_candidate_under_review
from scripts.research.candidate_review_refinement_factory import generate_candidate_review_hypotheses, read_jsonl


def test_candidate_under_review_generates_refinements(tmp_path):
    state = tmp_path / "state"
    runs = tmp_path / "runs"
    configs = tmp_path / "configs" / "generated"
    state.mkdir(parents=True)
    configs.mkdir(parents=True)
    (state / "champion_runs.json").write_text(json.dumps({"baseline_candidate_run_id": "EXP_044"}), encoding="utf-8")
    (state / "current_parent.json").write_text(json.dumps({"current_parent_run_id": "AUTO_002", "current_parent_strategy_id": "PARENT"}), encoding="utf-8")

    cfg = configs / "EXP_044.json"
    cfg.write_text(json.dumps({"strategy_id": "EXP_044_CFG", "hypothesis_id": "HYP_EXP_044", "entry_rule": {"top_n": 6}, "exit_rule": {"rank_threshold": 20}}), encoding="utf-8")

    run = runs / "EXP_044"
    run.mkdir(parents=True)
    (run / "run_manifest.json").write_text(json.dumps({"strategy_config_path": str(cfg), "strategy_id": "EXP_044_CFG", "hypothesis_id": "HYP_EXP_044"}), encoding="utf-8")
    (run / "metrics.json").write_text(json.dumps({"strategy": {"cagr_pct": 59, "max_drawdown_pct": -27}}), encoding="utf-8")
    (run / "spy_comparison_summary.json").write_text(json.dumps({"years_beating_spy": 7, "years_losing_to_spy": 0}), encoding="utf-8")
    (run / "audit.json").write_text(json.dumps({"decision": "promoted_candidate", "can_move_parent": True}), encoding="utf-8")

    refreshed = refresh_candidate_under_review(state_dir=state, runs_dir=runs, repo_root=tmp_path)
    assert refreshed["status"] == "active"

    bank = tmp_path / "bibliography" / "hypothesis_bank.jsonl"
    bank.parent.mkdir()
    result = generate_candidate_review_hypotheses(state_dir=state, hypothesis_bank_path=bank)
    assert result["generated"] >= 1
    rows = read_jsonl(bank)
    assert any(str(row["hypothesis_id"]).startswith("HYP_REVIEW_EXP_044") for row in rows)
