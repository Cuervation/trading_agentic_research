"""Daily execution model for the V1 strategy backtest."""

from __future__ import annotations

import pandas as pd

from backtester.costs import calculate_trade_net_return
from backtester.portfolio import Position, build_equity_row, calculate_positions_value
from backtester.signal_builder import build_momentum_trend_signals


EQUITY_COLUMNS = ["date", "equity", "cash", "gross_exposure", "positions_count"]
TRADE_COLUMNS = [
    "ticker",
    "signal_date",
    "entry_date",
    "exit_date",
    "holding_days",
    "entry_reason",
    "exit_reason",
    "entry_rank",
    "entry_ranking_value",
    "shares",
    "entry_price",
    "exit_price",
    "notional_entry",
    "notional_exit",
    "entry_cost",
    "exit_cost",
    "max_price_since_entry",
    "drawdown_from_peak_pct",
    "gross_return_pct",
    "net_return_pct",
]


def run_strategy_backtest(weekly_df, daily_df, strategy_config, project_config) -> dict:
    """Run a simple monthly long-only momentum backtest.

    V1 intentionally does not implement stop loss, take profit, or trailing stops.
    Signals are generated from weekly snapshots and executed at the first daily close
    strictly after each signal date.
    """
    initial_capital = float(project_config.get("initial_capital", 100000))
    cost_per_side_pct = float(project_config.get("cost_per_side_pct", 0.24))
    trailing_stop_pct = _get_trailing_stop_pct(strategy_config)
    breakeven_after_gain_pct = _get_breakeven_after_gain_pct(strategy_config)
    breakeven_buffer_pct = _get_breakeven_buffer_pct(strategy_config)
    max_gross_exposure_pct = _get_max_gross_exposure_pct(strategy_config)
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
                target_details=plan["target_details"],
                market_filter_passed=plan["market_filter_passed"],
                cash=cash,
                positions=positions,
                day_prices=day_prices,
                cost_per_side_pct=cost_per_side_pct,
                max_gross_exposure_pct=max_gross_exposure_pct,
                trade_rows=trade_rows,
                warnings=warnings,
            )
            processed_rebalances += 1

        valuation_prices = valuation_matrix.loc[current_date].dropna().to_dict()
        cash = _process_trailing_stops(
            current_date=current_date,
            cash=cash,
            positions=positions,
            prices=valuation_prices,
            trailing_stop_pct=trailing_stop_pct,
            breakeven_after_gain_pct=breakeven_after_gain_pct,
            breakeven_buffer_pct=breakeven_buffer_pct,
            cost_per_side_pct=cost_per_side_pct,
            trade_rows=trade_rows,
        )
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
        target_details = {}
        if market_filter_passed:
            selected = group.loc[group["selected_top_n"].astype(bool)].copy()
            target_tickers = set(selected["ticker"].astype(str).tolist())
            for _, row in selected.iterrows():
                ticker = str(row["ticker"])
                target_details[ticker] = {
                    "signal_date": signal_date,
                    "entry_reason": str(row.get("action_candidate", "selected_top_n")),
                    "entry_rank": int(row["rank"]) if pd.notna(row.get("rank")) else None,
                    "entry_ranking_value": float(row["ranking_value"]) if pd.notna(row.get("ranking_value")) else None,
                }
        else:
            target_tickers = set()

        plan[execution_date] = {
            "signal_date": signal_date,
            "target_tickers": target_tickers,
            "target_details": target_details,
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
    target_details: dict[str, dict],
    market_filter_passed: bool,
    cash: float,
    positions: dict[str, Position],
    day_prices: dict[str, float],
    cost_per_side_pct: float,
    max_gross_exposure_pct: float,
    trade_rows: list[dict],
    warnings: list[str],
) -> float:
    """Rebalance to equal-weight targets using current-day close prices.

    Sequence:
    1. Sell names outside the target universe.
    2. Drop target names without executable prices.
    3. Trim overweight target positions.
    4. Scale buys to available cash so rebalances do not fail due to cash shortage.
    """
    exit_reason = "market_filter_failed" if not market_filter_passed else "left_top_n"

    valid_target_tickers = {
        ticker for ticker in target_tickers
        if ticker in day_prices and float(day_prices[ticker]) > 0
    }
    missing_entry_tickers = sorted(target_tickers - valid_target_tickers)
    for ticker in missing_entry_tickers:
        warnings.append(f"No entry price for {ticker} on {current_date.date()}; entry skipped.")

    # First, close anything that should not remain in the portfolio.
    for ticker in list(positions.keys()):
        if ticker not in valid_target_tickers:
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

    if not market_filter_passed or not valid_target_tickers:
        return cash

    cost_rate = cost_per_side_pct / 100.0

    # Trim existing overweight positions before buying underweights/new positions.
    cash = _trim_overweights_to_target(
        current_date=current_date,
        cash=cash,
        positions=positions,
        target_tickers=valid_target_tickers,
        day_prices=day_prices,
        cost_per_side_pct=cost_per_side_pct,
        max_gross_exposure_pct=max_gross_exposure_pct,
        trade_rows=trade_rows,
    )

    portfolio_value = cash + calculate_positions_value(positions, day_prices)
    target_value = (portfolio_value * max_gross_exposure_pct) / len(valid_target_tickers)

    buy_orders: list[tuple[str, float]] = []
    for ticker in sorted(valid_target_tickers):
        current_value = _position_value(positions.get(ticker), day_prices.get(ticker))
        deficit = target_value - current_value
        if deficit > 0:
            buy_orders.append((ticker, deficit))

    total_required_cash = sum(value * (1.0 + cost_rate) for _, value in buy_orders)
    scale = min(1.0, cash / total_required_cash) if total_required_cash > 0 else 0.0

    for ticker, desired_value in buy_orders:
        buy_value = desired_value * scale
        if buy_value <= 0:
            continue

        price = float(day_prices[ticker])
        shares = buy_value / price
        entry_cost = buy_value * cost_rate
        cash -= buy_value + entry_cost
        signal_detail = target_details.get(ticker, {})

        if ticker in positions:
            _add_to_existing_position(
                position=positions[ticker],
                shares=shares,
                buy_value=buy_value,
                entry_cost=entry_cost,
                price=price,
                signal_detail=signal_detail,
            )
        else:
            positions[ticker] = Position(
                ticker=ticker,
                shares=shares,
                entry_date=current_date,
                entry_price=price,
                signal_date=signal_detail.get("signal_date"),
                entry_reason=signal_detail.get("entry_reason", "enter_or_hold"),
                entry_rank=signal_detail.get("entry_rank"),
                entry_ranking_value=signal_detail.get("entry_ranking_value"),
                notional_entry=buy_value,
                entry_cost=entry_cost,
                max_price_since_entry=price,
            )

    return cash


