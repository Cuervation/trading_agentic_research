from scripts.research.consumed_hypotheses import append_consumed_hypothesis, consumed_hypothesis_ids
from scripts.select_next_hypothesis import choose_next_hypothesis


def _hyp(hid, family="f"):
    return {
        "hypothesis_id": hid,
        "family": family,
        "status": "candidate",
        "bibliography_basis": [{"source_id": "x"}],
        "empirical_basis": [{"run_id": "r"}],
    }


def test_consumed_hypothesis_ids_are_persisted(tmp_path):
    state = tmp_path / "state"
    append_consumed_hypothesis(state_dir=state, run_id="EXP_001", hypothesis_id="HYP_A", family="f")
    append_consumed_hypothesis(state_dir=state, run_id="EXP_002", hypothesis_id="HYP_A", family="f")
    assert consumed_hypothesis_ids(state) == {"HYP_A"}


def test_selector_does_not_rerun_accepted_hypothesis_when_prefer_unseen():
    selected = choose_next_hypothesis(
        hypothesis_bank=[_hyp("HYP_A"), _hyp("HYP_B")],
        learning_memory={},
        cooldowns={},
        rejected_ids=set(),
        accepted_ids={"HYP_A"},
        prefer_unseen=True,
    )
    assert selected["hypothesis_id"] == "HYP_B"


def test_selector_does_not_rerun_consumed_hypothesis():
    selected = choose_next_hypothesis(
        hypothesis_bank=[_hyp("HYP_A"), _hyp("HYP_B")],
        learning_memory={},
        cooldowns={},
        rejected_ids=set(),
        accepted_ids=set(),
        consumed_ids={"HYP_A"},
        prefer_unseen=True,
    )
    assert selected["hypothesis_id"] == "HYP_B"
