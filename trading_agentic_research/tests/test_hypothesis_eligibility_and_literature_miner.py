import json
from pathlib import Path

from scripts.research.hypothesis_eligibility import eligible_hypothesis_preflight
from scripts.research.literature_hypothesis_miner import mine_literature_hypotheses, read_jsonl


def test_eligibility_preflight_blocks_empty_bank(tmp_path):
    bank = tmp_path / "bibliography" / "hypothesis_bank.jsonl"
    bank.parent.mkdir()
    bank.write_text("", encoding="utf-8")
    state = tmp_path / "state"
    state.mkdir()
    result = eligible_hypothesis_preflight(hypothesis_bank=bank, state_dir=state)
    assert result["eligible"] is False


def test_literature_miner_generates_supported_and_records_missing_features(tmp_path):
    parent = tmp_path / "configs" / "generated" / "PARENT.json"
    parent.parent.mkdir(parents=True)
    parent.write_text(json.dumps({
        "strategy_id": "PARENT",
        "strategy_family": "trend_following",
        "entry_rule": {"top_n": 15},
        "exit_rule": {"rank_threshold": 20},
    }), encoding="utf-8")

    weekly = tmp_path / "data" / "weekly.csv"
    weekly.parent.mkdir()
    weekly.write_text("date;ticker;close;ret_52w_pct;spy_close_vs_sma50_pct\n2020-01-03;SPY;100;1;1\n", encoding="utf-8")

    state = tmp_path / "state"
    state.mkdir()
    (state / "current_parent.json").write_text(json.dumps({
        "current_parent_run_id": "AUTO_002",
        "current_parent_hypothesis_id": "PARENT",
    }), encoding="utf-8")
    (state / "data_paths_resolved.json").write_text(json.dumps({"weekly_file": str(weekly)}), encoding="utf-8")

    bank = tmp_path / "bibliography" / "hypothesis_bank.jsonl"
    bank.parent.mkdir()
    result = mine_literature_hypotheses(parent_strategy_config_path=parent, hypothesis_bank_path=bank, state_dir=state, max_new=4)
    assert result["generated"] >= 1
    rows = read_jsonl(bank)
    assert all(r["bibliography_basis"] for r in rows)
    assert all(r["empirical_basis"] for r in rows)
    assert (state / "missing_feature_tasks.jsonl").exists()
