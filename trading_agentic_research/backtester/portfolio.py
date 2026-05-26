"""Portfolio state and position sizing primitives."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass
class Position:
    """Open position tracked by shares, sizing, and entry signal data."""

    ticker: str
    shares: float
    entry_date: object
    entry_price: float
    signal_date: object
    entry_reason: str
    entry_rank: int | None
    entry_ranking_value: float | None
    notional_entry: float
    entry_cost: float
    max_price_since_entry: float
    stop_exit_peak_price: float | None = None
    stop_exit_drawdown_from_peak_pct: float | None = None
    profit_lock_floor_price: float | None = None
    partial_take_profit_done: bool = False
    rank_deterioration_count: int = 0


def calculate_positions_value(
    positions: Mapping[str, Position],
    prices: Mapping[str, float],
) -> float:
    """Mark open positions to market using available prices."""
    total = 0.0
    for ticker, position in positions.items():
        price = prices.get(ticker)
        if price is not None:
            total += position.shares * float(price)
    return float(total)


def calculate_gross_exposure(
    positions: Mapping[str, Position],
    prices: Mapping[str, float],
) -> float:
    """Return long-only gross exposure value."""
    return calculate_positions_value(positions, prices)


def build_equity_row(date, cash: float, positions: Mapping[str, Position], prices: Mapping[str, float]) -> dict:
    """Build one daily portfolio snapshot."""
    gross_exposure = calculate_gross_exposure(positions, prices)
    return {
        "date": date,
        "equity": float(cash + gross_exposure),
        "cash": float(cash),
        "gross_exposure": float(gross_exposure),
        "positions_count": int(len(positions)),
    }
