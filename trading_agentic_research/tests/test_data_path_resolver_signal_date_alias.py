from scripts.research.data_path_resolver import resolve_data_paths


def test_resolver_accepts_signal_date_alias_and_root_daily_folder(tmp_path):
    weekly = tmp_path / "sp500_feature_store_weekly_master_all.csv"
    weekly.write_text(
        "open,high,low,close,adj_close,volume,ticker,signal_date\n"
        "1,2,0.5,1.5,1.5,100,SPY,2020-01-03\n",
        encoding="utf-8",
    )
    daily = tmp_path / "sp500_feature_store_daily_master_2020.csv"
    daily.write_text(
        "open,high,low,close,adj_close,volume,ticker,signal_date\n"
        "1,2,0.5,1.5,1.5,100,SPY,2020-01-03\n",
        encoding="utf-8",
    )
    local = tmp_path / "configs" / "local_data_paths.json"
    local.parent.mkdir()
    local.write_text(
        '{"data_paths":{"weekly_file_path":"sp500_feature_store_weekly_master_all.csv","daily_folder_path":"."}}',
        encoding="utf-8",
    )
    result = resolve_data_paths(
        weekly_file=None,
        daily_folder=None,
        project_config="configs/project_config.json",
        local_data_paths="configs/local_data_paths.json",
        repo_root=tmp_path,
        state_dir="state",
        persist=True,
    )
    assert result.can_run, result.to_dict()
    assert result.source == "local_config_weekly+local_config_daily"


def test_resolver_autodiscovers_root_daily_folder(tmp_path):
    weekly = tmp_path / "sp500_feature_store_weekly_master_all.csv"
    weekly.write_text("signal_date,ticker,close\n2020-01-03,SPY,100\n", encoding="utf-8")
    daily = tmp_path / "sp500_feature_store_daily_master_2020.csv"
    daily.write_text("signal_date,ticker,close\n2020-01-03,SPY,100\n", encoding="utf-8")
    result = resolve_data_paths(
        weekly_file=None,
        daily_folder=None,
        project_config="configs/project_config.json",
        repo_root=tmp_path,
        state_dir="state",
        persist=False,
    )
    assert result.can_run, result.to_dict()
    assert result.daily_folder == str(tmp_path)
