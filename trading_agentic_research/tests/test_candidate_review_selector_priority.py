from scripts.select_next_hypothesis import choose_next_hypothesis


def test_selector_prefers_candidate_review_topn_over_trailing(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    bank = [
        {
            "hypothesis_id": "HYP_REVIEW_EXP_044_TRAILING_18_V1",
            "family": "candidate_under_review_drawdown_refinement",
            "bibliography_basis": [{"source_id": "x"}],
            "empirical_basis": [{"run_id": "EXP_044"}],
            "status": "candidate",
        },
        {
            "hypothesis_id": "HYP_REVIEW_EXP_044_TOPN_7_V1",
            "family": "candidate_under_review_topn_refinement",
            "bibliography_basis": [{"source_id": "x"}],
            "empirical_basis": [{"run_id": "EXP_044"}],
            "status": "candidate",
        },
    ]
    selected = choose_next_hypothesis(
        hypothesis_bank=bank,
        learning_memory={},
        cooldowns={},
        rejected_ids=set(),
        accepted_ids=set(),
        prefer_unseen=True,
        state_dir=state,
    )
    assert selected["hypothesis_id"] == "HYP_REVIEW_EXP_044_TOPN_7_V1"
