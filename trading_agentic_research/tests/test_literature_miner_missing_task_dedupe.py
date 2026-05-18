import json

from scripts.research.literature_hypothesis_miner import (
    append_missing_tasks_dedup,
    mine_literature_hypotheses,
    read_jsonl,
)


def test_missing_feature_tasks_are_deduped(tmp_path):
    path = tmp_path / "state" / "missing_feature_tasks.jsonl"
    task = {
        "parent_run_id": "AUTO_002",
        "parent_hypothesis_id": "HYP",
        "source_id": "SRC",
        "candidate_suffix": "X",
        "missing_features": ["channel_r2", "close"],
    }
    assert append_missing_tasks_dedup(path, [task]) == 1
    assert append_missing_tasks_dedup(path, [task]) == 0
    assert len(read_jsonl(path)) == 1


def test_miner_reads_paper_ideas_and_generates_supported_hypotheses(tmp_path):
    parent = tmp_path / "configs" / "generated" / "PARENT.json"
    parent.parent.mkdir(parents=True)
    parent.write_text(json.dumps({"strategy_id": "PARENT", "strategy_family": "trend_following"}), encoding="utf-8")

    weekly = tmp_path / "weekly.csv"
    weekly.write_text("date;ticker;close;ret_52w_pct\n2020-01-03;SPY;100;1\n", encoding="utf-8")

    state = tmp_path / "state"
    state.mkdir()
    (state / "current_parent.json").write_text(json.dumps({"current_parent_run_id": "AUTO_002", "current_parent_hypothesis_id": "PARENT"}), encoding="utf-8")
    (state / "data_paths_resolved.json").write_text(json.dumps({"weekly_file": str(weekly)}), encoding="utf-8")

    bank = tmp_path / "bibliography" / "hypothesis_bank.jsonl"
    bank.parent.mkdir()
    paper_ideas = tmp_path / "bibliography" / "paper_ideas.jsonl"
    paper_ideas.write_text(json.dumps({
        "source_id": "custom_momentum",
        "title": "Custom momentum idea",
        "claim_seed": "Intermediate horizon momentum can work.",
        "families": ["paper_time_series_momentum"],
    }) + "\n", encoding="utf-8")

    result = mine_literature_hypotheses(
        parent_strategy_config_path=parent,
        hypothesis_bank_path=bank,
        state_dir=state,
        paper_ideas_path=paper_ideas,
        max_new=8,
    )
    assert result["generated"] >= 1
    rows = read_jsonl(bank)
    assert any("custom_momentum" in str(row.get("bibliography_basis")) for row in rows)
