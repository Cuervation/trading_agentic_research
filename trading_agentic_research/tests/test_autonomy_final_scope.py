import json
from pathlib import Path

from scripts.select_next_hypothesis import choose_next_hypothesis
from scripts.research.candidate_review_learning import (
    candidate_review_scope_reason,
    reset_candidate_review_learning_for_candidate,
    update_candidate_review_learning_from_run,
)
from scripts.research.generation_feedback import maybe_mark_candidate_review_exhausted


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def append_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


def review_hypothesis(hid: str, field: str = "ret_26w_pct") -> dict:
    return {
        "hypothesis_id": hid,
        "family": "candidate_under_review_exit_refinement",
        "claim": "review candidate",
        "causal_mechanism": "test",
        "bibliography_basis": [{"source_id": "test", "title": "test"}],
        "empirical_basis": [{"run_id": "EXP_054", "reason": "test"}],
        "features_required": [],
        "status": "candidate",
        "required_spy_comparison": "monthly_and_yearly",
        "axis": "candidate_under_review_exit_refinement",
        "falsification_rule": "Reject duplicates.",
        "strategy_overrides": {"ranking": {"field": field, "order": "desc"}},
    }


def regular_hypothesis(hid: str) -> dict:
    return {
        "hypothesis_id": hid,
        "family": "feature_space_momentum",
        "claim": "regular candidate",
        "causal_mechanism": "test",
        "bibliography_basis": [{"source_id": "test", "title": "test"}],
        "empirical_basis": [{"run_id": "AUTO_002", "reason": "test"}],
        "features_required": ["ret_13w_pct"],
        "status": "candidate",
        "required_spy_comparison": "monthly_and_yearly",
        "axis": "feature_space_ranking",
        "falsification_rule": "Reject duplicates.",
        "strategy_overrides": {"ranking": {"field": "ret_13w_pct", "order": "desc"}},
    }


def test_selector_blocks_stale_candidate_review_when_exp054_active(tmp_path):
    state = tmp_path / "state"
    write_json(state / "candidate_under_review.json", {"status": "active", "candidate_run_id": "EXP_054"})
    write_json(state / "current_parent.json", {"current_parent_hypothesis_id": "HYP_AUTO_TIME_SERIES_MOMENTUM_SEED"})
    write_json(state / "candidate_review_learning.json", {"version": 1, "candidate_run_id": "EXP_054", "attempts": [], "axis_stats": {}, "exhausted_axes": []})

    selected = choose_next_hypothesis(
        hypothesis_bank=[
            review_hypothesis("HYP_REVIEW_EXP_052_EXIT_16_V1", "ret_52w_pct"),
            review_hypothesis("HYP_REVIEW_EXP_054_EXIT_16_V1", "ret_26w_pct"),
        ],
        learning_memory={},
        cooldowns={},
        rejected_ids=set(),
        accepted_ids=set(),
        consumed_ids=set(),
        state_dir=state,
        prefer_unseen=True,
    )

    assert selected["hypothesis_id"] == "HYP_REVIEW_EXP_054_EXIT_16_V1"


def test_selector_blocks_all_review_rows_when_candidate_exhausted_and_uses_regular(tmp_path):
    state = tmp_path / "state"
    write_json(state / "candidate_under_review.json", {"status": "review_exhausted", "candidate_run_id": "EXP_054"})
    write_json(state / "current_parent.json", {"current_parent_hypothesis_id": "HYP_AUTO_TIME_SERIES_MOMENTUM_SEED"})

    selected = choose_next_hypothesis(
        hypothesis_bank=[
            review_hypothesis("HYP_REVIEW_EXP_054_EXIT_16_V1"),
            regular_hypothesis("HYP_FSPACE_AUTO_002_RANK_RET_13W_PCT_V1"),
        ],
        learning_memory={},
        cooldowns={},
        rejected_ids=set(),
        accepted_ids=set(),
        consumed_ids=set(),
        state_dir=state,
        prefer_unseen=True,
    )

    assert selected["hypothesis_id"] == "HYP_FSPACE_AUTO_002_RANK_RET_13W_PCT_V1"


