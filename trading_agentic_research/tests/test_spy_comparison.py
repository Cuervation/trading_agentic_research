import pandas as pd
import pytest

from backtester.spy_comparison import (
    build_spy_equity_curve,
    compare_equity_curves,
    compare_monthly,
    compare_yearly,
    summarize_spy_comparison,
)


def test_build_spy_equity_curve_filters_spy_and_range():
    daily_df = pd.DataFrame(
        {
            "date": [
                "2026-01-01",
                "2026-01-01",
                "2026-01-02",
                "2026-01-03",
                "2026-01-04",
            ],
            "ticker": ["AAPL", "SPY", "SPY", "SPY", "SPY"],
            "close": [10.0, 100.0, 110.0, 121.0, 130.0],
        }
    )

    spy = build_spy_equity_curve(
        daily_df,
        start_date="2026-01-02",
        end_date="2026-01-03",
        initial_capital=100000,
    )

    assert list(spy["date"]) == [pd.Timestamp("2026-01-02"), pd.Timestamp("2026-01-03")]
    assert list(spy["equity"].round(2)) == [100000.0, 110000.0]
    assert list(spy["daily_return_pct"].round(2)) == [0.0, 10.0]


def test_build_spy_equity_curve_raises_without_spy_in_range():
    daily_df = pd.DataFrame(
        {"date": ["2026-01-01"], "ticker": ["AAPL"], "close": [100.0]}
    )

    with pytest.raises(ValueError):
        build_spy_equity_curve(daily_df, "2026-01-01", "2026-01-02")


def test_compare_equity_curves_daily_output():
    strategy = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-03"]),
            "equity": [100.0, 110.0, 121.0],
        }
    )
    spy = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-03"]),
            "equity": [100.0, 105.0, 115.5],
        }
    )

    compared = compare_equity_curves(strategy, spy)

    assert list(compared.columns) == [
        "date",
        "strategy_equity",
        "spy_equity",
        "strategy_daily_return_pct",
        "spy_daily_return_pct",
        "excess_daily_return_pct",
        "winner",
    ]
    assert list(compared["winner"]) == ["tie", "strategy", "tie"]
    assert round(compared.iloc[1]["excess_daily_return_pct"], 2) == 5.0


def test_compare_monthly_returns():
    strategy = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-01-01", "2026-01-31", "2026-02-01", "2026-02-28"]),
            "equity": [100.0, 110.0, 110.0, 99.0],
        }
    )
    spy = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-01-01", "2026-01-31", "2026-02-01", "2026-02-28"]),
            "equity": [100.0, 105.0, 105.0, 105.0],
        }
    )

    monthly = compare_monthly(strategy, spy)

    assert list(monthly["year"]) == [2026, 2026]
    assert list(monthly["month"]) == [1, 2]
    assert list(monthly["winner"]) == ["strategy", "spy"]
    assert round(monthly.iloc[0]["strategy_return_pct"], 2) == 10.0
    assert round(monthly.iloc[1]["strategy_return_pct"], 2) == -10.0


def test_compare_yearly_returns():
    strategy = pd.DataFrame(
        {
            "date": pd.to_datetime(["2025-01-01", "2025-12-31", "2026-01-01", "2026-12-31"]),
            "equity": [100.0, 120.0, 120.0, 132.0],
        }
    )
    spy = pd.DataFrame(
        {
            "date": pd.to_datetime(["2025-01-01", "2025-12-31", "2026-01-01", "2026-12-31"]),
            "equity": [100.0, 110.0, 110.0, 132.0],
        }
    )

    yearly = compare_yearly(strategy, spy)

    assert list(yearly["year"]) == [2025, 2026]
    assert list(yearly["winner"]) == ["strategy", "spy"]
    assert round(yearly.iloc[0]["excess_return_pct"], 2) == 10.0
    assert round(yearly.iloc[1]["spy_return_pct"], 2) == 20.0


def test_summarize_spy_comparison_reject_without_risk_improvement():
    monthly = pd.DataFrame({"winner": ["spy", "strategy", "spy"]})
    yearly = pd.DataFrame({"winner": ["spy"]})

    summary = summarize_spy_comparison(
        monthly,
        yearly,
        strategy_metrics={"cagr_pct": 8.0, "max_drawdown_pct": -30.0},
        spy_metrics={"cagr_pct": 10.0, "max_drawdown_pct": -20.0},
    )

    assert summary["recommendation_hint"] == "reject"
    assert summary["excess_cagr_pct"] == -2.0
    assert summary["months_beating_spy"] == 1
    assert summary["months_losing_to_spy"] == 2
    assert summary["years_losing_to_spy"] == 1


def test_summarize_spy_comparison_candidate_when_clear_cagr_win():
    summary = summarize_spy_comparison(
        monthly_df=pd.DataFrame({"winner": ["strategy", "strategy"]}),
        yearly_df=pd.DataFrame({"winner": ["strategy"]}),
        strategy_metrics={"cagr_pct": 13.0, "max_drawdown_pct": -18.0},
        spy_metrics={"cagr_pct": 10.0, "max_drawdown_pct": -20.0},
    )

    assert summary["recommendation_hint"] == "candidate"
    assert summary["years_beating_spy"] == 1
