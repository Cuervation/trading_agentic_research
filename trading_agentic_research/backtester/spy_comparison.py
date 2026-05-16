"""SPY benchmark comparison helpers."""

from __future__ import annotations

import pandas as pd


_REQUIRED_DAILY_COLUMNS = {"date", "ticker", "close"}
_REQUIRED_EQUITY_COLUMNS = {"date", "equity"}


def build_spy_equity_curve(
    daily_df: pd.DataFrame,
    start_date,
    end_date,
    initial_capital: float = 100000,
    benchmark_ticker: str = "SPY",
) -> pd.DataFrame:
    """Build a buy-and-hold SPY equity curve for the strategy date range."""
    missing = _REQUIRED_DAILY_COLUMNS - set(daily_df.columns)
    if missing:
        raise ValueError(f"Missing required columns: {sorted(missing)}")

    start = pd.to_datetime(start_date)
    end = pd.to_datetime(end_date)

    df = daily_df.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df[df["ticker"] == benchmark_ticker]
    df = df[(df["date"] >= start) & (df["date"] <= end)]
    df = df.dropna(subset=["date", "close"])
    df = df.sort_values("date", kind="mergesort").reset_index(drop=True)

    if df.empty:
        raise ValueError(f"No {benchmark_ticker} rows found in requested date range")

    first_close = float(df.iloc[0]["close"])
    if first_close <= 0:
        raise ValueError("First benchmark close must be > 0")

    df["daily_return_pct"] = df["close"].astype(float).pct_change().fillna(0.0) * 100.0
    df["equity"] = float(initial_capital) * (df["close"].astype(float) / first_close)

    return df[["date", "equity", "daily_return_pct"]]


def compare_equity_curves(strategy_equity: pd.DataFrame, spy_equity: pd.DataFrame) -> pd.DataFrame:
    """Compare strategy and SPY equity curves day by day."""
    strategy = _prepare_equity_curve(strategy_equity, "strategy_equity")
    spy = _prepare_equity_curve(spy_equity, "spy_equity")

    comparison = strategy.merge(spy, on="date", how="inner")
    comparison = comparison.sort_values("date", kind="mergesort").reset_index(drop=True)

    comparison["strategy_daily_return_pct"] = (
        comparison["strategy_equity"].pct_change().fillna(0.0) * 100.0
    )
    comparison["spy_daily_return_pct"] = (
        comparison["spy_equity"].pct_change().fillna(0.0) * 100.0
    )
    comparison["excess_daily_return_pct"] = (
        comparison["strategy_daily_return_pct"] - comparison["spy_daily_return_pct"]
    )
    comparison["winner"] = comparison["excess_daily_return_pct"].apply(_winner_from_excess)

    return comparison[
        [
            "date",
            "strategy_equity",
            "spy_equity",
            "strategy_daily_return_pct",
            "spy_daily_return_pct",
            "excess_daily_return_pct",
            "winner",
        ]
    ]


def compare_monthly(strategy_equity: pd.DataFrame, spy_equity: pd.DataFrame) -> pd.DataFrame:
    """Compare strategy and SPY returns month by month."""
    return _compare_by_period(strategy_equity, spy_equity, period_columns=["year", "month"])


def compare_yearly(strategy_equity: pd.DataFrame, spy_equity: pd.DataFrame) -> pd.DataFrame:
    """Compare strategy and SPY returns year by year."""
    return _compare_by_period(strategy_equity, spy_equity, period_columns=["year"])


def summarize_spy_comparison(
    monthly_df: pd.DataFrame,
    yearly_df: pd.DataFrame,
    strategy_metrics: dict,
    spy_metrics: dict,
) -> dict:
    """Summarize strategy-vs-SPY comparison into a compact decision hint."""
    strategy_cagr_pct = float(strategy_metrics.get("cagr_pct", 0.0))
    spy_cagr_pct = float(spy_metrics.get("cagr_pct", 0.0))
    excess_cagr_pct = strategy_cagr_pct - spy_cagr_pct

    strategy_drawdown = strategy_metrics.get("max_drawdown_pct")
    spy_drawdown = spy_metrics.get("max_drawdown_pct")
    risk_improved = False
    if strategy_drawdown is not None and spy_drawdown is not None:
        risk_improved = float(strategy_drawdown) >= float(spy_drawdown)

    months_beating_spy = int((monthly_df.get("winner", pd.Series(dtype=str)) == "strategy").sum())
    months_losing_to_spy = int((monthly_df.get("winner", pd.Series(dtype=str)) == "spy").sum())
    years_beating_spy = int((yearly_df.get("winner", pd.Series(dtype=str)) == "strategy").sum())
    years_losing_to_spy = int((yearly_df.get("winner", pd.Series(dtype=str)) == "spy").sum())

    if strategy_cagr_pct < spy_cagr_pct and not risk_improved:
        recommendation_hint = "reject"
    elif abs(excess_cagr_pct) <= 1.0:
        recommendation_hint = "review"
    elif excess_cagr_pct > 1.0:
        recommendation_hint = "candidate"
    else:
        recommendation_hint = "review"

    return {
        "strategy_cagr_pct": strategy_cagr_pct,
        "spy_cagr_pct": spy_cagr_pct,
        "excess_cagr_pct": excess_cagr_pct,
        "months_beating_spy": months_beating_spy,
        "months_losing_to_spy": months_losing_to_spy,
        "years_beating_spy": years_beating_spy,
        "years_losing_to_spy": years_losing_to_spy,
        "recommendation_hint": recommendation_hint,
    }


def _prepare_equity_curve(equity_curve: pd.DataFrame, output_col: str) -> pd.DataFrame:
    missing = _REQUIRED_EQUITY_COLUMNS - set(equity_curve.columns)
    if missing:
        raise ValueError(f"Missing required columns: {sorted(missing)}")

    df = equity_curve.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date", "equity"])
    df = df.sort_values("date", kind="mergesort").reset_index(drop=True)
    return df[["date", "equity"]].rename(columns={"equity": output_col})


def _compare_by_period(
    strategy_equity: pd.DataFrame,
    spy_equity: pd.DataFrame,
    period_columns: list[str],
) -> pd.DataFrame:
    daily = compare_equity_curves(strategy_equity, spy_equity)
    if daily.empty:
        columns = period_columns + [
            "strategy_return_pct",
            "spy_return_pct",
            "excess_return_pct",
            "winner",
        ]
        return pd.DataFrame(columns=columns)

    daily["year"] = daily["date"].dt.year
    daily["month"] = daily["date"].dt.month

    rows = []
    for keys, group in daily.groupby(period_columns, sort=True):
        if not isinstance(keys, tuple):
            keys = (keys,)

        strategy_return = _period_return_pct(group["strategy_equity"])
        spy_return = _period_return_pct(group["spy_equity"])
        excess_return = strategy_return - spy_return

        row = dict(zip(period_columns, keys))
        row.update(
            {
                "strategy_return_pct": strategy_return,
                "spy_return_pct": spy_return,
                "excess_return_pct": excess_return,
                "winner": _winner_from_excess(excess_return),
            }
        )
        rows.append(row)

    return pd.DataFrame(rows)


def _period_return_pct(equity: pd.Series) -> float:
    if equity.empty:
        return 0.0

    start_equity = float(equity.iloc[0])
    end_equity = float(equity.iloc[-1])
    if start_equity <= 0:
        return 0.0

    return ((end_equity / start_equity) - 1.0) * 100.0


def _winner_from_excess(excess_return_pct: float) -> str:
    if excess_return_pct > 0:
        return "strategy"
    if excess_return_pct < 0:
        return "spy"
    return "tie"