def test_selector_blocks_duplicate_signature_from_consumed_id(tmp_path):
    state = tmp_path / "state"
    write_json(state / "candidate_under_review.json", {"status": "none"})
    old = regular_hypothesis("HYP_OLD")
    new = regular_hypothesis("HYP_NEW_SAME_SIGNATURE")
    selected_bank = [old, new, {**regular_hypothesis("HYP_OTHER"), "strategy_overrides": {"ranking": {"field": "ret_26w_pct", "order": "desc"}}}]

    selected = choose_next_hypothesis(
        hypothesis_bank=selected_bank,
        learning_memory={},
        cooldowns={},
        rejected_ids=set(),
        accepted_ids=set(),
        consumed_ids={"HYP_OLD"},
        state_dir=state,
        prefer_unseen=True,
    )

    assert selected["hypothesis_id"] == "HYP_OTHER"


def test_candidate_review_scope_reason_detects_stale_candidate(tmp_path):
    state = tmp_path / "state"
    write_json(state / "candidate_under_review.json", {"status": "active", "candidate_run_id": "EXP_054"})
    reason = candidate_review_scope_reason(review_hypothesis("HYP_REVIEW_EXP_052_EXIT_16_V1"), state_dir=state)
    assert reason == "stale_candidate_review:EXP_052_not_EXP_054"


def test_learning_ignores_stale_candidate_review_run(tmp_path):
    state = tmp_path / "state"
    run_dir = tmp_path / "runs" / "EXP_999"
    write_json(state / "candidate_under_review.json", {"status": "active", "candidate_run_id": "EXP_054", "official_parent_run_id": "AUTO_002"})
    write_json(state / "candidate_review_learning.json", {"version": 1, "candidate_run_id": "EXP_054", "attempts": [], "axis_stats": {}, "exhausted_axes": []})
    write_json(run_dir / "run_manifest.json", {"hypothesis_id": "HYP_REVIEW_EXP_052_EXIT_16_V1", "family": "candidate_under_review_exit_refinement"})

    result = update_candidate_review_learning_from_run(
        run_dir=run_dir,
        state_dir=state,
        audit={"decision": "rejected", "duplicate_result": True},
    )
    learning = json.loads((state / "candidate_review_learning.json").read_text(encoding="utf-8"))

    assert result["updated"] is False
    assert result["reason"] == "stale_candidate_review_hypothesis"
    assert learning["attempts"] == []
    assert learning["exhausted_axes"] == []


def test_learning_updates_active_candidate_axis_on_duplicate(tmp_path):
    state = tmp_path / "state"
    run_dir = tmp_path / "runs" / "EXP_100"
    write_json(state / "candidate_under_review.json", {"status": "active", "candidate_run_id": "EXP_054", "official_parent_run_id": "AUTO_002"})
    reset_candidate_review_learning_for_candidate(state_dir=state, candidate_run_id="EXP_054", official_parent_run_id="AUTO_002")
    write_json(run_dir / "run_manifest.json", {"hypothesis_id": "HYP_REVIEW_EXP_054_EXIT_16_V1", "family": "candidate_under_review_exit_refinement"})

    result = update_candidate_review_learning_from_run(
        run_dir=run_dir,
        state_dir=state,
        audit={"decision": "rejected", "duplicate_result": True},
    )
    learning = json.loads((state / "candidate_review_learning.json").read_text(encoding="utf-8"))

    assert result["updated"] is True
    assert "exit" in learning["exhausted_axes"]


def test_maybe_mark_candidate_review_exhausted_after_all_active_rows_blocked(tmp_path):
    state = tmp_path / "state"
    bank = tmp_path / "bibliography" / "hypothesis_bank.jsonl"
    hid = "HYP_REVIEW_EXP_054_EXIT_16_V1"
    write_json(state / "candidate_under_review.json", {"status": "active", "candidate_run_id": "EXP_054"})
    write_json(state / "current_parent.json", {"current_parent_hypothesis_id": "HYP_AUTO_TIME_SERIES_MOMENTUM_SEED"})
    write_json(state / "candidate_review_learning.json", {"version": 1, "candidate_run_id": "EXP_054", "attempts": [], "axis_stats": {}, "exhausted_axes": []})
    append_jsonl(bank, [review_hypothesis(hid)])
    append_jsonl(state / "consumed_hypotheses.jsonl", [{"hypothesis_id": hid, "run_id": "EXP_123"}])

    result = maybe_mark_candidate_review_exhausted(
        state_dir=state,
        hypothesis_bank=bank,
        generation_result={"generated": 0, "reason": "batch_selection_preflight"},
    )
    refreshed = json.loads((state / "candidate_under_review.json").read_text(encoding="utf-8"))

    assert result["candidate_review_status"] == "review_exhausted"
    assert refreshed["status"] == "review_exhausted"
    assert refreshed["reason"] == "no_selector_eligible_candidate_review_hypotheses"
