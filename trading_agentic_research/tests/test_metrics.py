import pandas as pd
import pytest

from backtester.metrics import (
    calculate_cagr,
    calculate_equity_curve,
    calculate_max_drawdown,
    calculate_period_returns,
    summarize_performance,
)


def test_calculate_equity_curve_basic():
    returns_df = pd.DataFrame(
        {
            "date": ["2026-01-01", "2026-01-02", "2026-01-03"],
            "return_pct": [10.0, -5.0, 0.0],
        }
    )

    eq = calculate_equity_curve(returns_df)
    assert list(eq["equity"].round(2)) == [110.0, 104.5, 104.5]


def test_calculate_max_drawdown_basic():
    equity_curve = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-03"]),
            "equity": [100.0, 120.0, 90.0],
        }
    )

    mdd = calculate_max_drawdown(equity_curve)
    assert round(mdd, 2) == -25.0


def test_calculate_cagr_positive_period():
    equity_curve = pd.DataFrame(
        {
            "date": pd.to_datetime(["2025-01-01", "2026-01-01"]),
            "equity": [100.0, 121.0],
        }
    )

    cagr = calculate_cagr(equity_curve)
    assert round(cagr, 1) == 21.0


def test_calculate_period_returns_monthly():
    equity_curve = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-01-31", "2026-02-28", "2026-03-31"]),
            "equity": [100.0, 110.0, 99.0],
        }
    )

    monthly = calculate_period_returns(equity_curve, period="M")
    assert len(monthly) == 2
    assert list(monthly["period_return_pct"].round(2)) == [10.0, -10.0]


def test_calculate_period_returns_invalid_period():
    equity_curve = pd.DataFrame({"date": pd.to_datetime(["2026-01-01"]), "equity": [100.0]})

    with pytest.raises(ValueError):
        calculate_period_returns(equity_curve, period="Q")


def test_summarize_performance_fields():
    equity_curve = pd.DataFrame(
        {
            "date": pd.to_datetime(["2025-01-01", "2026-01-01"]),
            "equity": [100.0, 121.0],
        }
    )

    summary = summarize_performance(equity_curve)

    assert set(summary.keys()) == {
        "total_return_pct",
        "cagr_pct",
        "max_drawdown_pct",
        "start_date",
        "end_date",
    }
    assert round(summary["total_return_pct"], 2) == 21.0
    assert summary["start_date"] == pd.Timestamp("2025-01-01")
    assert summary["end_date"] == pd.Timestamp("2026-01-01")
