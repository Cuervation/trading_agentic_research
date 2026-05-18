import json
from pathlib import Path
from scripts.research.feature_engineering_agent import build_feature_plan


def test_feature_agent_generates_candidate_files(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    state = tmp_path / "state"; reports = tmp_path / "reports"; state.mkdir()
    weekly = tmp_path / "weekly.csv"
    weekly.write_text("date,ticker,close,high,low\n2020-01-03,SPY,100,101,99\n", encoding="utf-8")
    (state / "data_paths_resolved.json").write_text(json.dumps({"weekly_file": str(weekly)}), encoding="utf-8")
    (state / "missing_feature_tasks.jsonl").write_text(json.dumps({"missing_features": ["ret_26w_pct", "atr_14w_pct"], "claim": "x"}) + "\n", encoding="utf-8")
    plan = build_feature_plan(state_dir=state, reports_dir=reports, generate_candidate=True)
    assert Path("scripts/generated/feature_engineering_candidate.py").exists()
    assert Path("tests/generated/test_feature_engineering_candidate.py").exists()
    assert plan["candidate_script"]
