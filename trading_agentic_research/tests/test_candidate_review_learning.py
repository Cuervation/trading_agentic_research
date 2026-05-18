import json

from scripts.research.candidate_review_learning import (
    candidate_review_priority,
    infer_candidate_review_axis,
    is_candidate_review_hypothesis_blocked,
    update_candidate_review_learning_from_run,
)


def test_candidate_review_priority_prefers_topn():
    topn = {"hypothesis_id": "HYP_REVIEW_EXP_044_TOPN_7_V1", "family": "candidate_under_review_topn_refinement"}
    trailing = {"hypothesis_id": "HYP_REVIEW_EXP_044_TRAILING_18_V1", "family": "candidate_under_review_drawdown_refinement"}
    exit_h = {"hypothesis_id": "HYP_REVIEW_EXP_044_EXIT_16_V1", "family": "candidate_under_review_exit_refinement"}
    assert infer_candidate_review_axis(topn) == "top_n"
    assert candidate_review_priority(topn) < candidate_review_priority(trailing) < candidate_review_priority(exit_h)


def test_duplicate_candidate_review_exhausts_axis(tmp_path):
    state = tmp_path / "state"
    runs = tmp_path / "runs"
    state.mkdir()
    (state / "candidate_under_review.json").write_text(json.dumps({
        "status": "active",
        "candidate_run_id": "EXP_044",
        "official_parent_run_id": "AUTO_002",
    }), encoding="utf-8")
    run = runs / "EXP_051"
    run.mkdir(parents=True)
    (run / "run_manifest.json").write_text(json.dumps({
        "hypothesis_id": "HYP_REVIEW_EXP_044_EXIT_16_V1",
        "family": "candidate_under_review_exit_refinement",
    }), encoding="utf-8")
    audit = {"decision": "rejected", "duplicate_result": True, "flags": ["duplicate_artifact"]}
    result = update_candidate_review_learning_from_run(run_dir=run, state_dir=state, audit=audit)
    assert result["updated"] is True
    assert "exit" in result["exhausted_axes"]
    assert is_candidate_review_hypothesis_blocked(
        {"hypothesis_id": "HYP_REVIEW_EXP_044_EXIT_18_V1", "family": "candidate_under_review_exit_refinement"},
        state_dir=state,
    )
    assert not is_candidate_review_hypothesis_blocked(
        {"hypothesis_id": "HYP_REVIEW_EXP_044_TOPN_7_V1", "family": "candidate_under_review_topn_refinement"},
        state_dir=state,
    )
