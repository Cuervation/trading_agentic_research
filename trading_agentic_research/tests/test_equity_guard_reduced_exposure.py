import pandas as pd

from backtester.execution import _process_rebalance


def test_reduced_exposure_pct_when_active_caps_effective_exposure():
    cash = _process_rebalance(
        current_date=pd.Timestamp("2026-01-31"),
        target_tickers={"AAA"},
        exit_tickers=set(),
        target_details={"AAA": {}},
        rank_map={"AAA": 1},
        market_filter_passed=True,
        cash=100000.0,
        positions={},
        day_prices={"AAA": 100.0},
        cost_per_side_pct=0.0,
        max_gross_exposure_pct=0.80,
        rank_deterioration_exit=None,
        block_new_entries=False,
        trade_rows=[],
        warnings=[],
        reduced_exposure_pct_when_active=20,
    )

    assert cash == 80000.0
