import json
from pathlib import Path
from scripts.research.feature_engineering_agent import build_feature_plan


def test_feature_engineering_agent_builds_plan(tmp_path):
    state = tmp_path / "state"
    reports = tmp_path / "reports"
    state.mkdir()
    weekly = tmp_path / "weekly.csv"
    weekly.write_text("date;ticker;close\n2020-01-03;SPY;100\n", encoding="utf-8")
    (state / "data_paths_resolved.json").write_text(json.dumps({"weekly_file": str(weekly)}), encoding="utf-8")
    (state / "missing_feature_tasks.jsonl").write_text(
        json.dumps({"missing_features": ["ret_26w_pct", "atr_14w_pct"], "claim": "x"}) + "\n",
        encoding="utf-8",
    )
    plan = build_feature_plan(state_dir=state, reports_dir=reports)
    assert plan["task_count"] == 1
    names = {x["feature"] for x in plan["features_to_add"]}
    assert "ret_26w_pct" in names
    assert (reports / "feature_engineering_plan.md").exists()
