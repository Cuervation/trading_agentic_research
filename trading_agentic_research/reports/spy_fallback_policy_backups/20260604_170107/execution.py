"""Daily execution model for the V1 strategy backtest."""

from __future__ import annotations

import re

import pandas as pd

from backtester.costs import calculate_trade_net_return
from backtester.portfolio import Position, build_equity_row, calculate_positions_value
from backtester.signal_builder import build_momentum_trend_signals


EQUITY_COLUMNS = [
    "date",
    "equity",
    "cash",
    "gross_exposure",
    "positions_count",
    "portfolio_drawdown_pct",
    "risk_state",
    "risk_target_exposure_pct",
]
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


def run_strategy_backtest(weekly_df, daily_df, strategy_config, project_config, signals_override=None) -> dict:
    """Run a simple monthly long-only momentum backtest.

    Signals are generated from weekly snapshots and executed at the first daily close
    strictly after each signal date. Optional risk controls stay disabled unless the
    config explicitly enables them.
    """
    initial_capital = float(project_config.get("initial_capital", 100000))
    base_cost_per_side_pct = float(project_config.get("cost_per_side_pct", 0.24))
    execution_costs = _get_execution_costs(strategy_config, project_config, base_cost_per_side_pct)
    cost_per_side_pct = float(execution_costs["effective_cost_per_side_pct"])
    execution_timing = _get_execution_timing(strategy_config)
    strict_next_close = bool(execution_timing.get("strict_next_close_enabled"))
    strict_next_open = bool(execution_timing.get("strict_next_open_enabled"))
    execution_timing_mode = str(execution_timing.get("execution_timing_mode", "current_default"))
    strict_apply_to = set(execution_timing.get("apply_to", []))
    strict_any_delayed = strict_next_close or strict_next_open
    strict_guard_timing = strict_any_delayed and bool(strict_apply_to & {"portfolio_drawdown_guard", "reentry"})
    strict_stop_timing = strict_any_delayed and "position_stop_loss" in strict_apply_to
    trailing_stop_pct = _get_trailing_stop_pct(strategy_config)
    trailing_activation_gain_pct = _get_trailing_activation_gain_pct(strategy_config)
    stop_loss_pct = _get_stop_loss_pct(strategy_config)
    breakeven_after_gain_pct = _get_breakeven_after_gain_pct(strategy_config)
    breakeven_buffer_pct = _get_breakeven_buffer_pct(strategy_config)
    profit_lock_steps = _get_profit_lock_steps(strategy_config)
    partial_take_profit = _get_partial_take_profit(strategy_config)
    rank_deterioration_exit = _get_rank_deterioration_exit(strategy_config)
    max_gross_exposure_pct = _get_max_gross_exposure_pct(strategy_config)
    equity_drawdown_guard = _get_equity_drawdown_guard(strategy_config)
    portfolio_drawdown_guard = _get_portfolio_drawdown_guard(strategy_config)
    max_drawdown_kill_switch = _get_max_drawdown_kill_switch(strategy_config)
    benchmark_ticker = str(
        strategy_config.get("benchmark_ticker")
        or project_config.get("benchmark_ticker", "SPY")
    )

    warnings: list[str] = []
    signals = signals_override.copy() if signals_override is not None else build_momentum_trend_signals(weekly_df, strategy_config)
    benchmark_context = _prepare_benchmark_context(daily_df, benchmark_ticker=benchmark_ticker)
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
    open_matrix = (
        prices.pivot(index="date", columns="ticker", values="open").sort_index()
        if "open" in prices.columns
        else close_matrix
    )
    valuation_matrix = close_matrix.ffill()
    daily_dates = list(close_matrix.index)

    rebalance_plan = _build_rebalance_plan(signals, close_matrix, warnings)

    cash = initial_capital
    positions: dict[str, Position] = {}
    trade_rows: list[dict] = []
    equity_rows: list[dict] = []
    processed_rebalances = 0
    equity_peak = initial_capital
    equity_guard_active = False
    equity_guard_activations = 0
    equity_guard_blocked_rebalances = 0
    equity_guard_partial_rebalances = 0
    equity_guard_cooldown_remaining = 0
    kill_switch_violated = False
    kill_switch_first_date = None
    risk_events: list[dict] = []
    portfolio_guard_runtime = {
        "state": "normal",
        "active_since": None,
        "last_state_change": None,
    }
    portfolio_guard_activations = 0
    portfolio_guard_reentries = 0
    portfolio_guard_scales = 0
    reduced_exposure_days = 0
    crisis_mode_days = 0
    delayed_execution_count = 0
    same_close_execution_count = 0
    previous_equity_dd_pct = None
    previous_benchmark_row = None
    previous_valuation_prices = None

    for current_date in daily_dates:
        valuation_prices = valuation_matrix.loc[current_date].dropna().to_dict()
        current_equity = cash + calculate_positions_value(positions, valuation_prices)
        equity_peak = max(equity_peak, current_equity)
        current_equity_dd_pct = ((current_equity / equity_peak) - 1.0) * 100.0 if equity_peak > 0 else 0.0
        if equity_drawdown_guard:
            if equity_guard_active and current_equity_dd_pct >= equity_drawdown_guard["resume_drawdown_pct"]:
                equity_guard_active = False
                equity_guard_cooldown_remaining = 0
            elif (not equity_guard_active) and current_equity_dd_pct <= equity_drawdown_guard["stop_new_entries_drawdown_pct"]:
                equity_guard_active = True
                equity_guard_activations += 1
                equity_guard_cooldown_remaining = int(equity_drawdown_guard.get("cooldown_rebalances") or 0)
        if max_drawdown_kill_switch and current_equity_dd_pct <= max_drawdown_kill_switch["stop_backtest_drawdown_pct"]:
            if not kill_switch_violated:
                kill_switch_first_date = current_date
            kill_switch_violated = True

        if portfolio_drawdown_guard:
            benchmark_row = _benchmark_row_for_date(benchmark_context, current_date)
            guard_signal_dd = previous_equity_dd_pct if strict_guard_timing else current_equity_dd_pct
            guard_signal_benchmark = previous_benchmark_row if strict_guard_timing else benchmark_row
            if guard_signal_dd is not None:
                portfolio_events = _update_portfolio_guard_runtime(
                    runtime=portfolio_guard_runtime,
                    guard=portfolio_drawdown_guard,
                    current_date=current_date,
                    current_drawdown_pct=guard_signal_dd,
                    benchmark_row=guard_signal_benchmark,
                )
            else:
                portfolio_events = []
            for event in portfolio_events:
                if strict_guard_timing:
                    event["execution_timing_mode"] = "strict_next_close"
                    event["signal_detected_previous_close"] = True
                    delayed_execution_count += 1
                else:
                    same_close_execution_count += 1
                if event.get("event") in {"guard_reduce_on", "guard_crisis_on"}:
                    portfolio_guard_activations += 1
                if event.get("event") == "guard_reentry":
                    portfolio_guard_reentries += 1
                risk_events.append(event)

        portfolio_risk_state = str(portfolio_guard_runtime.get("state", "normal"))
        portfolio_target_exposure_pct = _portfolio_guard_target_exposure_pct(
            portfolio_drawdown_guard,
            portfolio_risk_state,
        )

        if portfolio_risk_state == "crisis":
            crisis_mode_days += 1
        elif portfolio_risk_state == "reduced":
            reduced_exposure_days += 1

        if (
            portfolio_drawdown_guard
            and portfolio_target_exposure_pct is not None
            and current_date not in rebalance_plan
        ):
            cash, scaled_count = _scale_positions_to_target_gross_exposure(
                current_date=current_date,
                cash=cash,
                positions=positions,
                prices=valuation_prices,
                cost_per_side_pct=cost_per_side_pct,
                target_exposure_pct=portfolio_target_exposure_pct,
                exit_reason=(
                    "portfolio_guard_crisis"
                    if portfolio_risk_state == "crisis"
                    else "portfolio_guard_reduce"
                ),
                trade_rows=trade_rows,
                execution_timing_mode=execution_timing_mode if strict_guard_timing else None,
                signal_detected_date=(daily_dates[daily_dates.index(current_date)-1] if strict_guard_timing and daily_dates.index(current_date) > 0 else None),
            )
            if scaled_count:
                portfolio_guard_scales += 1
                risk_events.append(
                    {
                        "date": current_date,
                        "event": "guard_scale_positions",
                        "state": portfolio_risk_state,
                        "drawdown_pct": float(current_equity_dd_pct),
                        "target_exposure_pct": float(portfolio_target_exposure_pct),
                        "positions_scaled": int(scaled_count),
                    }
                )

        if current_date in rebalance_plan:
            plan = rebalance_plan[current_date]
            day_prices = (
                open_matrix.loc[current_date].dropna().to_dict()
                if strict_next_open
                else close_matrix.loc[current_date].dropna().to_dict()
            )
            guard_policy = _equity_guard_rebalance_policy(
                equity_guard_active=equity_guard_active,
                current_equity_dd_pct=current_equity_dd_pct,
                equity_drawdown_guard=equity_drawdown_guard,
                cooldown_remaining=equity_guard_cooldown_remaining,
            )
            effective_reduced_exposure = guard_policy["reduced_exposure_pct_when_active"]
            if portfolio_target_exposure_pct is not None:
                base_plan_exposure_pct = float(plan.get("max_gross_exposure_pct", max_gross_exposure_pct)) * 100.0
                portfolio_reduced_exposure = min(
                    base_plan_exposure_pct,
                    base_plan_exposure_pct * (portfolio_target_exposure_pct / 100.0),
                )
                effective_reduced_exposure = (
                    portfolio_reduced_exposure
                    if effective_reduced_exposure is None
                    else min(float(effective_reduced_exposure), portfolio_reduced_exposure)
                )
            cash = _process_rebalance(
                current_date=current_date,
                target_tickers=plan["target_tickers"],
                exit_tickers=plan.get("exit_tickers", set()),
                target_details=plan["target_details"],
                rank_map=plan.get("rank_map", {}),
                market_filter_passed=plan["market_filter_passed"],
                cash=cash,
                positions=positions,
                day_prices=day_prices,
                cost_per_side_pct=cost_per_side_pct,
                max_gross_exposure_pct=plan.get("max_gross_exposure_pct", max_gross_exposure_pct),
                rank_deterioration_exit=rank_deterioration_exit,
                block_new_entries=bool(guard_policy["block_new_entries"]),
                reduced_exposure_pct_when_active=effective_reduced_exposure,
                allow_entries_when_active_top_n=guard_policy["allow_entries_when_active_top_n"],
                trade_rows=trade_rows,
                warnings=warnings,
            )
            if guard_policy["block_new_entries"]:
                equity_guard_blocked_rebalances += 1
            elif equity_guard_active and (
                guard_policy["reduced_exposure_pct_when_active"] is not None
                or guard_policy["allow_entries_when_active_top_n"] is not None
            ):
                equity_guard_partial_rebalances += 1
            if equity_guard_active and equity_guard_cooldown_remaining > 0:
                equity_guard_cooldown_remaining -= 1
            processed_rebalances += 1

        stop_signal_prices = previous_valuation_prices if strict_stop_timing else valuation_prices
        cash, stop_delays = _process_trailing_stops(
            current_date=current_date,
            cash=cash,
            positions=positions,
            prices=(open_matrix.loc[current_date].dropna().to_dict() if strict_next_open else valuation_prices),
            signal_prices=stop_signal_prices,
            strict_next_close=strict_stop_timing,
            trailing_stop_pct=trailing_stop_pct,
            trailing_activation_gain_pct=trailing_activation_gain_pct,
            stop_loss_pct=stop_loss_pct,
            breakeven_after_gain_pct=breakeven_after_gain_pct,
            breakeven_buffer_pct=breakeven_buffer_pct,
            profit_lock_steps=profit_lock_steps,
            partial_take_profit=partial_take_profit,
            cost_per_side_pct=cost_per_side_pct,
            trade_rows=trade_rows,
            execution_timing_mode=execution_timing_mode if strict_stop_timing else None,
            signal_detected_date=(daily_dates[daily_dates.index(current_date)-1] if strict_stop_timing and daily_dates.index(current_date) > 0 else None),
        )
        delayed_execution_count += int(stop_delays)
        equity_row = build_equity_row(current_date, cash, positions, valuation_prices)
        equity_row["portfolio_drawdown_pct"] = float(current_equity_dd_pct)
        equity_row["risk_state"] = portfolio_risk_state
        equity_row["risk_target_exposure_pct"] = (
            float(portfolio_target_exposure_pct)
            if portfolio_target_exposure_pct is not None
            else 100.0
        )
        equity_rows.append(equity_row)
        previous_equity_dd_pct = current_equity_dd_pct
        previous_benchmark_row = _benchmark_row_for_date(benchmark_context, current_date)
        previous_valuation_prices = valuation_prices

    equity_curve = pd.DataFrame(equity_rows, columns=EQUITY_COLUMNS)
    trades = pd.DataFrame(trade_rows) if trade_rows else pd.DataFrame(columns=TRADE_COLUMNS)
    if not trades.empty:
        ordered_cols = [c for c in TRADE_COLUMNS if c in trades.columns] + [c for c in trades.columns if c not in TRADE_COLUMNS]
        trades = trades[ordered_cols]

    diagnostics = {
        "number_of_rebalances": int(processed_rebalances),
        "number_of_trades": int(len(trades)),
        "start_date": equity_curve["date"].min() if not equity_curve.empty else None,
        "end_date": equity_curve["date"].max() if not equity_curve.empty else None,
        "warnings": warnings,
        "equity_drawdown_guard": {
            "enabled": bool(equity_drawdown_guard),
            "activations": int(equity_guard_activations),
            "blocked_rebalances": int(equity_guard_blocked_rebalances),
            "partial_rebalances": int(equity_guard_partial_rebalances),
            "cooldown_remaining": int(equity_guard_cooldown_remaining),
            "active_at_end": bool(equity_guard_active),
        },
        "max_drawdown_kill_switch": {
            "enabled": bool(max_drawdown_kill_switch),
            "violated": bool(kill_switch_violated),
            "first_violation_date": kill_switch_first_date,
        },
        "risk_controls": {
            "portfolio_drawdown_guard": {
                "enabled": bool(portfolio_drawdown_guard),
                "activations": int(portfolio_guard_activations),
                "reentries": int(portfolio_guard_reentries),
                "reduced_exposure_days": int(reduced_exposure_days),
                "crisis_mode_days": int(crisis_mode_days),
                "scale_operations": int(portfolio_guard_scales),
                "active_at_end": portfolio_guard_runtime.get("state") != "normal",
                "state_at_end": portfolio_guard_runtime.get("state"),
            },
            "position_stop_loss": {
                "enabled": bool(stop_loss_pct),
                "stop_loss_pct": float(stop_loss_pct) if stop_loss_pct is not None else None,
                "count": int((trades["exit_reason"] == "stop_loss").sum()) if not trades.empty else 0,
            },
        },
        "risk_events": risk_events,
        "execution_timing": {
            "execution_timing_mode": execution_timing_mode,
            "strict_next_close_enabled": bool(strict_next_close),
            "strict_next_open_enabled": bool(strict_next_open),
            "next_open_available": bool("open" in prices.columns),
            "delayed_execution_count": int(delayed_execution_count),
            "same_close_execution_count": int(same_close_execution_count),
            "execution_timing_notes": execution_timing.get("execution_timing_notes", []),
        },
        "execution_costs": execution_costs,
    }

    return {"equity_curve": equity_curve, "trades": trades, "diagnostics": diagnostics}



