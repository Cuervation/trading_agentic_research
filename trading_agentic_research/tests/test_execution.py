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
    return {
        "initial_capital": 100000,
        "cost_per_side_pct": 0.24,
        "benchmark_ticker": "SPY",
    }


def test_run_strategy_backtest_executes_after_signal_date_not_on_signal_date():
    weekly_df = pd.DataFrame(
        {
            "date": ["2026-01-31", "2026-01-31", "2026-01-31"],
            "ticker": ["SPY", "AAA", "BBB"],
            "ret_52w_pct": [0.0, 20.0, 10.0],
            "close": [500.0, 10.0, 20.0],
            "spy_close_vs_sma50_pct": [1.0, None, None],
        }
    )
    daily_df = pd.DataFrame(
        {
            "date": [
                "2026-01-31", "2026-01-31", "2026-01-31",
                "2026-02-01", "2026-02-01", "2026-02-01",
            ],
            "ticker": ["AAA", "BBB", "SPY", "AAA", "BBB", "SPY"],
            "close": [9.0, 19.0, 500.0, 10.0, 20.0, 501.0],
        }
    )

    result = run_strategy_backtest(weekly_df, daily_df, _strategy_config(), _project_config())
    equity = result["equity_curve"]

    jan31 = equity[equity["date"] == pd.Timestamp("2026-01-31")].iloc[0]
    feb01 = equity[equity["date"] == pd.Timestamp("2026-02-01")].iloc[0]

    assert jan31["positions_count"] == 0
    assert feb01["positions_count"] == 1
    assert feb01["equity"] < 100000  # entry cost was paid
    assert result["diagnostics"]["number_of_rebalances"] == 1


def test_run_strategy_backtest_closes_positions_when_market_filter_fails():
    weekly_df = pd.DataFrame(
        {
            "date": [
                "2026-01-31", "2026-01-31", "2026-01-31",
                "2026-02-28", "2026-02-28", "2026-02-28",
            ],
            "ticker": ["SPY", "AAA", "BBB", "SPY", "AAA", "BBB"],
            "ret_52w_pct": [0.0, 20.0, 10.0, 0.0, 20.0, 10.0],
            "close": [500.0, 10.0, 20.0, 490.0, 12.0, 22.0],
            "spy_close_vs_sma50_pct": [1.0, None, None, -1.0, None, None],
        }
    )
    daily_df = pd.DataFrame(
        {
            "date": [
                "2026-02-01", "2026-02-01", "2026-02-01",
                "2026-03-01", "2026-03-01", "2026-03-01",
            ],
            "ticker": ["AAA", "BBB", "SPY", "AAA", "BBB", "SPY"],
            "close": [10.0, 20.0, 501.0, 12.0, 22.0, 490.0],
        }
    )

    result = run_strategy_backtest(weekly_df, daily_df, _strategy_config(), _project_config())
    trades = result["trades"]
    equity = result["equity_curve"]

    assert len(trades) == 1
    assert trades.iloc[0]["ticker"] == "AAA"
    assert trades.iloc[0]["entry_date"] == pd.Timestamp("2026-02-01")
    assert trades.iloc[0]["exit_date"] == pd.Timestamp("2026-03-01")
    assert round(trades.iloc[0]["gross_return_pct"], 2) == 20.0
    assert round(trades.iloc[0]["net_return_pct"], 2) == 19.52
    trade = trades.iloc[0]
    assert trade["exit_reason"] == "market_filter_failed"
    assert trade["entry_reason"] == "enter_or_hold"
    assert trade["signal_date"] == pd.Timestamp("2026-01-31")
    assert int(trade["entry_rank"]) == 1
    assert round(trade["entry_ranking_value"], 2) == 20.0
    assert round(trade["shares"], 6) > 0
    assert round(trade["notional_entry"], 2) == round(trade["shares"] * trade["entry_price"], 2)
    assert round(trade["notional_exit"], 2) == round(trade["shares"] * trade["exit_price"], 2)
    assert trade["entry_cost"] > 0
    assert trade["exit_cost"] > 0
    assert int(trade["holding_days"]) == 28
    assert equity.iloc[-1]["positions_count"] == 0
    assert result["diagnostics"]["number_of_trades"] == 1