def _trim_overweights_to_target(
    current_date: pd.Timestamp,
    cash: float,
    positions: dict[str, Position],
    target_tickers: set[str],
    day_prices: dict[str, float],
    cost_per_side_pct: float,
    max_gross_exposure_pct: float,
    trade_rows: list[dict],
) -> float:
    if not target_tickers:
        return cash

    portfolio_value = cash + calculate_positions_value(positions, day_prices)
    target_value = (portfolio_value * max_gross_exposure_pct) / len(target_tickers)

    for ticker in sorted(target_tickers):
        position = positions.get(ticker)
        price = day_prices.get(ticker)
        current_value = _position_value(position, price)
        excess_value = current_value - target_value
        if position is None or price is None or excess_value <= 0:
            continue

        shares_to_sell = min(position.shares, excess_value / float(price))
        if shares_to_sell <= 0:
            continue
        cash = _sell_position_shares(
            ticker=ticker,
            shares_to_sell=shares_to_sell,
            exit_date=current_date,
            exit_price=float(price),
            cash=cash,
            positions=positions,
            cost_per_side_pct=cost_per_side_pct,
            exit_reason="rebalance_trim",
            trade_rows=trade_rows,
        )

    return cash


def _position_value(position: Position | None, price: float | None) -> float:
    if position is None or price is None:
        return 0.0
    return float(position.shares) * float(price)


def _add_to_existing_position(
    position: Position,
    shares: float,
    buy_value: float,
    entry_cost: float,
    price: float,
    signal_detail: dict,
) -> None:
    old_value = position.shares * position.entry_price
    new_total_shares = position.shares + shares
    if new_total_shares <= 0:
        return

    position.entry_price = (old_value + buy_value) / new_total_shares
    position.shares = new_total_shares
    position.notional_entry += buy_value
    position.entry_cost += entry_cost
    position.entry_reason = signal_detail.get("entry_reason", position.entry_reason)
    position.entry_rank = signal_detail.get("entry_rank", position.entry_rank)
    position.entry_ranking_value = signal_detail.get("entry_ranking_value", position.entry_ranking_value)


def _get_trailing_stop_pct(strategy_config: dict) -> float | None:
    risk_management = strategy_config.get("risk_management", {})
    value = risk_management.get("trailing_stop_pct")
    if value is None:
        return None
    value = float(value)
    return value if value > 0 else None


def _get_breakeven_after_gain_pct(strategy_config: dict) -> float | None:
    risk_management = strategy_config.get("risk_management", {})
    value = risk_management.get("breakeven_after_gain_pct")
    if value is None:
        return None
    value = float(value)
    return value if value > 0 else None


def _get_breakeven_buffer_pct(strategy_config: dict) -> float:
    risk_management = strategy_config.get("risk_management", {})
    value = float(risk_management.get("breakeven_buffer_pct", 0.0) or 0.0)
    return max(value, 0.0)


def _get_max_gross_exposure_pct(strategy_config: dict) -> float:
    risk_management = strategy_config.get("risk_management", {})
    value = risk_management.get("max_gross_exposure_pct", 100)
    value = float(value)
    if value <= 0:
        return 1.0
    return min(value, 100.0) / 100.0


