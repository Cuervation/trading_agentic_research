import pandas as pd

from backtester.execution import run_strategy_backtest


def test_stop_loss_has_priority_over_trailing_same_day():
    config = {
        "benchmark_ticker": "SPY",
        "ranking": {"field": "ret_52w_pct"},
        "entry_rule": {"top_n": 1},
        "exit_rule": {"rank_threshold": 2},
        "market_filter": {"require_positive_trend": False},
        "risk_management": {"stop_loss_pct": 10, "trailing_stop_pct": 5},
    }
    weekly = pd.DataFrame({"date": ["2026-01-31", "2026-01-31"], "ticker": ["SPY", "AAA"], "ret_52w_pct": [0, 50], "close": [500, 100]})
    daily = pd.DataFrame({
        "date": ["2026-02-01", "2026-02-01", "2026-02-02", "2026-02-02"],
        "ticker": ["SPY", "AAA", "SPY", "AAA"],
        "close": [500, 100, 500, 88],
    })

    result = run_strategy_backtest(weekly, daily, config, {"initial_capital": 100000, "cost_per_side_pct": 0.24, "benchmark_ticker": "SPY"})

    assert list(result["trades"]["exit_reason"]) == ["stop_loss"]