def _get_execution_timing(strategy_config: dict) -> dict:
    cfg = strategy_config.get("execution_timing", {}) or {}
    enabled = bool(isinstance(cfg, dict) and cfg.get("enabled"))
    mode = str(cfg.get("mode", "current_default") if isinstance(cfg, dict) else "current_default")
    strict_close = enabled and mode == "strict_next_close"
    strict_open = enabled and mode == "strict_next_open"
    return {
        "execution_timing_mode": "strict_next_open" if strict_open else ("strict_next_close" if strict_close else "current_default"),
        "strict_next_close_enabled": bool(strict_close),
        "strict_next_open_enabled": bool(strict_open),
        "apply_to": list(cfg.get("apply_to", [])) if isinstance(cfg, dict) and isinstance(cfg.get("apply_to", []), list) else [],
        "execution_timing_notes": [
            "Default engine remains unchanged unless execution_timing.enabled=true and mode is strict_next_close or strict_next_open.",
            "Strict close mode evaluates portfolio guard/reentry and position stops from the previous available close, then executes at the current available close.",
            "Strict open mode uses the same delayed signal rule but executes at the current available open when open prices are available.",
            "Weekly rebalance signals were already executed at the first daily close strictly after signal_date.",
        ] if (strict_close or strict_open) else ["Default current engine timing."],
    }


