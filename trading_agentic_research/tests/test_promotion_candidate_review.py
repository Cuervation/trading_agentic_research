import json
from scripts.research.promotion_candidate_review import write_promotion_candidate_review


def test_promotion_candidate_review_writes_report(tmp_path):
    state = tmp_path / "state"
    runs = tmp_path / "runs"
    reports = tmp_path / "reports"
    state.mkdir()
    (state / "current_parent.json").write_text(json.dumps({"current_parent_run_id": "AUTO_002"}), encoding="utf-8")
    (state / "champion_runs.json").write_text(json.dumps({"baseline_candidate_run_id": "EXP_044"}), encoding="utf-8")
    for run_id, cagr in [("AUTO_002", 52), ("EXP_044", 59)]:
        rd = runs / run_id
        rd.mkdir(parents=True)
        (rd / "metrics.json").write_text(json.dumps({"strategy": {"cagr_pct": cagr, "max_drawdown_pct": -25}}), encoding="utf-8")
        (rd / "spy_comparison_summary.json").write_text(json.dumps({"years_beating_spy": 7, "years_losing_to_spy": 0}), encoding="utf-8")
        (rd / "audit.json").write_text(json.dumps({"decision": "x"}), encoding="utf-8")
    payload = write_promotion_candidate_review(state_dir=state, runs_dir=runs, reports_dir=reports)
    assert payload["promotion_candidate_run_id"] == "EXP_044"
    assert (reports / "promotion_candidate_review.md").exists()
