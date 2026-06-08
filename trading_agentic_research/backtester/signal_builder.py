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
    - market_filter.soft_weak_regime_top_n: reduce breadth instead of
      blocking all entries when SPY regime is weak
    - ranking.secondary_penalty_field / secondary_penalty_weight: soft
      one-field penalty applied to the primary ranking score
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
                "target_gross_exposure_pct",
                "entry_blocked_by_crisis",
                "spy_filter_policy",
                "spy_filter_warmup_days",
                "spy_filter_fallback_used",
                "spy_filter_fallback_outside_warmup",
                "spy_filter_missing_or_nan",
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

    decision_frequency = str(strategy_config.get("decision_frequency", "monthly")).lower()
    if decision_frequency == "weekly":
        decision_dates = df["date"].drop_duplicates().sort_values().tolist()
    elif decision_frequency == "monthly":
        # Legacy behavior: last weekly snapshot available in each month.
        month_key = df["date"].dt.to_period("M")
        decision_dates = df.groupby(month_key)["date"].max().sort_values().tolist()
    else:
        raise ValueError(
            f"Unsupported decision_frequency={decision_frequency!r}; expected 'monthly' or 'weekly'."
        )

    output_frames = []
    for signal_index, signal_date in enumerate(decision_dates):
        snapshot = df[df["date"] == signal_date].copy()
        market_eval = _evaluate_market_filter(snapshot, strategy_config, benchmark_ticker, signal_date=signal_date, first_signal_date=decision_dates[0], signal_index=signal_index)
        market_filter_passed = bool(market_eval["passed"])
        entry_blocked_by_crisis = _entry_blocked_by_crisis(snapshot, strategy_config, benchmark_ticker)
        effective_top_n, action_market_filter_passed = _effective_top_n_and_filter(
            top_n=top_n,
            market_filter_passed=market_filter_passed,
            strategy_config=strategy_config,
        )
        target_gross_exposure_pct = _dynamic_target_gross_exposure_pct(snapshot, strategy_config, benchmark_ticker)

        operable = snapshot[snapshot["ticker"] != benchmark_ticker].copy()
        operable = _apply_risk_filters(operable, strategy_config)

        # Minimal hard requirement: ranking value must exist for selection/ranking.
        operable = operable.dropna(subset=[ranking_column])
        if operable.empty:
            continue

        ranking_values = _ranking_values(operable, ranking_column, strategy_config)
        operable["rank"] = (
            ranking_values
            .rank(method="first", ascending=ranking_ascending)
            .astype(int)
        )
        operable = operable.sort_values("rank", kind="mergesort")

        operable["signal_date"] = signal_date
        operable["ranking_value"] = ranking_values
        operable["selected_top_n"] = operable["rank"] <= effective_top_n
        operable["in_exit_universe"] = operable["rank"] <= exit_rank_threshold
        operable["market_filter_passed"] = bool(action_market_filter_passed)
        operable["target_gross_exposure_pct"] = float(target_gross_exposure_pct)
        operable["entry_blocked_by_crisis"] = bool(entry_blocked_by_crisis)
        operable["spy_filter_policy"] = str(market_eval["policy"])
        operable["spy_filter_warmup_days"] = int(market_eval["warmup_days"])
        operable["spy_filter_fallback_used"] = bool(market_eval["fallback_used"])
        operable["spy_filter_fallback_outside_warmup"] = bool(market_eval["fallback_outside_warmup"])
        operable["spy_filter_missing_or_nan"] = bool(market_eval["missing_or_nan"])
        if entry_blocked_by_crisis:
            operable["selected_top_n"] = False
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
                    "target_gross_exposure_pct",
                    "entry_blocked_by_crisis",
                    "spy_filter_policy",
                    "spy_filter_warmup_days",
                    "spy_filter_fallback_used",
                    "spy_filter_fallback_outside_warmup",
                    "spy_filter_missing_or_nan",
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
                "target_gross_exposure_pct",
                "entry_blocked_by_crisis",
                "spy_filter_policy",
                "spy_filter_warmup_days",
                "spy_filter_fallback_used",
                "spy_filter_fallback_outside_warmup",
                "spy_filter_missing_or_nan",
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


