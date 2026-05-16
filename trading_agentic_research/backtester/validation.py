"""Validation helpers for backtest run artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd


REQUIRED_RUN_FILES = [
    "equity_curve.csv",
    "trades.csv",
    "metrics.json",
    "spy_comparison_monthly.csv",
    "spy_comparison_yearly.csv",
    "spy_comparison_summary.json",
]

CRITICAL_WARNING_KEYWORDS = (
    "critical",
    "lookahead",
    "data leakage",
    "missing comparison",
    "missing costs",
    "costs not applied",
)


def audit_run_folder(run_dir: str | Path, min_trades: int = 10) -> dict:
    """Audit one run folder and return the audit.json payload."""
    path = Path(run_dir)
    blocking_issues: list[str] = []
    reasons: list[str] = []
    warnings: list[str] = []

    missing_files = [name for name in REQUIRED_RUN_FILES if not (path / name).exists()]
    if missing_files:
        blocking_issues.append(f"Missing required files: {missing_files}")

    metrics = _read_json(path / "metrics.json") if (path / "metrics.json").exists() else {}
    comparison_summary = (
        _read_json(path / "spy_comparison_summary.json")
        if (path / "spy_comparison_summary.json").exists()
        else {}
    )
    monthly_df = _read_csv(path / "spy_comparison_monthly.csv")
    yearly_df = _read_csv(path / "spy_comparison_yearly.csv")
    trades_df = _read_csv(path / "trades.csv")

    warnings.extend(_extract_warnings(metrics))

    spy_fields = [
        "strategy_cagr_pct",
        "spy_cagr_pct",
        "excess_cagr_pct",
        "months_beating_spy",
        "months_losing_to_spy",
        "years_beating_spy",
        "years_losing_to_spy",
    ]
    missing_spy_fields = [field for field in spy_fields if field not in comparison_summary]
    if missing_spy_fields:
        blocking_issues.append(f"Missing SPY comparison fields: {missing_spy_fields}")

    costs_applied = _costs_are_present(metrics, trades_df)
    if not costs_applied:
        blocking_issues.append("Missing costs evidence: metrics costs metadata or net trade returns not found.")

    critical_warnings = _critical_warnings(warnings)
    if critical_warnings:
        blocking_issues.append(f"Critical warnings found: {critical_warnings}")

    strategy_cagr = _as_float(comparison_summary.get("strategy_cagr_pct"))
    spy_cagr = _as_float(comparison_summary.get("spy_cagr_pct"))
    years_beating = _as_int(comparison_summary.get("years_beating_spy"))
    years_losing = _as_int(comparison_summary.get("years_losing_to_spy"))
    number_of_trades = len(trades_df) if trades_df is not None else 0

    strategy_dd = _as_float(metrics.get("strategy", {}).get("max_drawdown_pct"))
    spy_dd = _as_float(metrics.get("spy", {}).get("max_drawdown_pct"))
    drawdown_improved = _drawdown_improved(strategy_dd, spy_dd)
    drawdown_exaggerated_worse = _drawdown_exaggerated_worse(strategy_dd, spy_dd)

    if strategy_cagr is not None and spy_cagr is not None:
        if strategy_cagr < spy_cagr and not drawdown_improved:
            reasons.append("Strategy CAGR is below SPY CAGR and drawdown did not improve.")
        elif strategy_cagr < spy_cagr and drawdown_improved:
            reasons.append("Strategy underperforms SPY CAGR but improves drawdown; follow-up may be useful.")
        elif strategy_cagr > spy_cagr:
            reasons.append("Strategy CAGR beats SPY CAGR.")

    if years_beating is not None and years_losing is not None:
        if years_beating <= years_losing:
            reasons.append("Strategy does not beat SPY in more years than it loses.")
        else:
            reasons.append("Strategy beats SPY in more years than it loses.")

    if number_of_trades < min_trades:
        reasons.append(f"Insufficient trades: {number_of_trades} < {min_trades}.")

    decision = _decide(
        blocking_issues=blocking_issues,
        strategy_cagr=strategy_cagr,
        spy_cagr=spy_cagr,
        years_beating=years_beating,
        years_losing=years_losing,
        number_of_trades=number_of_trades,
        min_trades=min_trades,
        drawdown_improved=drawdown_improved,
        drawdown_exaggerated_worse=drawdown_exaggerated_worse,
    )

    recommendation = _recommendation_for(decision)

    return {
        "audit_status": "completed" if not missing_files else "completed_with_missing_files",
        "decision": decision,
        "reasons": reasons,
        "blocking_issues": blocking_issues,
        "warnings": warnings,
        "recommendation": recommendation,
        "can_move_parent": decision in {"accepted_for_followup", "promoted_candidate"},
        "can_promote_baseline": False,
    }


def _decide(
    *,
    blocking_issues: list[str],
    strategy_cagr: float | None,
    spy_cagr: float | None,
    years_beating: int | None,
    years_losing: int | None,
    number_of_trades: int,
    min_trades: int,
    drawdown_improved: bool,
    drawdown_exaggerated_worse: bool,
) -> str:
    if blocking_issues:
        return "rejected"
    if strategy_cagr is None or spy_cagr is None:
        return "rejected"
    if years_beating is None or years_losing is None:
        return "rejected"
    if number_of_trades < min_trades:
        return "rejected"
    if strategy_cagr < spy_cagr and not drawdown_improved:
        return "rejected"
    if years_beating <= years_losing:
        return "rejected"

    if strategy_cagr > spy_cagr and years_beating > years_losing and not drawdown_exaggerated_worse:
        return "promoted_candidate"

    return "accepted_for_followup"


def _recommendation_for(decision: str) -> str:
    if decision == "promoted_candidate":
        return "Candidate can move forward for manual review; baseline promotion remains blocked."
    if decision == "accepted_for_followup":
        return "Keep researching; useful signal but not ready for baseline promotion."
    return "Reject or fix blocking issues before further research."


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _read_csv(path: Path) -> pd.DataFrame | None:
    if not path.exists():
        return None
    return pd.read_csv(path)


def _extract_warnings(metrics: dict) -> list[str]:
    diagnostics = metrics.get("diagnostics", {}) if isinstance(metrics, dict) else {}
    raw = diagnostics.get("warnings", [])
    if not isinstance(raw, list):
        return [str(raw)]
    return [str(item) for item in raw]


def _costs_are_present(metrics: dict, trades_df: pd.DataFrame | None) -> bool:
    costs = metrics.get("costs", {}) if isinstance(metrics, dict) else {}
    if costs.get("applied") is True and _as_float(costs.get("cost_per_side_pct"), default=0.0) > 0:
        return True

    if trades_df is None or trades_df.empty:
        return False
    required = {"gross_return_pct", "net_return_pct"}
    if not required.issubset(trades_df.columns):
        return False
    return bool((trades_df["gross_return_pct"] != trades_df["net_return_pct"]).any())


def _critical_warnings(warnings: list[str]) -> list[str]:
    found = []
    for warning in warnings:
        lower = warning.lower()
        if any(keyword in lower for keyword in CRITICAL_WARNING_KEYWORDS):
            found.append(warning)
    return found


def _drawdown_improved(strategy_dd: float | None, spy_dd: float | None) -> bool:
    if strategy_dd is None or spy_dd is None:
        return False
    return strategy_dd >= spy_dd


def _drawdown_exaggerated_worse(strategy_dd: float | None, spy_dd: float | None) -> bool:
    if strategy_dd is None or spy_dd is None:
        return False
    return strategy_dd < spy_dd * 1.5 if spy_dd < 0 else False


def _as_float(value, default=None) -> float | None:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value, default=None) -> int | None:
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
