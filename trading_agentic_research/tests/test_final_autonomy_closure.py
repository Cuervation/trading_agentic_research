import json
import subprocess
import sys
from pathlib import Path

from scripts.research.candidate_under_review import refresh_candidate_under_review
from scripts.research.candidate_review_learning import reset_candidate_review_learning_for_candidate
from scripts.research.feature_space_expansion_factory import generate_feature_space_hypotheses
from scripts.research.generation_feedback import maybe_mark_candidate_review_exhausted, record_generation_feedback


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def append_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


def valid_review_hypothesis(hid: str) -> dict:
    return {
        "hypothesis_id": hid,
        "family": "candidate_under_review_drawdown_refinement",
        "claim": "test candidate review hypothesis",
        "causal_mechanism": "test",
        "bibliography_basis": [{"source_id": "test", "title": "test"}],
        "empirical_basis": [{"run_id": "EXP_054", "reason": "test"}],
        "features_required": [],
        "status": "candidate",
        "required_spy_comparison": "monthly_and_yearly",
        "axis": "candidate_under_review_drawdown_refinement",
        "falsification_rule": "Reject on duplicate/no-effect.",
        "strategy_overrides": {"ranking": {"field": "ret_26w_pct", "order": "desc"}},
    }


def test_candidate_under_review_does_not_reactivate_exhausted_same_candidate(tmp_path):
    state = tmp_path / "state"
    runs = tmp_path / "runs"
    write_json(state / "current_parent.json", {"current_parent_run_id": "AUTO_002", "pending_parent_candidate_run_id": "EXP_054"})
    write_json(state / "champion_runs.json", {"pending_parent_candidate_run_id": "EXP_054", "current_parent_run_id": "AUTO_002"})
    write_json(state / "candidate_under_review.json", {"status": "review_exhausted", "candidate_run_id": "EXP_054", "reason": "done"})

    result = refresh_candidate_under_review(state_dir=state, runs_dir=runs, repo_root=tmp_path)

    assert result["status"] == "review_exhausted"
    assert result["candidate_run_id"] == "EXP_054"


def test_maybe_mark_candidate_review_exhausted_when_no_new_candidates(tmp_path):
    state = tmp_path / "state"
    bank = tmp_path / "bibliography" / "hypothesis_bank.jsonl"
    write_json(state / "candidate_under_review.json", {"status": "active", "candidate_run_id": "EXP_054"})
    write_json(state / "candidate_review_learning.json", {"exhausted_axes": []})
    bank.parent.mkdir(parents=True, exist_ok=True)
    bank.write_text("", encoding="utf-8")

    result = maybe_mark_candidate_review_exhausted(
        state_dir=state,
        hypothesis_bank=bank,
        generation_result={"generated": 0, "reason": "no_new_candidate_under_review_hypotheses"},
    )
    refreshed = json.loads((state / "candidate_under_review.json").read_text(encoding="utf-8"))

    assert result["candidate_review_status"] == "review_exhausted"
    assert refreshed["status"] == "review_exhausted"


def test_maybe_mark_candidate_review_exhausted_uses_selector_consumed_filter(tmp_path):
    state = tmp_path / "state"
    bank = tmp_path / "bibliography" / "hypothesis_bank.jsonl"
    hid = "HYP_REVIEW_EXP_054_TOPN_6_V1"
    write_json(state / "candidate_under_review.json", {"status": "active", "candidate_run_id": "EXP_054"})
    write_json(state / "current_parent.json", {"current_parent_run_id": "AUTO_002", "current_parent_hypothesis_id": "HYP_AUTO_TIME_SERIES_MOMENTUM_SEED"})
    write_json(state / "candidate_review_learning.json", {"version": 1, "candidate_run_id": "EXP_054", "attempts": [], "axis_stats": {}, "exhausted_axes": []})
    append_jsonl(bank, [valid_review_hypothesis(hid)])
    append_jsonl(state / "consumed_hypotheses.jsonl", [{"hypothesis_id": hid, "run_id": "EXP_999"}])

    result = maybe_mark_candidate_review_exhausted(
        state_dir=state,
        hypothesis_bank=bank,
        generation_result={"generated": 0, "reason": "no_new_candidate_under_review_hypotheses"},
    )
    refreshed = json.loads((state / "candidate_under_review.json").read_text(encoding="utf-8"))

    assert result["candidate_review_status"] == "review_exhausted"
    assert result["candidate_review_selectable_remaining"] == []
    assert refreshed["reason"] == "no_selector_eligible_candidate_review_hypotheses"


