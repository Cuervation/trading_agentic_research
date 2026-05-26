import pandas as pd

from backtester.execution import run_strategy_backtest


def _config(risk):
    return {
        "benchmark_ticker": "SPY",
        "ranking": {"field": "ret_52w_pct"},
        "entry_rule": {"top_n": 1},
        "exit_rule": {"rank_threshold": 2},
        "market_filter": {"require_positive_trend": False},
        "risk_management": risk,
    }


def _project():
    return {"initial_capital": 100000, "cost_per_side_pct": 0.24, "benchmark_ticker": "SPY"}


def _weekly():
    return pd.DataFrame({"date": ["2026-01-31", "2026-01-31"], "ticker": ["SPY", "AAA"], "ret_52w_pct": [0, 50], "close": [500, 100]})


def test_trailing_activation_blocks_trailing_before_gain_threshold():
    daily = pd.DataFrame({
        "date": ["2026-02-01", "2026-02-01", "2026-02-02", "2026-02-02"],
        "ticker": ["SPY", "AAA", "SPY", "AAA"],
        "close": [500, 100, 500, 88],
    })

    result = run_strategy_backtest(_weekly(), daily, _config({"trailing_stop_pct": 10, "trailing_activation_gain_pct": 10}), _project())

    assert result["trades"].empty


def test_trailing_activation_exits_after_gain_threshold():
    daily = pd.DataFrame({
        "date": ["2026-02-01", "2026-02-01", "2026-02-02", "2026-02-02", "2026-02-03", "2026-02-03"],
        "ticker": ["SPY", "AAA", "SPY", "AAA", "SPY", "AAA"],
        "close": [500, 100, 500, 115, 500, 100],
    })

    result = run_strategy_backtest(_weekly(), daily, _config({"trailing_stop_pct": 10, "trailing_activation_gain_pct": 10}), _project())

    assert list(result["trades"]["exit_reason"]) == ["trailing_stop"]
    assert result["trades"].iloc[0]["exit_date"] == pd.Timestamp("2026-02-03")


def test_trailing_without_activation_keeps_previous_behavior():
    daily = pd.DataFrame({
        "date": ["2026-02-01", "2026-02-01", "2026-02-02", "2026-02-02"],
        "ticker": ["SPY", "AAA", "SPY", "AAA"],
        "close": [500, 100, 500, 88],
    })

    result = run_strategy_backtest(_weekly(), daily, _config({"trailing_stop_pct": 10}), _project())

    assert list(result["trades"]["exit_reason"]) == ["trailing_stop"]
