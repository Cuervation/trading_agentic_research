"""Data loading utilities for weekly and daily feature stores."""

from __future__ import annotations

from glob import glob
from pathlib import Path
from typing import Iterable

import pandas as pd


REQUIRED_FEATURE_COLUMNS = ("date", "ticker", "close")


def load_weekly_feature_store(path: str) -> pd.DataFrame:
    """Load a weekly feature store CSV and apply minimal normalization."""
    csv_path = Path(path)
    if not csv_path.exists():
        raise FileNotFoundError(f"Weekly feature store not found: {path}")

    df = pd.read_csv(csv_path)
    return _normalize_feature_store(df)


def load_daily_feature_store_folder(folder_path: str) -> pd.DataFrame:
    """Load and merge daily feature store CSV files from a folder."""
    folder = Path(folder_path)
    if not folder.exists() or not folder.is_dir():
        raise FileNotFoundError(f"Daily feature store folder not found: {folder_path}")

    pattern = str(folder / "sp500_feature_store_daily_master_*.csv")
    file_paths = sorted(glob(pattern))

    if not file_paths:
        raise FileNotFoundError(
            f"No daily feature store files matched pattern: {pattern}"
        )

    frames = [pd.read_csv(file_path) for file_path in file_paths]
    merged = pd.concat(frames, ignore_index=True, sort=False)
    return _normalize_feature_store(merged)


def validate_feature_store(
    df: pd.DataFrame,
    required_columns: Iterable[str],
    benchmark_ticker: str = "SPY",
) -> dict:
    """Return a compact validation report for a feature-store dataframe."""
    required_columns = list(required_columns)
    missing_required_columns = [c for c in required_columns if c not in df.columns]

    has_date = "date" in df.columns
    has_ticker = "ticker" in df.columns

    min_date = None
    max_date = None
    if has_date and not df.empty:
        parsed_dates = pd.to_datetime(df["date"], errors="coerce")
        if parsed_dates.notna().any():
            min_date = parsed_dates.min()
            max_date = parsed_dates.max()

    tickers_count = int(df["ticker"].nunique()) if has_ticker else 0
    has_benchmark = bool((df["ticker"] == benchmark_ticker).any()) if has_ticker and not df.empty else False

    status = "ok" if not missing_required_columns else "invalid"

    return {
        "rows": int(len(df)),
        "columns": int(df.shape[1]),
        "tickers": tickers_count,
        "min_date": min_date,
        "max_date": max_date,
        "has_benchmark": has_benchmark,
        "missing_required_columns": missing_required_columns,
        "status": status,
    }


def _normalize_feature_store(df: pd.DataFrame) -> pd.DataFrame:
    """Apply minimal required normalization without mutating input in place."""
    normalized = df.copy()

    if "date" not in normalized.columns and "signal_date" in normalized.columns:
        normalized = normalized.rename(columns={"signal_date": "date"})

    _ensure_required_columns(normalized, REQUIRED_FEATURE_COLUMNS)

    normalized["date"] = pd.to_datetime(normalized["date"], errors="coerce")
    normalized = normalized.sort_values(["ticker", "date"], kind="mergesort").reset_index(
        drop=True
    )

    return normalized


def _ensure_required_columns(df: pd.DataFrame, required_columns: Iterable[str]) -> None:
    missing = [column for column in required_columns if column not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")
