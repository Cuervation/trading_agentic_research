import json
from scripts.research.literature_hypothesis_miner import mine_literature_hypotheses, read_jsonl
from scripts.research.paper_searcher import generate_paper_ideas


def test_paper_searcher_feeds_literature_miner(tmp_path):
    parent = tmp_path / "configs" / "generated" / "PARENT.json"
    parent.parent.mkdir(parents=True)
    parent.write_text(json.dumps({"strategy_id": "PARENT", "strategy_family": "trend_following"}), encoding="utf-8")
    weekly = tmp_path / "weekly.csv"
    weekly.write_text("date,ticker,close,ret_52w_pct\n2020-01-03,SPY,100,1\n", encoding="utf-8")
    state = tmp_path / "state"; state.mkdir()
    (state / "current_parent.json").write_text(json.dumps({"current_parent_run_id": "AUTO_002", "current_parent_hypothesis_id": "PARENT"}), encoding="utf-8")
    (state / "data_paths_resolved.json").write_text(json.dumps({"weekly_file": str(weekly)}), encoding="utf-8")
    paper_ideas = tmp_path / "bibliography" / "paper_ideas.jsonl"
    bank = tmp_path / "bibliography" / "hypothesis_bank.jsonl"
    generate_paper_ideas(output=paper_ideas, online=False)
    result = mine_literature_hypotheses(parent_strategy_config_path=parent, hypothesis_bank_path=bank, state_dir=state, paper_ideas_path=paper_ideas, max_new=3)
    assert result["generated"] >= 1
    assert any(row["hypothesis_id"].startswith("HYP_LIT_AUTO_002") for row in read_jsonl(bank))
