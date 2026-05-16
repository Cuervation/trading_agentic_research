import pandas as pd

from backtester.signal_builder import build_momentum_trend_signals


def _base_config():
    return {
        "benchmark_ticker": "SPY",
        "ranking": {"field": "ret_52w_pct"},
        "entry_rule": {"top_n": 2},
        "exit_rule": {"rank_threshold": 3},
        "market_filter": {
            "require_positive_trend": True,
            "fallback_allow_if_missing_spy_metric": True,
        },
    }


def test_build_momentum_trend_signals_monthly_last_date_and_no_spy_in_output():
    weekly_df = pd.DataFrame(
        {
            "date": [
                "2026-01-10",
                "2026-01-10",
                "2026-01-10",
                "2026-01-31",
                "2026-01-31",
                "2026-01-31",
                "2026-01-31",
                "2026-02-28",
                "2026-02-28",
                "2026-02-28",
            ],
            "ticker": ["SPY", "AAA", "BBB", "SPY", "AAA", "BBB", "CCC", "SPY", "AAA", "BBB"],
            "ret_52w_pct": [1.0, 20.0, 10.0, 2.0, 15.0, 25.0, 5.0, 3.0, 12.0, 8.0],
            "close": [500, 10, 11, 505, 10.5, 12, 7, 510, 11, 10],
            "spy_close_vs_sma50_pct": [1.0, None, None, 0.5, None, None, None, 0.2, None, None],
        }
    )

    signals = build_momentum_trend_signals(weekly_df, _base_config())

    assert set(signals["signal_date"].dt.strftime("%Y-%m-%d").unique()) == {"2026-01-31", "2026-02-28"}
    assert "SPY" not in set(signals["ticker"])


def test_build_momentum_trend_signals_ranking_and_flags():
    weekly_df = pd.DataFrame(
        {
            "date": ["2026-01-31", "2026-01-31", "2026-01-31", "2026-01-31"],
            "ticker": ["SPY", "AAA", "BBB", "CCC"],
            "ret_52w_pct": [1.0, 30.0, 20.0, 10.0],
            "close": [500, 10, 11, 12],
            "spy_close_vs_sma50_pct": [0.3, None, None, None],
        }
    )

    signals = build_momentum_trend_signals(weekly_df, _base_config())

    aaa = signals[signals["ticker"] == "AAA"].iloc[0]
    ccc = signals[signals["ticker"] == "CCC"].iloc[0]

    assert int(aaa["rank"]) == 1
    assert bool(aaa["selected_top_n"]) is True
    assert bool(ccc["selected_top_n"]) is False
    assert bool(ccc["in_exit_universe"]) is True
    assert aaa["action_candidate"] == "enter_or_hold"


def test_build_momentum_trend_signals_market_filter_blocks_when_negative():
    cfg = _base_config()
    weekly_df = pd.DataFrame(
        {
            "date": ["2026-01-31", "2026-01-31", "2026-01-31"],
            "ticker": ["SPY", "AAA", "BBB"],
            "ret_52w_pct": [1.0, 30.0, 20.0],
            "close": [500, 10, 11],
            "spy_close_vs_sma50_pct": [-0.1, None, None],
        }
    )

    signals = build_momentum_trend_signals(weekly_df, cfg)

    assert signals["market_filter_passed"].eq(False).all()
    assert set(signals["action_candidate"]) == {"blocked_by_market_filter"}


def test_build_momentum_trend_signals_fallback_warning_when_spy_metric_missing():
    cfg = _base_config()
    weekly_df = pd.DataFrame(
        {
            "date": ["2026-01-31", "2026-01-31", "2026-01-31"],
            "ticker": ["SPY", "AAA", "BBB"],
            "ret_52w_pct": [1.0, 30.0, 20.0],
            "close": [500, 10, 11],
        }
    )

    signals = build_momentum_trend_signals(weekly_df, cfg)

    assert signals["market_filter_passed"].eq(True).all()
