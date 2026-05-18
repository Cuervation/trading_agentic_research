import json
import subprocess
import sys
from pathlib import Path

from scripts.research.feature_engineering_agent import build_feature_plan


def test_generated_candidate_reads_semicolon_csv(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    state = tmp_path / "state"
    reports = tmp_path / "reports"
    state.mkdir()
    weekly = tmp_path / "weekly.csv"
    weekly.write_text("date;ticker;close\n2020-01-03;SPY;100\n", encoding="utf-8")
    (state / "data_paths_resolved.json").write_text(json.dumps({"weekly_file": str(weekly)}), encoding="utf-8")
    (state / "missing_feature_tasks.jsonl").write_text(
        json.dumps({"missing_features": ["ret_26w_pct"], "claim": "x"}) + "\n",
        encoding="utf-8",
    )

    plan = build_feature_plan(state_dir=state, reports_dir=reports, generate_candidate=True)
    assert Path(plan["candidate_script"]).exists()
    test_file = Path(plan["candidate_test"])
    assert test_file.exists()
    result = subprocess.run([sys.executable, "-m", "pytest", str(test_file)], cwd=tmp_path, text=True, capture_output=True)
    assert result.returncode == 0, result.stdout + result.stderr