def _get_execution_costs(strategy_config: dict, project_config: dict, base_cost_per_side_pct: float) -> dict:
    cfg = strategy_config.get("execution_costs", {}) or {}
    if not isinstance(cfg, dict) or not cfg.get("enabled"):
        return {
            "enabled": False,
            "base_cost_per_side_pct": float(base_cost_per_side_pct),
            "base_slippage_per_side_pct": 0.0,
            "cost_multiplier": 1.0,
            "slippage_multiplier": 1.0,
            "effective_cost_per_side_pct": float(base_cost_per_side_pct),
        }
    cost_multiplier = float(cfg.get("cost_multiplier", 1.0) or 1.0)
    slippage_multiplier = float(cfg.get("slippage_multiplier", 1.0) or 1.0)
    if cfg.get("slippage_bps_per_side") is not None:
        base_slippage = float(cfg.get("slippage_bps_per_side") or 0.0) / 100.0
    else:
        base_slippage = float(cfg.get("slippage_per_side_pct", project_config.get("slippage_per_side_pct", 0.0)) or 0.0)
    effective = max(0.0, float(base_cost_per_side_pct) * cost_multiplier) + max(0.0, base_slippage * slippage_multiplier)
    return {
        "enabled": True,
        "base_cost_per_side_pct": float(base_cost_per_side_pct),
        "base_slippage_per_side_pct": float(base_slippage),
        "cost_multiplier": float(cost_multiplier),
        "slippage_multiplier": float(slippage_multiplier),
        "effective_cost_per_side_pct": float(effective),
    }

