"""Validation helpers for backtest run artifacts."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pandas as pd

from scripts.governance import artifact_hashes, artifacts_are_duplicate


REQUIRED_RUN_FILES = [
    "equity_curve.csv",
    "trades.csv",
    "metrics.json",
    "spy_comparison_monthly.csv",
    "spy_comparison_yearly.csv",
    "spy_comparison_summary.json",
    "run_manifest.json",
]

CRITICAL_WARNING_KEYWORDS = (
    "critical",
    "lookahead",
    "data leakage",
    "missing comparison",
    "missing costs",
    "costs not applied",
)


def audit_run_folder(run_dir: str | Path, min_trades: int = 10, parent_run_dir: str | Path | None = None) -> dict:
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

    artifact_hash_payload = build_artifact_hash_payload(path, Path(parent_run_dir) if parent_run_dir is not None else None)
    duplicate_artifact = bool(artifact_hash_payload.get("duplicate_artifact"))
    if duplicate_artifact:
        reasons.append(f"Duplicate artifact/no-effect detected against {artifact_hash_payload.get('duplicate_against')}.")

    parent_comparison = None
    parent_pass = None
    parent_strong_fail = False
    parent_metric_no_effect = False
    if parent_run_dir is not None:
        parent_comparison = build_parent_comparison(path, Path(parent_run_dir))
        if not parent_comparison["parent_available"]:
            blocking_issues.append(f"Parent comparison unavailable: {parent_comparison['blocking_issues']}")
        else:
            parent_metric_no_effect = _parent_comparison_no_effect(parent_comparison)
            parent_pass = _parent_comparison_passes(parent_comparison)
            parent_strong_fail = _parent_comparison_strong_fail(parent_comparison)
            if parent_metric_no_effect:
                reasons.append("Candidate has metric_no_effect versus current parent.")
            elif parent_strong_fail:
                reasons.append("Candidate underperforms parent CAGR and worsens drawdown.")
            elif parent_pass:
                reasons.append("Candidate improves enough versus current parent for follow-up review.")
            else:
                reasons.append("Candidate does not show enough improvement versus current parent.")

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
        parent_pass=parent_pass,
        parent_strong_fail=parent_strong_fail,
        parent_metric_no_effect=parent_metric_no_effect,
        duplicate_artifact=duplicate_artifact,
    )

    recommendation = _recommendation_for(decision)
    can_move_parent = decision in {"accepted_for_followup", "promoted_candidate"} and parent_pass is not False and not parent_metric_no_effect and not duplicate_artifact

    payload = {
        "audit_status": "completed" if not missing_files else "completed_with_missing_files",
        "decision": decision,
        "reasons": reasons,
        "blocking_issues": blocking_issues,
        "warnings": warnings,
        "recommendation": recommendation,
        "can_move_parent": can_move_parent,
        "can_promote_baseline": False,
        "flags": _audit_flags(duplicate_artifact=duplicate_artifact, parent_metric_no_effect=parent_metric_no_effect),
        "artifact_hashes": artifact_hash_payload,
    }
    if parent_comparison is not None:
        payload["parent_comparison"] = parent_comparison
    return payload


def audit_run_folder_dd_first(run_dir: str | Path, min_trades: int = 50, parent_run_dir: str | Path | None = None) -> dict:
    """Audit one run with drawdown-first governance.

    This intentionally does not share the normal promotion semantics: DD_FIRST
    may mark a candidate for follow-up, but it never moves parent/baseline.
    """
    from backtester.dd_first import evaluate_dd_first_run

    return evaluate_dd_first_run(run_dir, min_trades=min_trades, parent_run_dir=parent_run_dir)


def audit_run_folder_dd20_spy_beater(run_dir: str | Path, min_trades: int = 3000, parent_run_dir: str | Path | None = None) -> dict:
    """Audit one run with the DD20 + SPY-beater hard constraint."""
    from backtester.dd20_spy_beater import evaluate_dd20_spy_beater_run

    return evaluate_dd20_spy_beater_run(run_dir, min_trades=min_trades, parent_run_dir=parent_run_dir)


def build_parent_comparison(run_dir: str | Path, parent_run_dir: str | Path) -> dict:
    """Compare a candidate run against the current parent run."""
    candidate_path = Path(run_dir)
    parent_path = Path(parent_run_dir)
    blocking_issues: list[str] = []

    if not parent_path.exists() or not parent_path.is_dir():
        return {"parent_available": False, "blocking_issues": [f"Parent folder not found: {parent_path}"]}

    for name in ["metrics.json", "equity_curve.csv", "trades.csv"]:
        if not (parent_path / name).exists():
            blocking_issues.append(f"Missing parent file: {name}")
        if not (candidate_path / name).exists():
            blocking_issues.append(f"Missing candidate file: {name}")
    if blocking_issues:
        return {"parent_available": False, "blocking_issues": blocking_issues}

    candidate_metrics = _read_json(candidate_path / "metrics.json")
    parent_metrics = _read_json(parent_path / "metrics.json")
    candidate_equity = _read_csv(candidate_path / "equity_curve.csv")
    parent_equity = _read_csv(parent_path / "equity_curve.csv")
    candidate_trades = _read_csv(candidate_path / "trades.csv")
    parent_trades = _read_csv(parent_path / "trades.csv")

    period_counts = _parent_period_win_counts(candidate_equity, parent_equity)
    strategy_cagr = _as_float(candidate_metrics.get("strategy", {}).get("cagr_pct"), 0.0)
    parent_cagr = _as_float(parent_metrics.get("strategy", {}).get("cagr_pct"), 0.0)
    strategy_dd = _as_float(candidate_metrics.get("strategy", {}).get("max_drawdown_pct"), 0.0)
    parent_dd = _as_float(parent_metrics.get("strategy", {}).get("max_drawdown_pct"), 0.0)

    return {
        "parent_available": True,
        "blocking_issues": [],
        "parent_run_id": parent_path.name,
        "strategy_cagr_pct": strategy_cagr,
        "parent_cagr_pct": parent_cagr,
        "excess_cagr_vs_parent_pct": round(strategy_cagr - parent_cagr, 6),
        "strategy_max_drawdown_pct": strategy_dd,
        "parent_max_drawdown_pct": parent_dd,
        "drawdown_delta_vs_parent_pct": round(strategy_dd - parent_dd, 6),
        "trade_count_delta": (len(candidate_trades) if candidate_trades is not None else 0) - (len(parent_trades) if parent_trades is not None else 0),
        **period_counts,
    }


def _parent_period_win_counts(candidate_equity: pd.DataFrame | None, parent_equity: pd.DataFrame | None) -> dict:
    if candidate_equity is None or parent_equity is None:
        return _empty_parent_period_counts()
    required = {"date", "equity"}
    if not required.issubset(candidate_equity.columns) or not required.issubset(parent_equity.columns):
        return _empty_parent_period_counts()

    candidate = candidate_equity[["date", "equity"]].copy()
    parent = parent_equity[["date", "equity"]].copy()
    candidate["date"] = pd.to_datetime(candidate["date"])
    parent["date"] = pd.to_datetime(parent["date"])
    merged = candidate.merge(parent, on="date", how="inner", suffixes=("_strategy", "_parent")).sort_values("date")
    if merged.empty:
        return _empty_parent_period_counts()

    monthly = _count_period_winners(merged, [merged["date"].dt.year, merged["date"].dt.month])
    yearly = _count_period_winners(merged, [merged["date"].dt.year])
    return {
        "months_beating_parent": monthly["strategy"],
        "months_losing_to_parent": monthly["parent"],
        "months_tied_parent": monthly["tie"],
        "years_beating_parent": yearly["strategy"],
        "years_losing_to_parent": yearly["parent"],
        "years_tied_parent": yearly["tie"],
    }


def _count_period_winners(merged: pd.DataFrame, groupers: list[pd.Series]) -> dict[str, int]:
    counts = {"strategy": 0, "parent": 0, "tie": 0}
    for _, group in merged.groupby(groupers):
        if len(group) < 1:
            continue
        strategy_return = (group["equity_strategy"].iloc[-1] / group["equity_strategy"].iloc[0] - 1.0) * 100.0
        parent_return = (group["equity_parent"].iloc[-1] / group["equity_parent"].iloc[0] - 1.0) * 100.0
        if strategy_return > parent_return:
            counts["strategy"] += 1
        elif strategy_return < parent_return:
            counts["parent"] += 1
        else:
            counts["tie"] += 1
    return counts


def _empty_parent_period_counts() -> dict:
    return {
        "months_beating_parent": 0,
        "months_losing_to_parent": 0,
        "months_tied_parent": 0,
        "years_beating_parent": 0,
        "years_losing_to_parent": 0,
        "years_tied_parent": 0,
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
    parent_pass: bool | None = None,
    parent_strong_fail: bool = False,
    parent_metric_no_effect: bool = False,
    duplicate_artifact: bool = False,
) -> str:
    if blocking_issues:
        return "rejected"
    if duplicate_artifact or parent_metric_no_effect:
        return "rejected"
    if strategy_cagr is None or spy_cagr is None:
        return "rejected"
    if years_beating is None or years_losing is None:
        return "rejected"
    if number_of_trades < min_trades:
        return "rejected"
    if parent_strong_fail:
        return "rejected"
    if strategy_cagr < spy_cagr and not drawdown_improved:
        return "rejected"
    if years_beating <= years_losing:
        return "rejected"

    if parent_pass is False:
        return "accepted_for_followup"

    if strategy_cagr > spy_cagr and years_beating > years_losing and not drawdown_exaggerated_worse:
        return "promoted_candidate"

    return "accepted_for_followup"


def build_artifact_hash_payload(run_dir: Path, parent_run_dir: Path | None = None) -> dict:
    current = artifact_hashes(run_dir)
    payload = {"current": current, "duplicate_artifact": False}

    comparisons: list[tuple[str, Path]] = []
    if parent_run_dir is not None:
        comparisons.append(("parent", parent_run_dir))
    latest = _latest_previous_run_dir(run_dir)
    if latest is not None and (parent_run_dir is None or latest.resolve() != parent_run_dir.resolve()):
        comparisons.append(("last_run", latest))

    for label, other_dir in comparisons:
        other_hashes = artifact_hashes(other_dir)
        payload[label] = {"run_id": other_dir.name, "hashes": other_hashes}
        if artifacts_are_duplicate(current, other_hashes):
            payload["duplicate_artifact"] = True
            payload["duplicate_against"] = label
            payload["duplicate_run_id"] = other_dir.name
            break
    return payload


def _latest_previous_run_dir(run_dir: Path) -> Path | None:
    siblings = [p for p in run_dir.parent.glob("EXP_*") if p.is_dir() and p.resolve() != run_dir.resolve()]
    current_number = _run_number(run_dir.name)
    numbered = [(num, p) for p in siblings if (num := _run_number(p.name)) is not None]
    if current_number is not None:
        prior = [(num, p) for num, p in numbered if num < current_number]
        if prior:
            return sorted(prior, key=lambda item: item[0], reverse=True)[0][1]
    if not siblings:
        return None
    return sorted(siblings, key=lambda p: p.stat().st_mtime, reverse=True)[0]


def _run_number(name: str) -> int | None:
    match = re.fullmatch(r"EXP_(\d+)", name)
    return int(match.group(1)) if match else None


def _parent_comparison_no_effect(parent_comparison: dict) -> bool:
    cagr_delta = float(parent_comparison.get("excess_cagr_vs_parent_pct", 0.0))
    drawdown_delta = float(parent_comparison.get("drawdown_delta_vs_parent_pct", 0.0))
    trades_delta = int(parent_comparison.get("trade_count_delta", 0))
    months_beating = int(parent_comparison.get("months_beating_parent", 0))
    months_losing = int(parent_comparison.get("months_losing_to_parent", 0))
    months_tied = int(parent_comparison.get("months_tied_parent", 0))
    return cagr_delta == 0.0 and drawdown_delta == 0.0 and trades_delta == 0 and months_beating == 0 and months_losing == 0 and months_tied > 0


def _audit_flags(*, duplicate_artifact: bool, parent_metric_no_effect: bool) -> list[str]:
    flags: list[str] = []
    if duplicate_artifact:
        flags.extend(["duplicate_artifact", "metric_no_effect"])
    elif parent_metric_no_effect:
        flags.append("metric_no_effect")
    return flags


def _parent_comparison_passes(parent_comparison: dict) -> bool:
    cagr_delta = float(parent_comparison.get("excess_cagr_vs_parent_pct", 0.0))
    drawdown_delta = float(parent_comparison.get("drawdown_delta_vs_parent_pct", 0.0))
    years_beating = int(parent_comparison.get("years_beating_parent", 0))
    years_losing = int(parent_comparison.get("years_losing_to_parent", 0))

    if cagr_delta > 0 and drawdown_delta >= -5.0 and years_beating > years_losing:
        return True
    if drawdown_delta > 3.0 and cagr_delta >= -1.0 and years_beating >= years_losing:
        return True
    return False


def _parent_comparison_strong_fail(parent_comparison: dict) -> bool:
    cagr_delta = float(parent_comparison.get("excess_cagr_vs_parent_pct", 0.0))
    drawdown_delta = float(parent_comparison.get("drawdown_delta_vs_parent_pct", 0.0))
    return cagr_delta < 0 and drawdown_delta < 0


def _recommendation_for(decision: str) -> str:
    if decision == "promoted_candidate":
        return "Candidate can move forward for manual review; baseline promotion remains blocked."
    if decision == "accepted_for_followup":
        return "Keep researching; useful signal but not ready for baseline promotion."
    return "Reject or fix blocking issues before further research."


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as f:
        return json.load(f)


def _read_csv(path: Path) -> pd.DataFrame | None:
    if not path.exists():
        return None

    with path.open("r", encoding="utf-8-sig") as f:
        first_line = ""
        for line in f:
            if line.strip():
                first_line = line
                break

    if ";" in first_line:
        return pd.read_csv(path, sep=";", decimal=",")
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