def test_run_strategy_backtest_skips_entry_without_daily_price_after_signal():
    weekly_df = pd.DataFrame(
        {
            "date": ["2026-01-31", "2026-01-31"],
            "ticker": ["SPY", "AAA"],
            "ret_52w_pct": [0.0, 20.0],
            "close": [500.0, 10.0],
            "spy_close_vs_sma50_pct": [1.0, None],
        }
    )
    daily_df = pd.DataFrame(
        {
            "date": ["2026-01-31"],
            "ticker": ["AAA"],
            "close": [10.0],
        }
    )

    result = run_strategy_backtest(weekly_df, daily_df, _strategy_config(), _project_config())

    assert result["trades"].empty
    assert result["equity_curve"].iloc[-1]["positions_count"] == 0
    assert result["diagnostics"]["number_of_rebalances"] == 0
    assert result["diagnostics"]["warnings"]


def test_run_strategy_backtest_does_not_operate_spy():
    weekly_df = pd.DataFrame(
        {
            "date": ["2026-01-31", "2026-01-31", "2026-01-31"],
            "ticker": ["SPY", "AAA", "BBB"],
            "ret_52w_pct": [99.0, 20.0, 10.0],
            "close": [500.0, 10.0, 20.0],
            "spy_close_vs_sma50_pct": [1.0, None, None],
        }
    )
    daily_df = pd.DataFrame(
        {
            "date": ["2026-02-01", "2026-02-01", "2026-02-01"],
            "ticker": ["SPY", "AAA", "BBB"],
            "close": [500.0, 10.0, 20.0],
        }
    )

    result = run_strategy_backtest(weekly_df, daily_df, _strategy_config(top_n=2), _project_config())

    assert "SPY" not in set(result["trades"].get("ticker", []))
    assert result["equity_curve"].iloc[-1]["positions_count"] == 2



def test_run_strategy_backtest_rebalances_equal_weight_without_insufficient_cash_warning():
    weekly_df = pd.DataFrame(
        {
            "date": [
                "2026-01-31", "2026-01-31", "2026-01-31", "2026-01-31",
                "2026-02-28", "2026-02-28", "2026-02-28", "2026-02-28",
            ],
            "ticker": ["SPY", "AAA", "BBB", "CCC", "SPY", "AAA", "BBB", "CCC"],
            "ret_52w_pct": [0.0, 30.0, 20.0, 10.0, 0.0, 30.0, 20.0, 10.0],
            "close": [500.0, 10.0, 20.0, 30.0, 510.0, 20.0, 20.0, 30.0],
            "spy_close_vs_sma50_pct": [1.0, None, None, None, 1.0, None, None, None],
        }
    )
    daily_df = pd.DataFrame(
        {
            "date": [
                "2026-02-01", "2026-02-01", "2026-02-01", "2026-02-01",
                "2026-03-01", "2026-03-01", "2026-03-01", "2026-03-01",
            ],
            "ticker": ["SPY", "AAA", "BBB", "CCC", "SPY", "AAA", "BBB", "CCC"],
            "close": [501.0, 10.0, 20.0, 30.0, 510.0, 20.0, 20.0, 30.0],
        }
    )

    result = run_strategy_backtest(weekly_df, daily_df, _strategy_config(top_n=3), _project_config())
    warnings = result["diagnostics"]["warnings"]
    trades = result["trades"]
    equity = result["equity_curve"]

    assert not any("Insufficient cash" in warning for warning in warnings)
    assert equity.iloc[-1]["positions_count"] == 3
    assert "rebalance_trim" in set(trades["exit_reason"])



def test_run_strategy_backtest_trailing_stop_exits_and_records_peak_drawdown():
    config = _strategy_config(top_n=1)
    config["risk_management"] = {"trailing_stop_pct": 20}
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
            "date": [
                "2026-02-01", "2026-02-01",
                "2026-02-02", "2026-02-02",
                "2026-02-03", "2026-02-03",
            ],
            "ticker": ["SPY", "AAA", "SPY", "AAA", "SPY", "AAA"],
            "close": [501.0, 100.0, 502.0, 130.0, 503.0, 100.0],
        }
    )

    result = run_strategy_backtest(weekly_df, daily_df, config, _project_config())
    trades = result["trades"]
    stop_trade = trades[trades["exit_reason"] == "trailing_stop"].iloc[0]

    assert stop_trade["ticker"] == "AAA"
    assert stop_trade["exit_date"] == pd.Timestamp("2026-02-03")
    assert round(stop_trade["max_price_since_entry"], 2) == 130.0
    assert round(stop_trade["drawdown_from_peak_pct"], 2) == -23.08
    assert result["equity_curve"].iloc[-1]["positions_count"] == 0