def _prepare_benchmark_context(daily_df: pd.DataFrame, benchmark_ticker: str) -> pd.DataFrame:
    if daily_df is None or daily_df.empty or "ticker" not in daily_df.columns:
        return pd.DataFrame()
    required = {"date", "ticker", "close"}
    if not required.issubset(daily_df.columns):
        return pd.DataFrame()
    spy = daily_df[daily_df["ticker"].astype(str) == str(benchmark_ticker)].copy()
    if spy.empty:
        return pd.DataFrame()
    spy["date"] = pd.to_datetime(spy["date"], errors="coerce")
    spy = spy.dropna(subset=["date", "close"]).sort_values("date", kind="mergesort")
    spy = spy.drop_duplicates(subset=["date"], keep="last")
    spy["close"] = pd.to_numeric(spy["close"], errors="coerce")
    if "close_sma_200" not in spy.columns:
        spy["close_sma_200"] = spy["close"].rolling(200, min_periods=200).mean()
    if "close_sma_50" not in spy.columns:
        spy["close_sma_50"] = spy["close"].rolling(50, min_periods=50).mean()
    if "close_sma_50_slope_5d_pct" not in spy.columns:
        spy["close_sma_50_slope_5d_pct"] = (
            (spy["close_sma_50"] / spy["close_sma_50"].shift(5)) - 1.0
        ) * 100.0
    return spy.set_index("date", drop=False)


def _benchmark_row_for_date(benchmark_context: pd.DataFrame, current_date: pd.Timestamp):
    if benchmark_context is None or benchmark_context.empty:
        return None
    try:
        row = benchmark_context.loc[pd.to_datetime(current_date)]
    except KeyError:
        return None
    if isinstance(row, pd.DataFrame):
        return row.iloc[-1]
    return row


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
    if "open" in prices.columns:
        prices["open"] = pd.to_numeric(prices["open"], errors="coerce")
    prices = prices.sort_values(["date", "ticker"], kind="mergesort")
    cols = ["date", "ticker", "close"] + (["open"] if "open" in prices.columns else [])
    return prices[cols]


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
        rank_map: dict[str, int] = {}
        exit_tickers: set[str] = set()
        if market_filter_passed:
            selected = group.loc[group["selected_top_n"].astype(bool)].copy()
            exit_universe = group.loc[group["in_exit_universe"].astype(bool)].copy()
            target_tickers = set(selected["ticker"].astype(str).tolist())
            exit_tickers = set(exit_universe["ticker"].astype(str).tolist())
            for _, row in selected.iterrows():
                ticker = str(row["ticker"])
                target_details[ticker] = {
                    "signal_date": signal_date,
                    "entry_reason": str(row.get("action_candidate", "selected_top_n")),
                    "entry_rank": int(row["rank"]) if pd.notna(row.get("rank")) else None,
                    "entry_ranking_value": float(row["ranking_value"]) if pd.notna(row.get("ranking_value")) else None,
                }
            for _, row in group.iterrows():
                ticker = str(row["ticker"])
                if pd.notna(row.get("rank")):
                    rank_map[ticker] = int(row["rank"])
        else:
            target_tickers = set()

        plan[execution_date] = {
            "signal_date": signal_date,
            "target_tickers": target_tickers,
            "exit_tickers": exit_tickers,
            "rank_map": rank_map,
            "target_details": target_details,
            "market_filter_passed": market_filter_passed,
            "max_gross_exposure_pct": _plan_max_gross_exposure_pct(group),
        }

    return plan


