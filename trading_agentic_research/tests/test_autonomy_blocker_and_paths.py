import json
from pathlib import Path

from scripts.research.autonomy_blocker import clear_autonomy_blocker, write_autonomy_blocker
from scripts.research.data_path_resolver import resolve_data_paths


def test_blocker_written_and_cleared(tmp_path):
    state = tmp_path / "state"
    payload = write_autonomy_blocker(state_dir=state, reason="missing_data", errors=["x"], next_action="fix")
    assert payload["status"] == "blocked"
    path = state / "autonomy_blocker.json"
    assert path.exists()
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded["reason"] == "missing_data"

    clear_autonomy_blocker(state_dir=state)
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded["status"] == "clear"


def test_resolver_uses_env_and_ignores_placeholders(tmp_path, monkeypatch):
    weekly = tmp_path / "data" / "sp500_weekly_feature_master.csv"
    weekly.parent.mkdir(parents=True)
    weekly.write_text("date;ticker;close\n2020-01-03;SPY;100\n", encoding="utf-8")
    daily = tmp_path / "data" / "daily_feature_store"
    daily.mkdir()
    (daily / "daily_2020.csv").write_text("date;ticker;close\n2020-01-03;SPY;100\n", encoding="utf-8")
    (tmp_path / "configs").mkdir()
    (tmp_path / "configs" / "project_config.json").write_text(json.dumps({"data_paths": {}}), encoding="utf-8")

    monkeypatch.setenv("TRADING_WEEKLY_FILE", str(weekly))
    monkeypatch.setenv("TRADING_DAILY_FOLDER", str(daily))

    result = resolve_data_paths(
        weekly_file=".\\TU_WEEKLY.csv",
        daily_folder=".\\TU_DAILY_FOLDER",
        project_config="configs/project_config.json",
        repo_root=tmp_path,
        state_dir="state",
    )
    assert result.can_run
    assert "env_weekly" in result.source
    assert "env_daily" in result.source
    assert Path(result.weekly_file).name == weekly.name