def _ranking_values(operable: pd.DataFrame, ranking_column: str, strategy_config: dict) -> pd.Series:
    values = pd.to_numeric(operable[ranking_column], errors="coerce")
    ranking_cfg = strategy_config.get("ranking", {}) or {}
    penalty_field = str(ranking_cfg.get("secondary_penalty_field") or "")
    if not penalty_field or penalty_field not in operable.columns:
        return values
    penalty = pd.to_numeric(operable[penalty_field], errors="coerce").fillna(0.0)
    try:
        weight = float(ranking_cfg.get("secondary_penalty_weight", 0.0) or 0.0)
    except (TypeError, ValueError):
        weight = 0.0
    if weight <= 0:
        return values
    if _get_ranking_ascending(strategy_config):
        return values + (weight * penalty)
    return values - (weight * penalty)


def _effective_top_n_and_filter(*, top_n: int, market_filter_passed: bool, strategy_config: dict) -> tuple[int, bool]:
    """Return breadth/filter behavior for hard vs soft market regime.

    Normal strategies remain unchanged. DD_FIRST soft regime candidates can set
    market_filter.soft_weak_regime_top_n to keep trading a smaller basket when
    SPY trend is weak instead of forcing zero new entries.
    """
    if market_filter_passed:
        return top_n, True
    market_filter_cfg = strategy_config.get("market_filter", {}) or {}
    if "soft_weak_regime_top_n" not in market_filter_cfg:
        return top_n, False
    try:
        weak_top_n = int(market_filter_cfg.get("soft_weak_regime_top_n"))
    except (TypeError, ValueError):
        return top_n, False
    weak_top_n = max(0, min(top_n, weak_top_n))
    return weak_top_n, weak_top_n > 0


def _dynamic_target_gross_exposure_pct(snapshot: pd.DataFrame, strategy_config: dict, benchmark_ticker: str) -> float:
    risk_management = strategy_config.get("risk_management", {}) or {}
    cfg = risk_management.get("dynamic_regime_exposure_pct")
    if not isinstance(cfg, dict):
        return float(risk_management.get("max_gross_exposure_pct", 100) or 100)

    row = _benchmark_context_row(snapshot, benchmark_ticker)
    if row is None:
        return float(cfg.get("weak", cfg.get("neutral", risk_management.get("max_gross_exposure_pct", 60))) or 60)
    close_vs_52 = _row_float(row, "spy_close_vs_sma52w_pct", "close_vs_sma52w_pct")
    close_vs_20 = _row_float(row, "spy_close_vs_sma20w_pct", "close_vs_sma20w_pct")
    dd_26 = _row_float(row, "spy_drawdown_from_high_26w_pct", "drawdown_from_high_26w_pct")

    if dd_26 <= -20 or close_vs_52 <= -20:
        regime = "crisis"
    elif close_vs_52 > 0 and close_vs_20 > 0:
        regime = "strong"
    elif close_vs_52 > 0 or close_vs_20 > 0:
        regime = "neutral"
    else:
        regime = "weak"
    return float(cfg.get(regime, cfg.get("neutral", risk_management.get("max_gross_exposure_pct", 60))) or 60)


def _entry_blocked_by_crisis(snapshot: pd.DataFrame, strategy_config: dict, benchmark_ticker: str) -> bool:
    risk_management = strategy_config.get("risk_management", {}) or {}
    cfg = risk_management.get("no_new_entries_in_crisis")
    if not isinstance(cfg, dict) or not cfg.get("enabled"):
        return False
    row = _benchmark_context_row(snapshot, benchmark_ticker)
    if row is None:
        return False
    threshold = float(cfg.get("crisis_threshold_pct", -10) or -10)
    priority = cfg.get("regime_field_priority") or [
        "spy_close_vs_sma50_pct",
        "close_vs_sma20w_pct",
        "close_vs_sma52w_pct",
    ]
    for field in priority:
        value = _row_float(row, str(field), _spy_prefixed_field(str(field)))
        if value != 0.0 or str(field) in row or _spy_prefixed_field(str(field)) in row:
            return value <= threshold
    return False