def _plan_max_gross_exposure_pct(group: pd.DataFrame) -> float:
    if "target_gross_exposure_pct" not in group.columns:
        return 1.0
    value = pd.to_numeric(group["target_gross_exposure_pct"], errors="coerce").dropna()
    if value.empty:
        return 1.0
    pct = float(value.iloc[0])
    if pct <= 0:
        return 0.0
    return min(pct, 100.0) / 100.0


def _first_daily_date_after(daily_index: pd.Index, signal_date: pd.Timestamp):
    future_dates = daily_index[daily_index > signal_date]
    if len(future_dates) == 0:
        return None
    return future_dates[0]


def _process_rebalance(
    current_date: pd.Timestamp,
    target_tickers: set[str],
    exit_tickers: set[str],
    target_details: dict[str, dict],
    rank_map: dict[str, int],
    market_filter_passed: bool,
    cash: float,
    positions: dict[str, Position],
    day_prices: dict[str, float],
    cost_per_side_pct: float,
    max_gross_exposure_pct: float,
    rank_deterioration_exit: dict | None,
    block_new_entries: bool,
    trade_rows: list[dict],
    warnings: list[str],
    reduced_exposure_pct_when_active: float | None = None,
    allow_entries_when_active_top_n: int | None = None,
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
        if ticker in exit_tickers:
            position = positions[ticker]
            current_rank = rank_map.get(ticker)
            if current_rank is not None and rank_deterioration_exit is not None:
                max_rank = int(rank_deterioration_exit.get("max_rank", 25) or 25)
                confirm = int(rank_deterioration_exit.get("confirm_rebalances", 2) or 2)
                if current_rank > max_rank:
                    position.rank_deterioration_count += 1
                else:
                    position.rank_deterioration_count = 0
                if position.rank_deterioration_count >= confirm:
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
                        exit_reason="rank_deterioration_exit",
                        trade_rows=trade_rows,
                    )
                    continue
        if ticker not in valid_target_tickers and ticker not in exit_tickers:
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

    if block_new_entries:
        return cash

    if not market_filter_passed or not valid_target_tickers:
        return cash

    if allow_entries_when_active_top_n is not None and allow_entries_when_active_top_n > 0:
        allowed = {
            ticker for ticker, _rank in sorted(
                ((ticker, int(rank_map.get(ticker, 10**9))) for ticker in valid_target_tickers),
                key=lambda item: (item[1], item[0]),
            )[:allow_entries_when_active_top_n]
        }
        valid_target_tickers = {ticker for ticker in valid_target_tickers if ticker in allowed or ticker in positions}
        if not valid_target_tickers:
            return cash

    if reduced_exposure_pct_when_active is not None:
        max_gross_exposure_pct = min(max_gross_exposure_pct, float(reduced_exposure_pct_when_active) / 100.0)

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


def _get_trailing_activation_gain_pct(strategy_config: dict) -> float | None:
    risk_management = strategy_config.get("risk_management", {}) or {}
    value = risk_management.get("trailing_activation_gain_pct")
    if value is None:
        return None
    value = float(value)
    return value if value > 0 else None


def _get_stop_loss_pct(strategy_config: dict) -> float | None:
    risk_controls = strategy_config.get("risk_controls", {}) or {}
    position_stop = risk_controls.get("position_stop_loss")
    if isinstance(position_stop, dict) and position_stop.get("enabled"):
        value = position_stop.get("stop_loss_pct")
        if value is not None:
            value = abs(float(value))
            return value if value > 0 else None
    risk_management = strategy_config.get("risk_management", {}) or {}
    value = risk_management.get("stop_loss_pct")
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


def _get_profit_lock_steps(strategy_config: dict) -> list[dict] | None:
    risk_management = strategy_config.get("risk_management", {}) or {}
    steps = risk_management.get("profit_lock_steps")
    if not steps:
        return None
    if not isinstance(steps, list):
        return None
    normalized: list[dict] = []
    for step in steps:
        if not isinstance(step, dict):
            continue
        try:
            gain_pct = float(step.get("gain_pct"))
            lock_pct = float(step.get("lock_pct"))
        except (TypeError, ValueError):
            continue
        if gain_pct > 0 and lock_pct >= 0:
            normalized.append({"gain_pct": gain_pct, "lock_pct": lock_pct})
    return normalized or None


def _get_partial_take_profit(strategy_config: dict) -> dict | None:
    risk_management = strategy_config.get("risk_management", {}) or {}
    cfg = risk_management.get("partial_take_profit")
    if not isinstance(cfg, dict) or not cfg.get("enabled"):
        return None
    try:
        gain_pct = float(cfg.get("gain_pct"))
        sell_fraction = float(cfg.get("sell_fraction"))
    except (TypeError, ValueError):
        return None
    if gain_pct <= 0 or not (0 < sell_fraction < 1):
        return None
    return {"gain_pct": gain_pct, "sell_fraction": sell_fraction}


def _get_rank_deterioration_exit(strategy_config: dict) -> dict | None:
    exit_rule = strategy_config.get("exit_rule", {}) or {}
    cfg = exit_rule.get("rank_deterioration_exit")
    if not isinstance(cfg, dict) or not cfg.get("enabled"):
        return None
    try:
        max_rank = int(cfg.get("max_rank"))
        confirm_rebalances = int(cfg.get("confirm_rebalances"))
    except (TypeError, ValueError):
        return None
    if max_rank <= 0 or confirm_rebalances <= 0:
        return None
    return {"max_rank": max_rank, "confirm_rebalances": confirm_rebalances}


