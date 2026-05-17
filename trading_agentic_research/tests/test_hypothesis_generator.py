from scripts.hypothesis_generator import (
    existing_override_signatures,
    generate_hypotheses_from_parent,
    next_versioned_id,
    strategy_override_signature,
)


def test_next_versioned_id_bumps_when_taken():
    existing = {"HYP_X_V1", "HYP_X_V2"}
    assert next_versioned_id("HYP_X_V1", existing) == "HYP_X_V3"


def test_strategy_override_signature_stable():
    sig1 = strategy_override_signature({"exit_rule": {"rank_threshold": 20}, "entry_rule": {"top_n": 10}})
    sig2 = strategy_override_signature({"entry_rule": {"top_n": 10}, "exit_rule": {"rank_threshold": 20}})
    assert sig1 == sig2


def test_generate_hypotheses_from_parent_has_basis_and_overrides():
    bank = [{"hypothesis_id": "H_OLD", "strategy_overrides": {"entry_rule": {"top_n": 10}}}]
    sigs = existing_override_signatures(bank)
    existing_ids = {"H_OLD"}

    parent_cfg = {"strategy_id": "PARENT", "strategy_family": "cross_sectional_momentum"}
    out = generate_hypotheses_from_parent(
        family="cross_sectional_momentum",
        parent_strategy_config=parent_cfg,
        parent_run_id="EXP_PARENT",
        parent_learning_id="LEARN_PARENT",
        existing_ids=existing_ids,
        existing_override_sigs=sigs,
        max_new=2,
    )

    assert len(out) > 0
    for h in out:
        assert h.get("bibliography_basis")
        assert isinstance(h.get("strategy_overrides"), dict) and h["strategy_overrides"]
        assert h.get("empirical_basis")
