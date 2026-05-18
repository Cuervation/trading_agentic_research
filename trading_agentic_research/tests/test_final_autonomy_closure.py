import json
import subprocess
import sys
from pathlib import Path

from scripts.research.candidate_under_review import refresh_candidate_under_review
from scripts.research.generation_feedback import maybe_mark_candidate_review_exhausted, record_generation_feedback


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


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