def _get_equity_drawdown_guard(strategy_config: dict) -> dict | None:
    risk_management = strategy_config.get("risk_management", {}) or {}
    cfg = risk_management.get("equity_drawdown_guard")
    if not isinstance(cfg, dict) or not cfg.get("enabled"):
        return None
    try:
        stop = float(cfg.get("stop_new_entries_drawdown_pct"))
        resume = float(cfg.get("resume_drawdown_pct"))
    except (TypeError, ValueError):
        return None
    if resume < stop:
        return None
    guard = {"stop_new_entries_drawdown_pct": stop, "resume_drawdown_pct": resume}
    reduced = cfg.get("reduced_exposure_pct_when_active")
    if reduced is not None:
        try:
            reduced_value = float(reduced)
            if reduced_value > 0:
                guard["reduced_exposure_pct_when_active"] = reduced_value
        except (TypeError, ValueError):
            pass
    cooldown = cfg.get("cooldown_rebalances")
    if cooldown is not None:
        try:
            cooldown_value = int(cooldown)
            if cooldown_value > 0:
                guard["cooldown_rebalances"] = cooldown_value
        except (TypeError, ValueError):
            pass
    top_n = cfg.get("allow_entries_when_active_top_n")
    if top_n is not None:
        try:
            top_n_value = int(top_n)
            if top_n_value > 0:
                guard["allow_entries_when_active_top_n"] = top_n_value
        except (TypeError, ValueError):
            pass
    return guard


def _get_portfolio_drawdown_guard(strategy_config: dict) -> dict | None:
    risk_controls = strategy_config.get("risk_controls", {}) or {}
    cfg = risk_controls.get("portfolio_drawdown_guard")
    if not isinstance(cfg, dict) or not cfg.get("enabled"):
        return None
    try:
        reduce_dd = float(cfg.get("reduce_exposure_drawdown_pct"))
        crisis_dd = float(cfg.get("crisis_drawdown_pct", reduce_dd))
    except (TypeError, ValueError):
        return None
    if crisis_dd > reduce_dd:
        return None
    try:
        reduced_multiplier = float(cfg.get("reduced_exposure_multiplier", 0.5))
    except (TypeError, ValueError):
        reduced_multiplier = 0.5
    try:
        crisis_multiplier = float(cfg.get("crisis_exposure_multiplier", 0.0))
    except (TypeError, ValueError):
        crisis_multiplier = 0.0
    reentry_drawdown = cfg.get("reentry_drawdown_pct")
    if reentry_drawdown is not None:
        try:
            reentry_drawdown = float(reentry_drawdown)
        except (TypeError, ValueError):
            reentry_drawdown = None
    mode = str(cfg.get("reentry_mode") or "dd_recovered").lower()
    cooldown_days = cfg.get("cooldown_days")
    if cooldown_days is None:
        match = re.search(r"cooldown_(\d+)", mode)
        cooldown_days = int(match.group(1)) if match else 0
    try:
        cooldown_days = int(cooldown_days or 0)
    except (TypeError, ValueError):
        cooldown_days = 0
    return {
        "reduce_exposure_drawdown_pct": reduce_dd,
        "reduced_exposure_multiplier": max(0.0, min(1.0, reduced_multiplier)),
        "crisis_drawdown_pct": crisis_dd,
        "crisis_exposure_multiplier": max(0.0, min(1.0, crisis_multiplier)),
        "reentry_drawdown_pct": reentry_drawdown,
        "reentry_mode": mode,
        "cooldown_days": max(0, cooldown_days),
    }


def _portfolio_guard_target_exposure_pct(
    portfolio_drawdown_guard: dict | None,
    state: str,
) -> float | None:
    if not portfolio_drawdown_guard or state == "normal":
        return None
    if state == "crisis":
        return float(portfolio_drawdown_guard.get("crisis_exposure_multiplier", 0.0)) * 100.0
    return float(portfolio_drawdown_guard.get("reduced_exposure_multiplier", 1.0)) * 100.0


def _update_portfolio_guard_runtime(
    *,
    runtime: dict,
    guard: dict,
    current_date: pd.Timestamp,
    current_drawdown_pct: float,
    benchmark_row,
) -> list[dict]:
    events: list[dict] = []
    old_state = str(runtime.get("state", "normal"))
    new_state = old_state

    if old_state != "normal" and _portfolio_reentry_allowed(
        guard=guard,
        runtime=runtime,
        current_date=current_date,
        current_drawdown_pct=current_drawdown_pct,
        benchmark_row=benchmark_row,
    ):
        new_state = "normal"
        runtime["state"] = "normal"
        runtime["active_since"] = None
        runtime["last_state_change"] = current_date
        return [
            {
                "date": current_date,
                "event": "guard_reentry",
                "state": "normal",
                "drawdown_pct": float(current_drawdown_pct),
                "reentry_mode": guard.get("reentry_mode"),
            }
        ]

    if current_drawdown_pct <= float(guard["crisis_drawdown_pct"]):
        new_state = "crisis"
    elif old_state != "normal" or current_drawdown_pct <= float(guard["reduce_exposure_drawdown_pct"]):
        new_state = "reduced"

    if new_state != old_state:
        runtime["state"] = new_state
        runtime["last_state_change"] = current_date
        if old_state == "normal":
            runtime["active_since"] = current_date
        event_name = "guard_crisis_on" if new_state == "crisis" else "guard_reduce_on"
        if new_state == "normal":
            event_name = "guard_off"
        events.append(
            {
                "date": current_date,
                "event": event_name,
                "state": new_state,
                "drawdown_pct": float(current_drawdown_pct),
                "target_exposure_pct": _portfolio_guard_target_exposure_pct(guard, new_state),
            }
        )

    return events


