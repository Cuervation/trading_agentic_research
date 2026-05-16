import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backtester.data_loader import (
    load_daily_feature_store_folder,
    load_weekly_feature_store,
    validate_feature_store,
)


def test_validate_feature_store_ok_and_has_benchmark():
    df = pd.DataFrame(
        {
            "date": ["2026-01-02", "2026-01-03", "2026-01-02"],
            "ticker": ["AAPL", "AAPL", "SPY"],
            "close": [100.0, 101.0, 500.0],
        }
    )

    result = validate_feature_store(df, required_columns=["date", "ticker", "close"])

    assert result["status"] == "ok"
    assert result["rows"] == 3
    assert result["columns"] == 3
    assert result["tickers"] == 2
    assert result["has_benchmark"] is True
    assert result["missing_required_columns"] == []
    assert result["min_date"] == pd.Timestamp("2026-01-02")
    assert result["max_date"] == pd.Timestamp("2026-01-03")


def test_validate_feature_store_missing_required_column():
    df = pd.DataFrame({"date": ["2026-01-02"], "ticker": ["AAPL"]})

    result = validate_feature_store(df, required_columns=["date", "ticker", "close"])

    assert result["status"] == "invalid"
    assert result["missing_required_columns"] == ["close"]
    assert result["has_benchmark"] is False


def test_load_weekly_feature_store_parses_dates_and_sorts(tmp_path):
    source_df = pd.DataFrame(
        {
            "date": ["2026-01-03", "2026-01-02"],
            "ticker": ["AAPL", "AAPL"],
            "close": [101.0, 100.0],
        }
    )
    file_path = tmp_path / "weekly.csv"
    source_df.to_csv(file_path, index=False)

    loaded = load_weekly_feature_store(str(file_path))

    assert list(loaded["date"]) == [pd.Timestamp("2026-01-02"), pd.Timestamp("2026-01-03")]
    assert loaded.iloc[0]["close"] == 100.0
    assert source_df["date"].dtype == object


def test_load_daily_feature_store_folder_merges_matching_files(tmp_path):
    df_2020 = pd.DataFrame(
        {
            "date": ["2020-01-02", "2020-01-03"],
            "ticker": ["AAPL", "SPY"],
            "close": [75.0, 320.0],
        }
    )
    df_2021 = pd.DataFrame(
        {
            "date": ["2021-01-04", "2021-01-05"],
            "ticker": ["MSFT", "AAPL"],
            "close": [210.0, 130.0],
        }
    )

    df_2020.to_csv(tmp_path / "sp500_feature_store_daily_master_2020_part1.csv", index=False)
    df_2021.to_csv(tmp_path / "sp500_feature_store_daily_master_2021_part1.csv", index=False)

    loaded = load_daily_feature_store_folder(str(tmp_path))

    assert len(loaded) == 4
    assert pd.api.types.is_datetime64_any_dtype(loaded["date"])
    assert list(loaded.columns) == ["date", "ticker", "close"]


def test_load_daily_feature_store_folder_raises_when_no_files(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_daily_feature_store_folder(str(tmp_path))
