import pandas as pd

from backtester.execution import run_strategy_backtest


def test_equity_drawdown_guard_blocks_new_entries_but_allows_exits():
    config = {
        "benchmark_ticker": "SPY",
        "ranking": {"field": "ret_52w_pct"},
        "entry_rule": {"top_n": 1},
        "exit_rule": {"rank_threshold": 1},
        "market_filter": {"require_positive_trend": True, "fallback_allow_if_missing_spy_metric": False},
        "risk_management": {"equity_drawdown_guard": {"enabled": True, "stop_new_entries_drawdown_pct": -15, "resume_drawdown_pct": -8}},
    }
    weekly = pd.DataFrame({
        "date": ["2026-01-31", "2026-01-31", "2026-02-28", "2026-02-28"],
        "ticker": ["SPY", "AAA", "SPY", "BBB"],
        "ret_52w_pct": [0, 50, 0, 60],
        "close": [500, 100, 500, 100],
        "spy_close_vs_sma50_pct": [1, None, 1, None],
    })
    daily = pd.DataFrame({
        "date": ["2026-02-01", "2026-02-01", "2026-02-15", "2026-02-15", "2026-03-01", "2026-03-01"],
        "ticker": ["SPY", "AAA", "SPY", "AAA", "SPY", "BBB"],
        "close": [500, 100, 500, 70, 500, 100],
    })

    result = run_strategy_backtest(weekly, daily, config, {"initial_capital": 100000, "cost_per_side_pct": 0.24, "benchmark_ticker": "SPY"})

    assert result["diagnostics"]["equity_drawdown_guard"]["activations"] >= 1
    assert result["diagnostics"]["equity_drawdown_guard"]["blocked_rebalances"] >= 1
    assert "BBB" not in set(result["trades"].get("ticker", []))
