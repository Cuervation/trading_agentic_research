import pandas as pd

from backtester.execution import run_strategy_backtest


def _config(risk=None):
    return {
        "benchmark_ticker": "SPY",
        "ranking": {"field": "ret_52w_pct"},
        "entry_rule": {"top_n": 1},
        "exit_rule": {"rank_threshold": 2},
        "market_filter": {"require_positive_trend": False},
        "risk_management": risk or {},
    }


def _project():
    return {"initial_capital": 100000, "cost_per_side_pct": 0.24, "benchmark_ticker": "SPY"}


def _weekly():
    return pd.DataFrame({
        "date": ["2026-01-31", "2026-01-31"],
        "ticker": ["SPY", "AAA"],
        "ret_52w_pct": [0, 50],
        "close": [500, 100],
    })


def test_stop_loss_pct_closes_from_entry_price():
    daily = pd.DataFrame({
        "date": ["2026-02-01", "2026-02-01", "2026-02-02", "2026-02-02"],
        "ticker": ["SPY", "AAA", "SPY", "AAA"],
        "close": [500, 100, 500, 88],
    })

    result = run_strategy_backtest(_weekly(), daily, _config({"stop_loss_pct": 10}), _project())

    assert list(result["trades"]["exit_reason"]) == ["stop_loss"]
    assert result["trades"].iloc[0]["exit_date"] == pd.Timestamp("2026-02-02")


def test_missing_stop_loss_keeps_previous_behavior():
    daily = pd.DataFrame({
        "date": ["2026-02-01", "2026-02-01", "2026-02-02", "2026-02-02"],
        "ticker": ["SPY", "AAA", "SPY", "AAA"],
        "close": [500, 100, 500, 88],
    })

    result = run_strategy_backtest(_weekly(), daily, _config(), _project())

    assert result["trades"].empty
