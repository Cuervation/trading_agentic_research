import json
from pathlib import Path

from scripts.research.autonomous_hypothesis_factory import (
    generate_value_hypotheses,
    read_jsonl,
    real_override_signature,
)


def test_real_override_signature_ignores_strategy_id():
    a = {"strategy_id": "A", "entry_rule": {"top_n": 6}}
    b = {"strategy_id": "B", "entry_rule": {"top_n": 6}}
    assert real_override_signature(a) == real_override_signature(b)


def test_factory_generates_value_hypotheses_with_dedup(tmp_path):
    parent = tmp_path / "configs" / "generated" / "PARENT.json"
    parent.parent.mkdir(parents=True)
    parent.write_text(json.dumps({"strategy_id": "PARENT", "entry_rule": {"top_n": 8}, "exit_rule": {"rank_threshold": 24}}), encoding="utf-8")
    bank = tmp_path / "bibliography" / "hypothesis_bank.jsonl"
    bank.parent.mkdir()
    bank.write_text(json.dumps({"hypothesis_id":"OLD", "strategy_overrides":{"strategy_id":"OLD", "entry_rule":{"top_n":4}}}) + "\n", encoding="utf-8")
    state = tmp_path / "state"
    state.mkdir()
    (state / "current_parent.json").write_text(json.dumps({"current_parent_run_id": "AUTO_002", "current_parent_hypothesis_id": "PARENT"}), encoding="utf-8")
    result = generate_value_hypotheses(parent_strategy_config_path=parent, hypothesis_bank_path=bank, state_dir=state, max_new=4)
    assert result["generated"] == 4
    rows = read_jsonl(bank)
    assert all(r["bibliography_basis"] for r in rows if r.get("hypothesis_id") != "OLD")
    assert all(r["empirical_basis"] for r in rows if r.get("hypothesis_id") != "OLD")
    assert all(r["falsification_rule"] for r in rows if r.get("hypothesis_id") != "OLD")
    # Existing real override top_n=4 should not be generated again with a new strategy_id.
    assert not any(r.get("strategy_overrides", {}).get("entry_rule", {}).get("top_n") == 4 for r in rows if r.get("hypothesis_id") != "OLD")