def _portfolio_reentry_allowed(
    *,
    guard: dict,
    runtime: dict,
    current_date: pd.Timestamp,
    current_drawdown_pct: float,
    benchmark_row,
) -> bool:
    mode = str(guard.get("reentry_mode") or "dd_recovered").lower()
    if mode in {"never", "permanent", "none_permanent"}:
        return False

    reentry_drawdown = guard.get("reentry_drawdown_pct")
    if reentry_drawdown is not None and current_drawdown_pct < float(reentry_drawdown):
        return False

    cooldown_days = int(guard.get("cooldown_days") or 0)
    active_since = runtime.get("active_since")
    if cooldown_days > 0:
        if active_since is None:
            return False
        elapsed_days = (pd.to_datetime(current_date) - pd.to_datetime(active_since)).days
        if elapsed_days < cooldown_days:
            return False

    if "spy_sma200" in mode and not _spy_above_sma(benchmark_row, 200):
        return False
    if "sma50" in mode and not _spy_above_sma(benchmark_row, 50):
        return False
    if "slope50" in mode and not _spy_sma50_slope_positive(benchmark_row):
        return False

    return True


def _spy_above_sma(benchmark_row, window: int) -> bool:
    if benchmark_row is None:
        return False
    close = _series_float(benchmark_row, "close")
    sma = _series_float(benchmark_row, f"close_sma_{window}")
    if close is None or sma is None:
        return False
    return close > sma


def _spy_sma50_slope_positive(benchmark_row) -> bool:
    if benchmark_row is None:
        return False
    slope = _series_float(benchmark_row, "close_sma_50_slope_5d_pct")
    return slope is not None and slope > 0


def _series_float(row, field: str) -> float | None:
    if row is None or field not in row:
        return None
    value = pd.to_numeric(row[field], errors="coerce")
    if pd.isna(value):
        return None
    return float(value)


def _equity_guard_rebalance_policy(
    *,
    equity_guard_active: bool,
    current_equity_dd_pct: float,
    equity_drawdown_guard: dict | None,
    cooldown_remaining: int,
) -> dict[str, float | int | bool | None]:
    policy = {
        "block_new_entries": False,
        "reduced_exposure_pct_when_active": None,
        "allow_entries_when_active_top_n": None,
    }
    if not equity_guard_active or not equity_drawdown_guard:
        return policy

    reduced = equity_drawdown_guard.get("reduced_exposure_pct_when_active")
    top_n = equity_drawdown_guard.get("allow_entries_when_active_top_n")
    cooldown = int(equity_drawdown_guard.get("cooldown_rebalances") or 0)
    hard_stop = float(equity_drawdown_guard["stop_new_entries_drawdown_pct"]) - 3.0
    hard_breach = current_equity_dd_pct <= hard_stop

    if hard_breach:
        policy["block_new_entries"] = True
        return policy

    if cooldown and cooldown_remaining > 0:
        policy["block_new_entries"] = True
        return policy

    if reduced is None and top_n is None:
        policy["block_new_entries"] = True
        return policy

    policy["reduced_exposure_pct_when_active"] = reduced
    policy["allow_entries_when_active_top_n"] = top_n
    return policy


def _get_max_drawdown_kill_switch(strategy_config: dict) -> dict | None:
    risk_management = strategy_config.get("risk_management", {}) or {}
    cfg = risk_management.get("max_drawdown_kill_switch")
    if not isinstance(cfg, dict) or not cfg.get("enabled"):
        return None
    try:
        stop = float(cfg.get("stop_backtest_drawdown_pct"))
    except (TypeError, ValueError):
        return None
    return {"stop_backtest_drawdown_pct": stop}


