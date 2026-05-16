"""Cost model utilities."""

from __future__ import annotations


def apply_transaction_cost(return_pct: float, cost_per_side_pct: float, sides: int) -> float:
    """Apply transaction costs to a gross return percentage.

    Args:
        return_pct: Gross return in percentage points (e.g. 5.0 means +5.0%).
        cost_per_side_pct: Cost per side in percentage points (e.g. 0.24 means 0.24%).
        sides: Number of executed sides (e.g. buy+sell = 2).
    """
    total_cost_pct = float(cost_per_side_pct) * int(sides)
    return float(return_pct) - total_cost_pct


def calculate_trade_net_return(
    entry_price: float,
    exit_price: float,
    cost_per_side_pct: float,
) -> float:
    """Calculate net trade return percentage after buy and sell costs."""
    if entry_price <= 0:
        raise ValueError("entry_price must be > 0")

    gross_return_pct = ((float(exit_price) / float(entry_price)) - 1.0) * 100.0
    return apply_transaction_cost(gross_return_pct, cost_per_side_pct=cost_per_side_pct, sides=2)
