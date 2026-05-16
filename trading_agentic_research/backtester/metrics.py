"""Performance and risk metrics."""

from __future__ import annotations

import pandas as pd


def calculate_equity_curve(returns_df: pd.DataFrame) -> pd.DataFrame:
    """Build an equity curve from periodic returns in percentage points.

    Required columns in returns_df:
    - date
    - return_pct (e.g. 1.0 means +1.0% for that row period)
    """
    required = {"date", "return_pct"}
    missing = required - set(returns_df.columns)
    if missing:
        raise ValueError(f"Missing required columns: {sorted(missing)}")

    df = returns_df.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.sort_values("date", kind="mergesort").reset_index(drop=True)

    growth = 1.0 + (df["return_pct"].astype(float) / 100.0)
    df["equity"] = 100.0 * growth.cumprod()
    return df


def calculate_cagr(
    equity_curve: pd.DataFrame,
    date_col: str = "date",
    equity_col: str = "equity",
) -> float:
    """Calculate CAGR in percentage points."""
    if equity_curve.empty:
        return 0.0

    df = equity_curve.copy()
    df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
    df = df.sort_values(date_col, kind="mergesort")

    start_equity = float(df.iloc[0][equity_col])
    end_equity = float(df.iloc[-1][equity_col])
    start_date = df.iloc[0][date_col]
    end_date = df.iloc[-1][date_col]

    days = (end_date - start_date).days
    if days <= 0 or start_equity <= 0:
        return 0.0

    years = days / 365.25
    cagr = (end_equity / start_equity) ** (1.0 / years) - 1.0
    return cagr * 100.0


def calculate_max_drawdown(equity_curve: pd.DataFrame, equity_col: str = "equity") -> float:
    """Calculate max drawdown in percentage points (negative or zero)."""
    if equity_curve.empty:
        return 0.0

    equity = equity_curve[equity_col].astype(float)
    running_peak = equity.cummax()
    drawdown = (equity / running_peak - 1.0) * 100.0
    return float(drawdown.min())


def calculate_period_returns(equity_curve: pd.DataFrame, period: str = "M") -> pd.DataFrame:
    """Calculate monthly or yearly returns from an equity curve.

    period must be:
    - "M" (month-end buckets)
    - "Y" (year-end buckets)
    """
    if period not in {"M", "Y"}:
        raise ValueError("period must be 'M' or 'Y'")

    if equity_curve.empty:
        return pd.DataFrame(columns=["period_end", "period_return_pct"])

    df = equity_curve.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.sort_values("date", kind="mergesort")

    series = df.set_index("date")["equity"].astype(float)
    resample_rule = "ME" if period == "M" else "YE"
    period_end_equity = series.resample(resample_rule).last().dropna()
    period_return = period_end_equity.pct_change().dropna() * 100.0

    return pd.DataFrame(
        {
            "period_end": period_return.index,
            "period_return_pct": period_return.values,
        }
    ).reset_index(drop=True)


def summarize_performance(equity_curve: pd.DataFrame) -> dict:
    """Return a compact performance summary."""
    if equity_curve.empty:
        return {
            "total_return_pct": 0.0,
            "cagr_pct": 0.0,
            "max_drawdown_pct": 0.0,
            "start_date": None,
            "end_date": None,
        }

    df = equity_curve.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.sort_values("date", kind="mergesort").reset_index(drop=True)

    start_equity = float(df.iloc[0]["equity"])
    end_equity = float(df.iloc[-1]["equity"])
    total_return_pct = ((end_equity / start_equity) - 1.0) * 100.0 if start_equity > 0 else 0.0

    return {
        "total_return_pct": float(total_return_pct),
        "cagr_pct": float(calculate_cagr(df)),
        "max_drawdown_pct": float(calculate_max_drawdown(df)),
        "start_date": df.iloc[0]["date"],
        "end_date": df.iloc[-1]["date"],
    }
