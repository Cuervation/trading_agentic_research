import pandas as pd

from backtester.execution import run_strategy_backtest
from backtester.signal_builder import build_momentum_trend_signals


def _config(*, weekly=False):
    config = {
        "benchmark_ticker": "SPY",
        "ranking": {"field": "ret_52w_pct"},
        "entry_rule": {"top_n": 1},
        "exit_rule": {"rank_threshold": 2},
        "market_filter": {
            "require_positive_trend": True,
            "fallback_allow_if_missing_spy_metric": False,
        },
    }
    if weekly:
        config.update(
            {
                "decision_frequency": "weekly",
                "entry_frequency": "weekly",
                "exit_frequency": "weekly",
                "position_retention": "hold_until_exit_rank_threshold",
            }
        )
    return config


def _weekly_snapshots():
    rows = []
    ranks = {
        "2026-01-09": {"AAA": 30.0, "BBB": 20.0, "CCC": 10.0},
        "2026-01-16": {"AAA": 20.0, "BBB": 30.0, "CCC": 10.0},
        "2026-01-23": {"AAA": 10.0, "BBB": 30.0, "CCC": 20.0},
    }
    for date, values in ranks.items():
        rows.append(
            {
                "date": date,
                "ticker": "SPY",
                "ret_52w_pct": 0.0,
                "close": 500.0,
                "spy_close_vs_sma50_pct": 1.0,
            }
        )
        for ticker, value in values.items():
            rows.append(
                {
                    "date": date,
                    "ticker": ticker,
                    "ret_52w_pct": value,
                    "close": 10.0,
                    "spy_close_vs_sma50_pct": None,
                }
            )
    return pd.DataFrame(rows)


def _daily_prices():
    rows = []
    for date in ["2026-01-10", "2026-01-17", "2026-01-24"]:
        for ticker, close in [("SPY", 500.0), ("AAA", 10.0), ("BBB", 10.0), ("CCC", 10.0)]:
            rows.append({"date": date, "ticker": ticker, "close": close})
    return pd.DataFrame(rows)


def _project():
    return {
        "initial_capital": 100000,
        "cost_per_side_pct": 0.24,
        "benchmark_ticker": "SPY",
    }


def test_monthly_decision_frequency_keeps_legacy_last_snapshot():
    signals = build_momentum_trend_signals(_weekly_snapshots(), _config())

    assert set(signals["signal_date"]) == {pd.Timestamp("2026-01-23")}


def test_weekly_decision_frequency_uses_every_available_snapshot():
    signals = build_momentum_trend_signals(_weekly_snapshots(), _config(weekly=True))

    assert set(signals["signal_date"]) == {
        pd.Timestamp("2026-01-09"),
        pd.Timestamp("2026-01-16"),
        pd.Timestamp("2026-01-23"),
    }


def test_weekly_exit_holds_existing_position_inside_exit_rank_threshold():
    result = run_strategy_backtest(
        _weekly_snapshots().query("date != '2026-01-23'"),
        _daily_prices(),
        _config(weekly=True),
        _project(),
    )

    jan17 = result["equity_curve"].loc[
        result["equity_curve"]["date"].eq(pd.Timestamp("2026-01-17"))
    ].iloc[0]
    assert int(jan17["positions_count"]) == 2
    assert not (
        result["trades"]["ticker"].eq("AAA")
        & result["trades"]["exit_reason"].eq("left_exit_rank_threshold")
    ).any()


def test_weekly_exit_closes_above_threshold_after_signal_without_lookahead():
    result = run_strategy_backtest(
        _weekly_snapshots(),
        _daily_prices(),
        _config(weekly=True),
        _project(),
    )

    aaa = result["trades"].loc[
        result["trades"]["ticker"].eq("AAA")
        & result["trades"]["exit_reason"].eq("left_exit_rank_threshold")
    ].iloc[0]
    assert aaa["exit_reason"] == "left_exit_rank_threshold"
    assert aaa["exit_date"] == pd.Timestamp("2026-01-24")
    assert aaa["exit_date"] > pd.Timestamp("2026-01-23")
    assert (result["trades"]["entry_date"] > result["trades"]["signal_date"]).all()