def _process_trailing_stops(
    current_date: pd.Timestamp,
    cash: float,
    positions: dict[str, Position],
    prices: dict[str, float],
    trailing_stop_pct: float | None,
    breakeven_after_gain_pct: float | None,
    breakeven_buffer_pct: float,
    cost_per_side_pct: float,
    trade_rows: list[dict],
) -> float:
    if trailing_stop_pct is None and breakeven_after_gain_pct is None:
        return cash

    stop_fraction = trailing_stop_pct / 100.0 if trailing_stop_pct is not None else None
    breakeven_trigger = (
        1.0 + (breakeven_after_gain_pct / 100.0)
        if breakeven_after_gain_pct is not None
        else None
    )
    breakeven_floor = 1.0 + (breakeven_buffer_pct / 100.0)
    for ticker in list(positions.keys()):
        price = prices.get(ticker)
        if price is None:
            continue
        position = positions[ticker]
        price = float(price)
        position.max_price_since_entry = max(float(position.max_price_since_entry), price)
        drawdown_from_peak_pct = ((price / position.max_price_since_entry) - 1.0) * 100.0
        if (
            breakeven_trigger is not None
            and position.max_price_since_entry >= position.entry_price * breakeven_trigger
            and price <= position.entry_price * breakeven_floor
        ):
            position.stop_exit_peak_price = float(position.max_price_since_entry)
            position.stop_exit_drawdown_from_peak_pct = float(drawdown_from_peak_pct)
            cash = _close_position(
                ticker=ticker,
                exit_date=current_date,
                exit_price=price,
                cash=cash,
                positions=positions,
                cost_per_side_pct=cost_per_side_pct,
                exit_reason="breakeven_stop",
                trade_rows=trade_rows,
            )
            continue

        if stop_fraction is not None and price <= position.max_price_since_entry * (1.0 - stop_fraction):
            position.stop_exit_peak_price = float(position.max_price_since_entry)
            position.stop_exit_drawdown_from_peak_pct = float(drawdown_from_peak_pct)
            cash = _close_position(
                ticker=ticker,
                exit_date=current_date,
                exit_price=price,
                cash=cash,
                positions=positions,
                cost_per_side_pct=cost_per_side_pct,
                exit_reason="trailing_stop",
                trade_rows=trade_rows,
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
    position = positions.get(ticker)
    if position is None:
        return cash
    return _sell_position_shares(
        ticker=ticker,
        shares_to_sell=position.shares,
        exit_date=exit_date,
        exit_price=exit_price,
        cash=cash,
        positions=positions,
        cost_per_side_pct=cost_per_side_pct,
        exit_reason=exit_reason,
        trade_rows=trade_rows,
    )


def _sell_position_shares(
    ticker: str,
    shares_to_sell: float,
    exit_date: pd.Timestamp,
    exit_price: float,
    cash: float,
    positions: dict[str, Position],
    cost_per_side_pct: float,
    exit_reason: str,
    trade_rows: list[dict],
) -> float:
    position = positions[ticker]
    shares_to_sell = min(float(shares_to_sell), float(position.shares))
    if shares_to_sell <= 0:
        return cash

    sell_ratio = shares_to_sell / position.shares
    notional_exit = shares_to_sell * exit_price
    exit_cost = notional_exit * (cost_per_side_pct / 100.0)
    cash += notional_exit - exit_cost
    holding_days = (pd.to_datetime(exit_date) - pd.to_datetime(position.entry_date)).days

    notional_entry_sold = position.notional_entry * sell_ratio
    entry_cost_sold = position.entry_cost * sell_ratio
    gross_return_pct = ((exit_price / position.entry_price) - 1.0) * 100.0
    net_return_pct = calculate_trade_net_return(
        entry_price=position.entry_price,
        exit_price=exit_price,
        cost_per_side_pct=cost_per_side_pct,
    )

    trade_rows.append(
        {
            "ticker": ticker,
            "signal_date": position.signal_date,
            "entry_date": position.entry_date,
            "exit_date": exit_date,
            "holding_days": int(holding_days),
            "entry_reason": position.entry_reason,
            "exit_reason": exit_reason,
            "entry_rank": position.entry_rank,
            "entry_ranking_value": position.entry_ranking_value,
            "shares": float(shares_to_sell),
            "entry_price": float(position.entry_price),
            "exit_price": float(exit_price),
            "notional_entry": float(notional_entry_sold),
            "notional_exit": float(notional_exit),
            "entry_cost": float(entry_cost_sold),
            "exit_cost": float(exit_cost),
            "max_price_since_entry": float(position.stop_exit_peak_price or position.max_price_since_entry),
            "drawdown_from_peak_pct": (
                float(position.stop_exit_drawdown_from_peak_pct)
                if position.stop_exit_drawdown_from_peak_pct is not None
                else float(((exit_price / position.max_price_since_entry) - 1.0) * 100.0)
            ),
            "gross_return_pct": float(gross_return_pct),
            "net_return_pct": float(net_return_pct),
        }
    )

    remaining_shares = position.shares - shares_to_sell
    if remaining_shares <= 1e-10:
        positions.pop(ticker)
    else:
        position.shares = remaining_shares
        position.notional_entry -= notional_entry_sold
        position.entry_cost -= entry_cost_sold

    return cash
