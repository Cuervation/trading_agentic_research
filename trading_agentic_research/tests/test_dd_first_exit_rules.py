from copy import deepcopy

import pandas as pd

from backtester.execution import run_strategy_backtest


def _strategy_config(top_n=1):
    return {
        "benchmark_ticker": "SPY",
        "ranking": {"field": "ret_52w_pct"},
        "entry_rule": {"top_n": top_n},
        "exit_rule": {"rank_threshold": 2},
        "market_filter": {
            "require_positive_trend": True,
            "fallback_allow_if_missing_spy_metric": False,
        },
    }


def _project_config():
    return {"initial_capital": 100000, "cost_per_side_pct": 0.24, "benchmark_ticker": "SPY"}


def test_profit_lock_steps():
    config = _strategy_config(top_n=1)
    config["risk_management"] = {"profit_lock_steps": [{"gain_pct": 15, "lock_pct": 3}]}
    weekly_df = pd.DataFrame(
        {
            "date": ["2026-01-31", "2026-01-31"],
            "ticker": ["SPY", "AAA"],
            "ret_52w_pct": [0.0, 20.0],
            "close": [500.0, 100.0],
            "spy_close_vs_sma50_pct": [1.0, None],
        }
    )
    daily_df = pd.DataFrame(
        {
            "date": ["2026-02-01", "2026-02-01", "2026-02-02", "2026-02-02", "2026-02-03", "2026-02-03"],
            "ticker": ["SPY", "AAA", "SPY", "AAA", "SPY", "AAA"],
            "close": [501.0, 100.0, 502.0, 120.0, 503.0, 102.0],
        }
    )

    result = run_strategy_backtest(weekly_df, daily_df, config, _project_config())
    trades = result["trades"]
    exit_trade = trades[trades["exit_reason"] == "profit_lock_stop"].iloc[0]

    assert exit_trade["ticker"] == "AAA"
    assert exit_trade["exit_date"] == pd.Timestamp("2026-02-03")
    assert round(exit_trade["max_price_since_entry"], 2) == 120.0


def test_partial_take_profit():
    config = _strategy_config(top_n=1)
    config["risk_management"] = {
        "partial_take_profit": {"enabled": True, "gain_pct": 25, "sell_fraction": 0.5}
    }
    weekly_df = pd.DataFrame(
        {
            "date": ["2026-01-31", "2026-01-31"],
            "ticker": ["SPY", "AAA"],
            "ret_52w_pct": [0.0, 20.0],
            "close": [500.0, 100.0],
            "spy_close_vs_sma50_pct": [1.0, None],
        }
    )
    daily_df = pd.DataFrame(
        {
            "date": ["2026-02-01", "2026-02-01", "2026-02-02", "2026-02-02", "2026-02-03", "2026-02-03"],
            "ticker": ["SPY", "AAA", "SPY", "AAA", "SPY", "AAA"],
            "close": [501.0, 100.0, 502.0, 126.0, 503.0, 130.0],
        }
    )

    result = run_strategy_backtest(weekly_df, daily_df, config, _project_config())
    partials = result["trades"][result["trades"]["exit_reason"] == "partial_take_profit"]

    assert len(partials) == 1
    assert partials.iloc[0]["ticker"] == "AAA"


def test_rank_deterioration_exit():
    config = _strategy_config(top_n=1)
    config["exit_rule"] = {
        "rank_threshold": 40,
        "rank_deterioration_exit": {"enabled": True, "max_rank": 1, "confirm_rebalances": 2},
    }
    weekly_df = pd.DataFrame(
        {
            "date": [
                "2026-01-31", "2026-01-31", "2026-01-31",
                "2026-02-28", "2026-02-28", "2026-02-28",
                "2026-03-31", "2026-03-31", "2026-03-31",
            ],
            "ticker": ["SPY", "AAA", "BBB", "SPY", "AAA", "BBB", "SPY", "AAA", "BBB"],
            "ret_52w_pct": [0.0, 50.0, 10.0, 0.0, 10.0, 60.0, 0.0, 10.0, 70.0],
            "close": [500.0, 100.0, 20.0, 500.0, 101.0, 20.0, 500.0, 102.0, 20.0],
            "spy_close_vs_sma50_pct": [1.0, None, None, 1.0, None, None, 1.0, None, None],
        }
    )
    daily_df = pd.DataFrame(
        {
            "date": [
                "2026-02-01", "2026-02-01", "2026-02-01",
                "2026-03-01", "2026-03-01", "2026-03-01",
                "2026-04-01", "2026-04-01", "2026-04-01",
            ],
            "ticker": ["SPY", "AAA", "BBB", "SPY", "AAA", "BBB", "SPY", "AAA", "BBB"],
            "close": [501.0, 100.0, 20.0, 502.0, 101.0, 20.0, 503.0, 102.0, 20.0],
        }
    )

    result = run_strategy_backtest(weekly_df, daily_df, config, _project_config())
    rank_exits = result["trades"][result["trades"]["exit_reason"] == "rank_deterioration_exit"]

    assert len(rank_exits) == 1
    assert rank_exits.iloc[0]["ticker"] == "AAA"


def test_disabled_exit_knobs_do_not_change_behavior():
    base = _strategy_config(top_n=1)
    disabled = deepcopy(base)
    disabled["risk_management"] = {
        "trailing_stop_pct": 0,
        "breakeven_after_gain_pct": 0,
        "profit_lock_steps": [],
        "partial_take_profit": {"enabled": False},
    }
    disabled["exit_rule"] = {
        "rank_threshold": 2,
        "rank_deterioration_exit": {"enabled": False, "max_rank": 25, "confirm_rebalances": 2},
    }
    weekly_df = pd.DataFrame(
        {
            "date": ["2026-01-31", "2026-01-31"],
            "ticker": ["SPY", "AAA"],
            "ret_52w_pct": [0.0, 20.0],
            "close": [500.0, 100.0],
            "spy_close_vs_sma50_pct": [1.0, None],
        }
    )
    daily_df = pd.DataFrame(
        {
            "date": ["2026-02-01", "2026-02-01"],
            "ticker": ["SPY", "AAA"],
            "close": [501.0, 100.0],
        }
    )

    base_result = run_strategy_backtest(weekly_df, daily_df, base, _project_config())
    disabled_result = run_strategy_backtest(weekly_df, daily_df, disabled, _project_config())

    assert list(base_result["trades"]["exit_reason"]) == list(disabled_result["trades"]["exit_reason"])
