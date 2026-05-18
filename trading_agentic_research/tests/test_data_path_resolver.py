import json
from pathlib import Path
from scripts.research.data_path_resolver import resolve_data_paths, is_placeholder_path


def test_resolver_ignores_placeholders_and_discovers(tmp_path):
    weekly = tmp_path / "data" / "sp500_feature_store_weekly_master.csv"
    weekly.parent.mkdir(parents=True)
    weekly.write_text("date;ticker;close\n2020-01-03;SPY;100\n", encoding="utf-8")
    daily = tmp_path / "data" / "daily_feature_store"
    daily.mkdir()
    (daily / "daily_2020.csv").write_text("date;ticker;close\n2020-01-03;SPY;100\n", encoding="utf-8")
    (tmp_path / "configs").mkdir()
    (tmp_path / "configs" / "project_config.json").write_text(json.dumps({"data_paths": {}}), encoding="utf-8")

    result = resolve_data_paths(
        weekly_file=".\\TU_WEEKLY.csv",
        daily_folder=".\\TU_DAILY_FOLDER",
        project_config="configs/project_config.json",
        repo_root=tmp_path,
        state_dir="state",
    )
    assert is_placeholder_path(".\\TU_WEEKLY.csv")
    assert result.can_run
    assert Path(result.weekly_file).name == "sp500_feature_store_weekly_master.csv"
    assert Path(result.daily_folder).name == "daily_feature_store"
