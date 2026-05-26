import pandas as pd

from backtester.signal_builder import build_momentum_trend_signals


def test_no_new_entries_in_crisis_blocks_selected_top_n_only():
    config = {
        "benchmark_ticker": "SPY",
        "ranking": {"field": "ret_52w_pct"},
        "entry_rule": {"top_n": 1},
        "exit_rule": {"rank_threshold": 2},
        "market_filter": {"require_positive_trend": False},
        "risk_management": {"no_new_entries_in_crisis": {"enabled": True, "crisis_threshold_pct": -10, "regime_field_priority": ["spy_close_vs_sma50_pct"]}},
    }
    weekly = pd.DataFrame({
        "date": ["2026-01-31", "2026-01-31", "2026-01-31"],
        "ticker": ["SPY", "AAA", "BBB"],
        "ret_52w_pct": [0, 50, 40],
        "close": [500, 100, 90],
        "spy_close_vs_sma50_pct": [-12, None, None],
    })

    signals = build_momentum_trend_signals(weekly, config)

    assert signals["entry_blocked_by_crisis"].all()
    assert not signals["selected_top_n"].any()
    assert signals["in_exit_universe"].any()
    assert set(signals["action_candidate"]) == {"blocked_by_crisis_guard"}


def test_embedded_spy_fields_drive_dynamic_exposure_without_spy_row():
    config = {
        "benchmark_ticker": "SPY",
        "ranking": {"field": "ret_52w_pct"},
        "entry_rule": {"top_n": 1},
        "exit_rule": {"rank_threshold": 2},
        "market_filter": {"require_positive_trend": True, "fallback_allow_if_missing_spy_metric": False},
        "risk_management": {
            "dynamic_regime_exposure_pct": {"strong": 80, "neutral": 45, "weak": 25, "crisis": 0}
        },
    }
    weekly = pd.DataFrame(
        {
            "date": ["2026-01-31", "2026-01-31"],
            "ticker": ["AAA", "BBB"],
            "ret_52w_pct": [50, 40],
            "close": [100, 90],
            "spy_close_vs_sma50_pct": [5, 5],
            "spy_close_vs_sma52w_pct": [10, 10],
            "spy_close_vs_sma20w_pct": [3, 3],
            "spy_drawdown_from_high_26w_pct": [-2, -2],
        }
    )

    signals = build_momentum_trend_signals(weekly, config)

    assert signals["market_filter_passed"].all()
    assert set(signals["target_gross_exposure_pct"]) == {80.0}
