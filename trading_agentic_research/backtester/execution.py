"""Daily execution model for the V1 strategy backtest."""

from __future__ import annotations

import pandas as pd

from backtester.costs import calculate_trade_net_return
from backtester.portfolio import Position, build_equity_row, calculate_positions_value
from backtester.signal_builder import build_momentum_trend_signals


EQUITY_COLUMNS = ["date", "equity", "cash", "gross_exposure", "positions_count"]
TRADE_COLUMNS = [
    "ticker",
    "entry_date",
    "exit_date",
    "entry_price",
    "exit_price",
    "gross_return_pct",
    "net_return_pct",
    "exit_reason",
]


def run_strategy_backtest(weekly_df, daily_df, strategy_config, project_config) -> dict:
    """Run a simple monthly long-only momentum backtest.

    V1 intentionally does not implement stop loss, take profit, or trailing stops.
    Signals are generated from weekly snapshots and executed at the first daily close
    strictly after each signal date.
    """
    initial_capital = float(project_config.get("initial_capital", 100000))
    cost_per_side_pct = float(project_config.get("cost_per_side_pct", 0.24))
    benchmark_ticker = str(
        strategy_config.get("benchmark_ticker")
        or project_config.get("benchmark_ticker", "SPY")
    )

    warnings: list[str] = []
    signals = build_momentum_trend_signals(weekly_df, strategy_config)
    prices = _prepare_daily_prices(daily_df, benchmark_ticker=benchmark_ticker)

    if prices.empty:
        equity_curve = pd.DataFrame(columns=EQUITY_COLUMNS)
        return {
            "equity_curve": equity_curve,
            "trades": pd.DataFrame(columns=TRADE_COLUMNS),
            "diagnostics": {
                "number_of_rebalances": 0,
                "number_of_trades": 0,
                "start_date": None,
                "end_date": None,
                "warnings": ["No daily prices available after excluding benchmark ticker."],
            },
        }

    close_matrix = prices.pivot(index="date", columns="ticker", values="close").sort_index()
    valuation_matrix = close_matrix.ffill()
    daily_dates = list(close_matrix.index)

    rebalance_plan = _build_rebalance_plan(signals, close_matrix, warnings)

    cash = initial_capital
    positions: dict[str, Position] = {}
    trade_rows: list[dict] = []
    equity_rows: list[dict] = []
    processed_rebalances = 0

    for current_date in daily_dates:
        if current_date in rebalance_plan:
            plan = rebalance_plan[current_date]
            day_prices = close_matrix.loc[current_date].dropna().to_dict()
            cash = _process_rebalance(
                current_date=current_date,
                target_tickers=plan["target_tickers"],
                market_filter_passed=plan["market_filter_passed"],
                cash=cash,
                positions=positions,
                day_prices=day_prices,
                cost_per_side_pct=cost_per_side_pct,
                trade_rows=trade_rows,
                warnings=warnings,
            )
            processed_rebalances += 1

        valuation_prices = valuation_matrix.loc[current_date].dropna().to_dict()
        equity_rows.append(build_equity_row(current_date, cash, positions, valuation_prices))

    equity_curve = pd.DataFrame(equity_rows, columns=EQUITY_COLUMNS)
    trades = pd.DataFrame(trade_rows, columns=TRADE_COLUMNS)

    diagnostics = {
        "number_of_rebalances": int(processed_rebalances),
        "number_of_trades": int(len(trades)),
        "start_date": equity_curve["date"].min() if not equity_curve.empty else None,
        "end_date": equity_curve["date"].max() if not equity_curve.empty else None,
        "warnings": warnings,
    }

    return {"equity_curve": equity_curve, "trades": trades, "diagnostics": diagnostics}


def _prepare_daily_prices(daily_df: pd.DataFrame, benchmark_ticker: str) -> pd.DataFrame:
    required = {"date", "ticker", "close"}
    missing = required - set(daily_df.columns)
    if missing:
        raise ValueError(f"daily_df missing required columns: {sorted(missing)}")

    prices = daily_df.copy()
    prices["date"] = pd.to_datetime(prices["date"], errors="coerce")
    prices = prices.dropna(subset=["date", "ticker", "close"])
    prices = prices[prices["ticker"] != benchmark_ticker]
    prices["close"] = prices["close"].astype(float)
    prices = prices.sort_values(["date", "ticker"], kind="mergesort")
    return prices[["date", "ticker", "close"]]