def _profit_lock_floor(position: Position, profit_lock_steps: list[dict] | None) -> float | None:
    if not profit_lock_steps:
        return None
    applicable = [step for step in profit_lock_steps if float(position.max_price_since_entry) >= float(position.entry_price) * (1.0 + float(step["gain_pct"]) / 100.0)]
    if not applicable:
        return None
    highest_lock = max(float(step["lock_pct"]) for step in applicable)
    return float(position.entry_price) * (1.0 + highest_lock / 100.0)


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
    signal_prices: dict[str, float] | None,
    strict_next_close: bool,
    trailing_stop_pct: float | None,
    trailing_activation_gain_pct: float | None,
    stop_loss_pct: float | None,
    breakeven_after_gain_pct: float | None,
    breakeven_buffer_pct: float,
    profit_lock_steps: list[dict] | None,
    partial_take_profit: dict | None,
    cost_per_side_pct: float,
    trade_rows: list[dict],
    execution_timing_mode: str | None = None,
    signal_detected_date: pd.Timestamp | None = None,
) -> tuple[float, int]:
    if stop_loss_pct is None and trailing_stop_pct is None and breakeven_after_gain_pct is None and not profit_lock_steps and not partial_take_profit:
        return cash, 0
    delayed_count = 0
    signal_prices = signal_prices or prices

    loss_fraction = stop_loss_pct / 100.0 if stop_loss_pct is not None else None
    stop_fraction = trailing_stop_pct / 100.0 if trailing_stop_pct is not None else None
    trailing_activation = (
        1.0 + (trailing_activation_gain_pct / 100.0)
        if trailing_activation_gain_pct is not None
        else None
    )
    breakeven_trigger = (
        1.0 + (breakeven_after_gain_pct / 100.0)
        if breakeven_after_gain_pct is not None
        else None
    )
    breakeven_floor = 1.0 + (breakeven_buffer_pct / 100.0)
    for ticker in list(positions.keys()):
        signal_price = signal_prices.get(ticker)
        execution_price = prices.get(ticker)
        if signal_price is None or execution_price is None:
            continue
        position = positions[ticker]
        signal_price = float(signal_price)
        price = float(execution_price)
        position.max_price_since_entry = max(float(position.max_price_since_entry), signal_price)
        drawdown_from_peak_pct = ((signal_price / position.max_price_since_entry) - 1.0) * 100.0

        if loss_fraction is not None and signal_price <= position.entry_price * (1.0 - loss_fraction):
            position.stop_exit_peak_price = float(position.max_price_since_entry)
            position.stop_exit_drawdown_from_peak_pct = float(drawdown_from_peak_pct)
            cash = _close_position(
                ticker=ticker,
                exit_date=current_date,
                exit_price=price,
                cash=cash,
                positions=positions,
                cost_per_side_pct=cost_per_side_pct,
                exit_reason="stop_loss",
                trade_rows=trade_rows,
                execution_timing_mode=execution_timing_mode,
                signal_detected_date=signal_detected_date,
            )
            if strict_next_close:
                delayed_count += 1
            continue

        lock_price = _profit_lock_floor(position, profit_lock_steps)
        if lock_price is not None:
            position.profit_lock_floor_price = lock_price
            if signal_price <= lock_price:
                position.stop_exit_peak_price = float(position.max_price_since_entry)
                position.stop_exit_drawdown_from_peak_pct = float(drawdown_from_peak_pct)
                cash = _close_position(
                    ticker=ticker,
                    exit_date=current_date,
                    exit_price=price,
                    cash=cash,
                    positions=positions,
                    cost_per_side_pct=cost_per_side_pct,
                    exit_reason="profit_lock_stop",
                    trade_rows=trade_rows,
                )
                continue

        trailing_is_active = (
            stop_fraction is not None
            and (
                trailing_activation is None
                or position.max_price_since_entry >= position.entry_price * trailing_activation
            )
        )
        if trailing_is_active and signal_price <= position.max_price_since_entry * (1.0 - stop_fraction):
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
            continue

        if (
            breakeven_trigger is not None
            and position.max_price_since_entry >= position.entry_price * breakeven_trigger
            and signal_price <= position.entry_price * breakeven_floor
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

        if partial_take_profit and not position.partial_take_profit_done:
            gain_trigger = float(partial_take_profit.get("gain_pct", 0) or 0)
            sell_fraction = float(partial_take_profit.get("sell_fraction", 0) or 0)
            if gain_trigger > 0 and 0 < sell_fraction < 1 and signal_price >= position.entry_price * (1.0 + gain_trigger / 100.0):
                shares_to_sell = position.shares * sell_fraction
                cash = _sell_position_shares(
                    ticker=ticker,
                    shares_to_sell=shares_to_sell,
                    exit_date=current_date,
                    exit_price=price,
                    cash=cash,
                    positions=positions,
                    cost_per_side_pct=cost_per_side_pct,
                    exit_reason="partial_take_profit",
                    trade_rows=trade_rows,
                )
                remaining = positions.get(ticker)
                if remaining is not None:
                    remaining.partial_take_profit_done = True
                continue
    return cash, delayed_count


def _scale_positions_to_target_gross_exposure(
    *,
    current_date: pd.Timestamp,
    cash: float,
    positions: dict[str, Position],
    prices: dict[str, float],
    cost_per_side_pct: float,
    target_exposure_pct: float,
    exit_reason: str,
    trade_rows: list[dict],
    execution_timing_mode: str | None = None,
    signal_detected_date: pd.Timestamp | None = None,
) -> tuple[float, int]:
    if not positions:
        return cash, 0
    target_exposure_pct = max(0.0, min(100.0, float(target_exposure_pct)))
    gross_value = calculate_positions_value(positions, prices)
    if gross_value <= 0:
        return cash, 0
    equity = cash + gross_value
    target_value = max(0.0, equity * (target_exposure_pct / 100.0))
    if gross_value <= target_value * 1.000001:
        return cash, 0
    sell_fraction = 1.0 - (target_value / gross_value if gross_value > 0 else 0.0)
    sell_fraction = max(0.0, min(1.0, sell_fraction))
    scaled = 0
    for ticker in list(positions.keys()):
        position = positions.get(ticker)
        price = prices.get(ticker)
        if position is None or price is None:
            continue
        shares_to_sell = float(position.shares) * sell_fraction
        if shares_to_sell <= 1e-10:
            continue
        cash = _sell_position_shares(
            ticker=ticker,
            shares_to_sell=shares_to_sell,
            exit_date=current_date,
            exit_price=float(price),
            cash=cash,
            positions=positions,
            cost_per_side_pct=cost_per_side_pct,
            exit_reason=exit_reason,
            trade_rows=trade_rows,
            execution_timing_mode=execution_timing_mode,
            signal_detected_date=signal_detected_date,
        )
        scaled += 1
    return cash, scaled


def _close_position(
    ticker: str,
    exit_date: pd.Timestamp,
    exit_price: float,
    cash: float,
    positions: dict[str, Position],
    cost_per_side_pct: float,
    exit_reason: str,
    trade_rows: list[dict],
    execution_timing_mode: str | None = None,
    signal_detected_date: pd.Timestamp | None = None,
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
        execution_timing_mode=execution_timing_mode,
        signal_detected_date=signal_detected_date,
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
    execution_timing_mode: str | None = None,
    signal_detected_date: pd.Timestamp | None = None,
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
            "execution_timing_mode": execution_timing_mode,
            "signal_detected_date": signal_detected_date,
            "delayed_execution_days": (
                int((pd.to_datetime(exit_date) - pd.to_datetime(signal_detected_date)).days)
                if signal_detected_date is not None else None
            ),
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
