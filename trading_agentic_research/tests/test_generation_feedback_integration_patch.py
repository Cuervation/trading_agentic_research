from __future__ import annotations

import json
from pathlib import Path

from scripts.research.generation_feedback import record_generation_feedback
from scripts.research.candidate_under_review import refresh_candidate_under_review


def test_generation_feedback_counts_rows_written(tmp_path: Path):
    state = tmp_path / "state"
    reports = tmp_path / "reports"
    event = record_generation_feedback(
        state_dir=state,
        reports_dir=reports,
        phase="paper_searcher",
        generation_result={"rows_written": 3, "reason": "offline_seed"},
        eligibility_before={"eligible": False, "reason": "none"},
        eligibility_after={"eligible": False, "reason": "still_none"},
    )
    assert event["generated"] == 3
    assert event["warning"] == "generated_but_no_eligible_hypothesis"
    assert (state / "generation_feedback.json").exists()
    assert (reports / "generation_feedback.md").exists()


def test_refresh_candidate_under_review_preserves_exhausted(tmp_path: Path):
    state = tmp_path / "state"
    runs = tmp_path / "runs"
    state.mkdir()
    runs.mkdir()
    (state / "current_parent.json").write_text(json.dumps({
        "current_parent_run_id": "AUTO_002",
        "pending_parent_candidate_run_id": "EXP_054",
    }), encoding="utf-8")
    (state / "candidate_under_review.json").write_text(json.dumps({
        "status": "review_exhausted",
        "reason": "all_candidate_review_hypotheses_blocked_or_consumed",
        "candidate_run_id": "EXP_054",
    }), encoding="utf-8")

    result = refresh_candidate_under_review(
        state_dir=state,
        runs_dir=runs,
        repo_root=tmp_path,
    )

    assert result["status"] == "review_exhausted"
    assert result["candidate_run_id"] == "EXP_054"
