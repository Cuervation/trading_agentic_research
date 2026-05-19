"""Signal construction utilities."""

from __future__ import annotations

import operator
import warnings
from typing import Any

import pandas as pd


_CONDITION_OPERATORS = {
    ">": operator.gt,
    ">=": operator.ge,
    "<": operator.lt,
    "<=": operator.le,
    "==": operator.eq,
    "=": operator.eq,
    "!=": operator.ne,
}


def build_momentum_trend_signals(weekly_df, strategy_config) -> pd.DataFrame:
    """Build monthly decision signals from weekly feature-store snapshots.

    The function uses only data available on each signal date.
    Supported real strategy knobs:
    - ranking.field
    - ranking.order: desc (default) or asc
    - entry_rule.top_n
    - exit_rule.rank_threshold
    - market_filter.require_positive_trend
    - market_filter.fallback_allow_if_missing_spy_metric
    - risk_filters.require_non_null_fields
    - risk_filters.conditions: [{field, operator, value, enabled_if_field_exists}]
    """
    if weekly_df is None or len(weekly_df) == 0:
        return pd.DataFrame(
            columns=[
                "signal_date",
                "ticker",
                "rank",
                "ranking_value",
                "selected_top_n",
                "in_exit_universe",
                "market_filter_passed",
                "action_candidate",
            ]
        )

    ranking_column = _get_ranking_column(strategy_config)
    ranking_ascending = _get_ranking_ascending(strategy_config)
    benchmark_ticker = str(strategy_config.get("benchmark_ticker", "SPY"))
    top_n = int(strategy_config.get("entry_rule", {}).get("top_n", 15))
    exit_rank_threshold = int(
        strategy_config.get("exit_rule", {}).get("rank_threshold", 30)
    )

    df = weekly_df.copy()
    if "date" not in df.columns or "ticker" not in df.columns:
        raise ValueError("weekly_df must contain 'date' and 'ticker'")
    if ranking_column not in df.columns:
        raise ValueError(f"weekly_df must contain ranking column: {ranking_column}")

    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"]).sort_values(["date", "ticker"], kind="mergesort")

    # Decision date: last weekly date available each month.
    month_key = df["date"].dt.to_period("M")
    decision_dates = df.groupby(month_key)["date"].max().sort_values().tolist()

    output_frames = []
    for signal_date in decision_dates:
        snapshot = df[df["date"] == signal_date].copy()
        market_filter_passed = _evaluate_market_filter(snapshot, strategy_config, benchmark_ticker)

        operable = snapshot[snapshot["ticker"] != benchmark_ticker].copy()
        operable = _apply_risk_filters(operable, strategy_config)

        # Minimal hard requirement: ranking value must exist for selection/ranking.
        operable = operable.dropna(subset=[ranking_column])
        if operable.empty:
            continue

        operable["rank"] = (
            operable[ranking_column]
            .astype(float)
            .rank(method="first", ascending=ranking_ascending)
            .astype(int)
        )
        operable = operable.sort_values("rank", kind="mergesort")

        operable["signal_date"] = signal_date
        operable["ranking_value"] = operable[ranking_column].astype(float)
        operable["selected_top_n"] = operable["rank"] <= top_n
        operable["in_exit_universe"] = operable["rank"] <= exit_rank_threshold
        operable["market_filter_passed"] = bool(market_filter_passed)
        operable["action_candidate"] = operable.apply(_candidate_action, axis=1)

        output_frames.append(
            operable[
                [
                    "signal_date",
                    "ticker",
                    "rank",
                    "ranking_value",
                    "selected_top_n",
                    "in_exit_universe",
                    "market_filter_passed",
                    "action_candidate",
                ]
            ]
        )

    if not output_frames:
        return pd.DataFrame(
            columns=[
                "signal_date",
                "ticker",
                "rank",
                "ranking_value",
                "selected_top_n",
                "in_exit_universe",
                "market_filter_passed",
                "action_candidate",
            ]
        )

    return pd.concat(output_frames, ignore_index=True)


def _get_ranking_column(strategy_config: dict) -> str:
    if "ranking_column" in strategy_config:
        return str(strategy_config["ranking_column"])
    ranking = strategy_config.get("ranking", {})
    return str(ranking.get("field", "ret_52w_pct"))


