import json
from pathlib import Path

from scripts.research.generation_feedback import maybe_mark_candidate_review_exhausted, record_generation_feedback


def write_json(path: Path, payload: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_record_generation_feedback_marks_generated_but_ineligible(tmp_path):
    state = tmp_path / "state"
    reports = tmp_path / "reports"
    event = record_generation_feedback(
        state_dir=state,
        reports_dir=reports,
        phase="value_factory",
        generation_result={"generated": 3, "reason": "test"},
        eligibility_before={"eligible": False, "reason": "empty"},
        eligibility_after={"eligible": False, "reason": "all blocked"},
    )
    assert event["warning"] == "generated_but_no_eligible_hypothesis"
    assert (reports / "generation_feedback.md").exists()


def test_maybe_mark_candidate_review_exhausted_when_all_consumed(tmp_path):
    state = tmp_path / "state"
    bank = tmp_path / "bibliography" / "hypothesis_bank.jsonl"
    write_json(state / "candidate_under_review.json", {"status": "active", "candidate_run_id": "EXP_999"})
    (state / "consumed_hypotheses.jsonl").parent.mkdir(parents=True, exist_ok=True)
    (state / "consumed_hypotheses.jsonl").write_text('{"hypothesis_id":"HYP_REVIEW_EXP_999_TOPN_7_V1"}\n', encoding="utf-8")
    bank.parent.mkdir(parents=True, exist_ok=True)
    bank.write_text(json.dumps({
        "hypothesis_id": "HYP_REVIEW_EXP_999_TOPN_7_V1",
        "family": "candidate_under_review_drawdown_refinement",
        "status": "candidate",
    }) + "\n", encoding="utf-8")

    result = maybe_mark_candidate_review_exhausted(
        state_dir=state,
        hypothesis_bank=bank,
        generation_result={"generated": 0, "reason": "no_new"},
    )
    assert result["candidate_review_status"] == "review_exhausted"
    updated = json.loads((state / "candidate_under_review.json").read_text(encoding="utf-8"))
    assert updated["status"] == "review_exhausted"
