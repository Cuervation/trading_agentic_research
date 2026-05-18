import json
from pathlib import Path
from scripts.research.autonomous_hypothesis_factory import generate_value_hypotheses, read_jsonl


def test_factory_generates_value_hypotheses(tmp_path):
    parent = tmp_path / "configs" / "generated" / "PARENT.json"
    parent.parent.mkdir(parents=True)
    parent.write_text(json.dumps({"strategy_id": "PARENT", "entry_rule": {"top_n": 8}, "exit_rule": {"rank_threshold": 24}}), encoding="utf-8")
    bank = tmp_path / "bibliography" / "hypothesis_bank.jsonl"
    bank.parent.mkdir()
    state = tmp_path / "state"
    state.mkdir()
    (state / "current_parent.json").write_text(json.dumps({"current_parent_run_id": "AUTO_002", "current_parent_hypothesis_id": "PARENT"}), encoding="utf-8")
    result = generate_value_hypotheses(parent_strategy_config_path=parent, hypothesis_bank_path=bank, state_dir=state, max_new=4)
    assert result["generated"] == 4
    rows = read_jsonl(bank)
    assert all(r["bibliography_basis"] for r in rows)
    assert all(r["empirical_basis"] for r in rows)
    assert all(r["falsification_rule"] for r in rows)