def test_candidate_review_learning_resets_when_candidate_changes(tmp_path):
    state = tmp_path / "state"
    write_json(state / "candidate_review_learning.json", {
        "version": 1,
        "candidate_run_id": "EXP_044",
        "official_parent_run_id": "AUTO_002",
        "attempts": [{"run_id": "EXP_050", "axis": "exit"}],
        "axis_stats": {"exit": {"attempts": 1}},
        "exhausted_axes": ["exit"],
    })

    result = reset_candidate_review_learning_for_candidate(
        state_dir=state,
        candidate_run_id="EXP_054",
        official_parent_run_id="AUTO_002",
    )
    learning = json.loads((state / "candidate_review_learning.json").read_text(encoding="utf-8"))

    assert result["reset"] is True
    assert learning["candidate_run_id"] == "EXP_054"
    assert learning["attempts"] == []
    assert learning["axis_stats"] == {}
    assert learning["exhausted_axes"] == []


def test_feature_space_expansion_factory_generates_supported_hypothesis(tmp_path):
    state = tmp_path / "state"
    bank = tmp_path / "bibliography" / "hypothesis_bank.jsonl"
    parent = tmp_path / "configs" / "generated" / "parent.json"
    weekly = tmp_path / "data" / "weekly.csv"
    write_json(state / "current_parent.json", {
        "current_parent_run_id": "AUTO_002",
        "current_parent_hypothesis_id": "HYP_AUTO_TIME_SERIES_MOMENTUM_SEED",
    })
    write_json(parent, {
        "strategy_id": "HYP_AUTO_TIME_SERIES_MOMENTUM_SEED",
        "ranking": {"field": "close_vs_sma52w_pct", "order": "desc"},
        "entry_rule": {"top_n": 8},
        "exit_rule": {"rank_threshold": 20},
    })
    weekly.parent.mkdir(parents=True, exist_ok=True)
    weekly.write_text("date,ticker,close,ret_13w_pct,ret_26w_pct,channel_r2,close_vs_sma20w_pct\n", encoding="utf-8")
    write_json(state / "data_paths_resolved.json", {"weekly_file": str(weekly)})
    bank.parent.mkdir(parents=True, exist_ok=True)
    bank.write_text("", encoding="utf-8")

    result = generate_feature_space_hypotheses(
        parent_strategy_config_path=parent,
        hypothesis_bank_path=bank,
        state_dir=state,
        max_new=3,
    )

    assert result["generated"] >= 1
    rows = bank.read_text(encoding="utf-8").splitlines()
    assert rows
    assert "HYP_FSPACE_AUTO_002" in rows[0]


def test_record_generation_feedback_writes_report(tmp_path):
    event = record_generation_feedback(
        state_dir=tmp_path / "state",
        reports_dir=tmp_path / "reports",
        phase="value_factory",
        generation_result={"generated": 2, "reason": "test"},
        eligibility_after={"eligible": False, "reason": "blocked"},
    )
    assert event["warning"] == "generated_but_no_eligible_hypothesis"
    assert (tmp_path / "state" / "generation_feedback.json").exists()
    assert (tmp_path / "reports" / "generation_feedback.md").exists()


def test_autonomous_wrapper_uses_generation_feedback_integration():
    content = Path("scripts/run_research_batch_autonomous.py").read_text(encoding="utf-8")
    assert "record_generation_feedback" in content
    assert "maybe_mark_candidate_review_exhausted" in content
    assert "prefer_best_champion=False" in content
    assert "generate_feature_space_hypotheses" in content
    assert "--allow-parent-update" not in subprocess.list2cmdline([sys.executable, "scripts/run_research_batch_autonomous.py", "--max-runs", "1"])