def _benchmark_context_row(snapshot: pd.DataFrame, benchmark_ticker: str) -> pd.Series | None:
    benchmark_rows = snapshot[snapshot["ticker"] == benchmark_ticker]
    if not benchmark_rows.empty:
        return benchmark_rows.iloc[0]
    spy_columns = [c for c in snapshot.columns if str(c).startswith("spy_")]
    if spy_columns and not snapshot.empty:
        return snapshot.iloc[0]
    return None


def _spy_prefixed_field(field: str) -> str:
    return field if field.startswith("spy_") else f"spy_{field}"


def _row_float(row: pd.Series, *fields: str) -> float:
    for field in fields:
        if field not in row:
            continue
        value = pd.to_numeric(row[field], errors="coerce")
        if not pd.isna(value):
            return float(value)
    return 0.0


def _evaluate_market_filter(
    snapshot: pd.DataFrame,
    strategy_config: dict,
    benchmark_ticker: str,
    *,
    signal_date=None,
    first_signal_date=None,
    signal_index: int = 0,
) -> dict[str, Any]:
    # AUTONOMY_DIRECT_PATCH_SPY_MARKET_FILTER
    market_filter_cfg = strategy_config.get("market_filter", {})
    require_positive_trend = bool(market_filter_cfg.get("require_positive_trend", True))
    fallback_if_missing = bool(market_filter_cfg.get("fallback_allow_if_missing_spy_metric", True))
    policy_cfg = strategy_config.get("spy_filter_missing_policy", {}) or {}
    policy = str(policy_cfg.get("mode", "current") or "current")
    if policy not in {"current", "allow_warmup_only", "block_on_nan"}:
        policy = "current"
    warmup_days = int(policy_cfg.get("warmup_days", 252) or 252)

    def within_warmup() -> bool:
        if signal_date is not None and first_signal_date is not None:
            try:
                return (pd.to_datetime(signal_date) - pd.to_datetime(first_signal_date)).days < warmup_days
            except Exception:
                pass
        return int(signal_index) < warmup_days

    def result(passed: bool, *, fallback_used=False, missing_or_nan=False) -> dict[str, Any]:
        outside = bool(fallback_used and not within_warmup())
        return {
            "passed": bool(passed),
            "policy": policy,
            "warmup_days": int(warmup_days),
            "fallback_used": bool(fallback_used),
            "fallback_outside_warmup": outside,
            "missing_or_nan": bool(missing_or_nan),
        }

    if not require_positive_trend:
        return result(True)

    def fallback_decision() -> bool:
        if policy == "current":
            return fallback_if_missing
        if policy == "allow_warmup_only":
            return bool(within_warmup() and fallback_if_missing)
        if policy == "block_on_nan":
            return False
        return fallback_if_missing

    row = _benchmark_context_row(snapshot, benchmark_ticker)
    if row is None:
        decision = fallback_decision()
        warnings.warn(
            f"critical: SPY market filter could not find {benchmark_ticker} row on signal date; using fallback={decision}.",
            UserWarning,
        )
        return result(decision, fallback_used=True, missing_or_nan=True)

    metric_candidates = [
        "spy_close_vs_sma50_pct",
        "close_vs_sma50_pct",
        "close_vs_sma52w_pct",
    ]

    for col in metric_candidates:
        if col not in row:
            continue
        value = pd.to_numeric(row[col], errors="coerce")
        if not pd.isna(value):
            return result(bool(value > 0))

    decision = fallback_decision()
    warnings.warn(
        f"critical: SPY market filter metrics unavailable/NaN (tried={metric_candidates}); using fallback={decision}.",
        UserWarning,
    )
    return result(decision, fallback_used=True, missing_or_nan=True)


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
    if bool(row.get("entry_blocked_by_crisis", False)):
        return "blocked_by_crisis_guard"
    if not bool(row["market_filter_passed"]):
        return "blocked_by_market_filter"
    if bool(row["selected_top_n"]):
        return "enter_or_hold"
    if bool(row["in_exit_universe"]):
        return "hold_if_already_in_position"
    return "exit_candidate"