def _build_rebalance_plan(
    signals: pd.DataFrame,
    close_matrix: pd.DataFrame,
    warnings: list[str],
) -> dict[pd.Timestamp, dict]:
    if signals.empty:
        return {}

    signal_df = signals.copy()
    signal_df["signal_date"] = pd.to_datetime(signal_df["signal_date"], errors="coerce")
    plan: dict[pd.Timestamp, dict] = {}

    for signal_date, group in signal_df.groupby("signal_date", sort=True):
        execution_date = _first_daily_date_after(close_matrix.index, signal_date)
        if execution_date is None:
            warnings.append(f"No daily price date after signal_date={signal_date.date()}; skipped rebalance.")
            continue

        market_filter_passed = bool(group["market_filter_passed"].all())
        if market_filter_passed:
            target_tickers = set(
                group.loc[group["selected_top_n"].astype(bool), "ticker"].astype(str).tolist()
            )
        else:
            target_tickers = set()

        plan[execution_date] = {
            "signal_date": signal_date,
            "target_tickers": target_tickers,
            "market_filter_passed": market_filter_passed,
        }

    return plan


def _first_daily_date_after(daily_index: pd.Index, signal_date: pd.Timestamp):
    future_dates = daily_index[daily_index > signal_date]
    if len(future_dates) == 0:
        return None
    return future_dates[0]


def _process_rebalance(
    current_date: pd.Timestamp,
    target_tickers: set[str],
    market_filter_passed: bool,
    cash: float,
    positions: dict[str, Position],
    day_prices: dict[str, float],
    cost_per_side_pct: float,
    trade_rows: list[dict],
    warnings: list[str],
) -> float:
    exit_reason = "market_filter_failed" if not market_filter_passed else "left_top_n"

    for ticker in list(positions.keys()):
        if ticker not in target_tickers:
            price = day_prices.get(ticker)
            if price is None:
                warnings.append(f"No exit price for {ticker} on {current_date.date()}; position kept.")
                continue
            cash = _close_position(
                ticker=ticker,
                exit_date=current_date,
                exit_price=float(price),
                cash=cash,
                positions=positions,
                cost_per_side_pct=cost_per_side_pct,
                exit_reason=exit_reason,
                trade_rows=trade_rows,
            )

    if not market_filter_passed or not target_tickers:
        return cash

    new_tickers = sorted(ticker for ticker in target_tickers if ticker not in positions)
    if not new_tickers:
        return cash

    valid_entry_tickers = [ticker for ticker in new_tickers if ticker in day_prices]
    missing_entry_tickers = sorted(set(new_tickers) - set(valid_entry_tickers))
    for ticker in missing_entry_tickers:
        warnings.append(f"No entry price for {ticker} on {current_date.date()}; entry skipped.")

    if not valid_entry_tickers:
        return cash

    existing_value = calculate_positions_value(positions, day_prices)
    portfolio_value = cash + existing_value
    target_value = portfolio_value / max(len(target_tickers), 1)
    cost_rate = cost_per_side_pct / 100.0

    for ticker in valid_entry_tickers:
        affordable_value = min(target_value, cash / (1.0 + cost_rate))
        if affordable_value <= 0:
            warnings.append(f"Insufficient cash to enter {ticker} on {current_date.date()}.")
            continue

        price = float(day_prices[ticker])
        shares = affordable_value / price
        entry_cost = affordable_value * cost_rate
        cash -= affordable_value + entry_cost
        positions[ticker] = Position(
            ticker=ticker,
            shares=shares,
            entry_date=current_date,
            entry_price=price,
        )

    return cash


def _close_position(
    ticker: str,
    exit_date: pd.Timestamp,
    exit_price: float,
    cash: float,
    positions: dict[str, Position],
    cost_per_side_pct: float,
    exit_reason: str,
    trade_rows: list[dict],
) -> float:
    position = positions.pop(ticker)
    gross_value = position.shares * exit_price
    exit_cost = gross_value * (cost_per_side_pct / 100.0)
    cash += gross_value - exit_cost

    gross_return_pct = ((exit_price / position.entry_price) - 1.0) * 100.0
    net_return_pct = calculate_trade_net_return(
        entry_price=position.entry_price,
        exit_price=exit_price,
        cost_per_side_pct=cost_per_side_pct,
    )

    trade_rows.append(
        {
            "ticker": ticker,
            "entry_date": position.entry_date,
            "exit_date": exit_date,
            "entry_price": float(position.entry_price),
            "exit_price": float(exit_price),
            "gross_return_pct": float(gross_return_pct),
            "net_return_pct": float(net_return_pct),
            "exit_reason": exit_reason,
        }
    )
    return cash