def _get_ranking_ascending(strategy_config: dict) -> bool:
    ranking = strategy_config.get("ranking", {})
    order = str(ranking.get("order", "desc") or "desc").lower()
    if order not in {"asc", "ascending", "desc", "descending"}:
        warnings.warn(f"Unsupported ranking.order={order!r}; using desc.", UserWarning)
        order = "desc"
    return order in {"asc", "ascending"}


def _evaluate_market_filter(snapshot: pd.DataFrame, strategy_config: dict, benchmark_ticker: str) -> bool:
    # AUTONOMY_DIRECT_PATCH_SPY_MARKET_FILTER
    market_filter_cfg = strategy_config.get("market_filter", {})
    require_positive_trend = bool(market_filter_cfg.get("require_positive_trend", True))
    fallback_if_missing = bool(
        market_filter_cfg.get("fallback_allow_if_missing_spy_metric", True)
    )

    if not require_positive_trend:
        return True

    spy_rows = snapshot[snapshot["ticker"] == benchmark_ticker]
    if spy_rows.empty:
        warnings.warn(
            f"critical: SPY market filter could not find {benchmark_ticker} row on signal date; using fallback={fallback_if_missing}.",
            UserWarning,
        )
        return fallback_if_missing

    row = spy_rows.iloc[0]
    metric_candidates = [
        "spy_close_vs_sma50_pct",
        "close_vs_sma50_pct",
        "close_vs_sma52w_pct",
    ]

    for col in metric_candidates:
        if col not in spy_rows.columns:
            continue
        value = pd.to_numeric(row[col], errors="coerce")
        if not pd.isna(value):
            return bool(value > 0)

    warnings.warn(
        f"critical: SPY market filter metrics unavailable/NaN (tried={metric_candidates}); using fallback={fallback_if_missing}.",
        UserWarning,
    )
    return fallback_if_missing


def _apply_risk_filters(operable: pd.DataFrame, strategy_config: dict[str, Any]) -> pd.DataFrame:
    """Apply row-level risk/confirmation filters before ranking.

    This makes generated hypotheses like ranking + trend confirmation real rather
    than cosmetic config differences. Missing optional fields are skipped only
    when a condition has enabled_if_field_exists=true.
    """
    cfg = strategy_config.get("risk_filters", {}) or {}
    if operable.empty or not isinstance(cfg, dict):
        return operable

    out = operable.copy()

    required = [str(x) for x in (cfg.get("require_non_null_fields") or []) if x]
    existing_required = [field for field in required if field in out.columns]
    missing_required = [field for field in required if field not in out.columns]
    if missing_required:
        warnings.warn(
            f"Risk filter required fields missing and ignored: {missing_required}",
            UserWarning,
        )
    if existing_required:
        out = out.dropna(subset=existing_required)

    for cond in cfg.get("conditions", []) or []:
        if not isinstance(cond, dict):
            continue
        field = str(cond.get("field") or "")
        op_name = str(cond.get("operator") or ">")
        value = cond.get("value")
        enabled_if_field_exists = bool(cond.get("enabled_if_field_exists", False))
        if not field:
            continue
        if field not in out.columns:
            if enabled_if_field_exists:
                continue
            warnings.warn(f"Risk filter field missing: {field}; no rows pass this condition.", UserWarning)
            return out.iloc[0:0]
        op = _CONDITION_OPERATORS.get(op_name)
        if op is None:
            warnings.warn(f"Unsupported risk filter operator={op_name!r}; condition skipped.", UserWarning)
            continue
        series = pd.to_numeric(out[field], errors="coerce")
        try:
            numeric_value = float(value)
        except (TypeError, ValueError):
            warnings.warn(f"Invalid risk filter value for {field}: {value!r}; condition skipped.", UserWarning)
            continue
        mask = op(series, numeric_value).fillna(False)
        out = out[mask].copy()
        if out.empty:
            break

    return out


def _candidate_action(row: pd.Series) -> str:
    if not bool(row["market_filter_passed"]):
        return "blocked_by_market_filter"
    if bool(row["selected_top_n"]):
        return "enter_or_hold"
    if bool(row["in_exit_universe"]):
        return "hold_if_already_in_position"
    return "exit_candidate"
