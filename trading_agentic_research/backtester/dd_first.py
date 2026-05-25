"""Drawdown-first scoring and reporting helpers."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import pandas as pd

from scripts.governance import artifact_hashes, artifacts_are_duplicate

DD_FIRST_COLUMNS = [
    "run_id",
    "strategy_id",
    "parent_run_id",
    "parent_strategy_id",
    "decision",
    "dd_first_decision",
    "strategy_cagr_pct",
    "spy_cagr_pct",
    "excess_cagr_pct",
    "strategy_max_drawdown_pct",
    "spy_max_drawdown_pct",
    "parent_max_drawdown_pct",
    "drawdown_improvement_vs_parent_pct",
    "drawdown_improvement_vs_spy_pct",
    "calmar_ratio",
    "parent_calmar_ratio",
    "years_beating_spy",
    "years_losing_to_spy",
    "months_beating_spy",
    "months_losing_to_spy",
    "trades",
    "dd_first_score",
    "dd_first_rejection_reason",
]

DD_REQUIRED_RUN_FILES = [
    "equity_curve.csv",
    "trades.csv",
    "metrics.json",
    "spy_comparison_daily.csv",
    "spy_comparison_monthly.csv",
    "spy_comparison_yearly.csv",
    "spy_comparison_summary.json",
    "run_manifest.json",
]

CRITICAL_WARNING_KEYWORDS = (
    "critical",
    "lookahead",
    "data leakage",
    "leakage",
    "missing comparison",
    "missing costs",
    "costs not applied",
)


def evaluate_dd_first_run(
    run_dir: str | Path,
    *,
    parent_run_dir: str | Path | None = None,
    min_trades: int = 50,
    accepted_drawdown_improvement_pct: float = 10.0,
    promoted_drawdown_improvement_pct: float = 15.0,
) -> dict[str, Any]:
    """Evaluate one run with DD_FIRST rules.

    DD_FIRST is intentionally isolated from normal governance: it never moves
    current_parent, never promotes baseline, and only emits audit/report data.
    """
    path = Path(run_dir)
    parent_path = Path(parent_run_dir) if parent_run_dir is not None else None

    manifest = _read_json(path / "run_manifest.json") if (path / "run_manifest.json").exists() else {}
    metrics = _read_json(path / "metrics.json") if (path / "metrics.json").exists() else {}
    summary = _read_json(path / "spy_comparison_summary.json") if (path / "spy_comparison_summary.json").exists() else {}
    trades_df = _read_csv(path / "trades.csv")

    strategy_metrics = metrics.get("strategy", {}) if isinstance(metrics, dict) else {}
    spy_metrics = metrics.get("spy", {}) if isinstance(metrics, dict) else {}
    warnings = _extract_warnings(metrics)

    strategy_cagr = _first_float(summary.get("strategy_cagr_pct"), strategy_metrics.get("cagr_pct"))
    spy_cagr = _first_float(summary.get("spy_cagr_pct"), spy_metrics.get("cagr_pct"))
    excess_cagr = _first_float(summary.get("excess_cagr_pct"))
    if excess_cagr is None and strategy_cagr is not None and spy_cagr is not None:
        excess_cagr = strategy_cagr - spy_cagr

    strategy_dd = _first_float(strategy_metrics.get("max_drawdown_pct"))
    spy_dd = _first_float(spy_metrics.get("max_drawdown_pct"))
    years_beating = _as_int(summary.get("years_beating_spy"), 0)
    years_losing = _as_int(summary.get("years_losing_to_spy"), 0)
    months_beating = _as_int(summary.get("months_beating_spy"), 0)
    months_losing = _as_int(summary.get("months_losing_to_spy"), 0)
    trades = int(len(trades_df)) if trades_df is not None else 0

    parent_metrics: dict[str, Any] = {}
    parent_manifest: dict[str, Any] = {}
    parent_trades = None
    if parent_path is not None and parent_path.exists():
        parent_metrics_payload = _read_json(parent_path / "metrics.json") if (parent_path / "metrics.json").exists() else {}
        parent_metrics = parent_metrics_payload.get("strategy", {}) if isinstance(parent_metrics_payload, dict) else {}
        parent_manifest = _read_json(parent_path / "run_manifest.json") if (parent_path / "run_manifest.json").exists() else {}
        parent_trades = _read_csv(parent_path / "trades.csv")

    parent_dd = _first_float(parent_metrics.get("max_drawdown_pct"))
    parent_cagr = _first_float(parent_metrics.get("cagr_pct"))
    parent_calmar = _calmar(parent_cagr, parent_dd)
    calmar = _calmar(strategy_cagr, strategy_dd)
    improvement_parent = _drawdown_improvement(strategy_dd, parent_dd)
    improvement_spy = _drawdown_improvement(strategy_dd, spy_dd)

    missing_files = [name for name in DD_REQUIRED_RUN_FILES if not (path / name).exists()]
    missing_spy_fields = [
        field
        for field in [
            "strategy_cagr_pct",
            "spy_cagr_pct",
            "excess_cagr_pct",
            "months_beating_spy",
            "months_losing_to_spy",
            "years_beating_spy",
            "years_losing_to_spy",
        ]
        if field not in summary
    ]
    costs_present = _costs_are_present(metrics, trades_df)
    critical_warnings = _critical_warnings(warnings)
    duplicate_artifact = _duplicate_artifact(path, parent_path)
    metric_no_effect = _metric_no_effect(strategy_cagr, parent_cagr, strategy_dd, parent_dd, trades, parent_trades)
    killed_sample = _killed_trade_sample(trades, parent_trades, min_trades)

    rejection_reasons: list[str] = []
    if missing_files:
        rejection_reasons.append(f"missing_required_artifacts:{','.join(missing_files)}")
    if not costs_present:
        rejection_reasons.append("missing_costs")
    if missing_spy_fields:
        rejection_reasons.append(f"missing_spy_comparison:{','.join(missing_spy_fields)}")
    if critical_warnings:
        rejection_reasons.append("critical_warning")
    if trades < min_trades:
        rejection_reasons.append(f"insufficient_trades:{trades}<{min_trades}")
    if metric_no_effect:
        rejection_reasons.append("metric_no_effect")
    if duplicate_artifact:
        rejection_reasons.append("duplicate_artifact")
    if strategy_cagr is None or spy_cagr is None or excess_cagr is None or strategy_dd is None:
        rejection_reasons.append("missing_core_metrics")
    if strategy_cagr is not None and spy_cagr is not None and strategy_cagr <= spy_cagr and (improvement_parent or 0.0) < accepted_drawdown_improvement_pct:
        rejection_reasons.append("underperforms_spy_without_material_drawdown_improvement")
    if parent_dd is not None and strategy_dd is not None and abs(strategy_dd) > abs(parent_dd):
        rejection_reasons.append("worse_drawdown_than_parent")
    if killed_sample:
        rejection_reasons.append("drawdown_reduction_killed_trade_sample")

    accepted = (
        not rejection_reasons
        and (improvement_parent or 0.0) >= accepted_drawdown_improvement_pct
        and (excess_cagr or 0.0) > 0
        and years_beating >= years_losing
        and trades >= min_trades
    )
    promoted = (
        accepted
        and (improvement_parent or 0.0) >= promoted_drawdown_improvement_pct
        and calmar > parent_calmar
        and (excess_cagr or 0.0) > 0
        and years_beating > years_losing
        and years_beating >= 2
        and months_beating >= months_losing
    )

    if promoted:
        dd_decision = "promoted_candidate"
    elif accepted:
        dd_decision = "accepted_for_followup"
    else:
        dd_decision = "rejected"

    score = _dd_first_score(
        drawdown_improvement_vs_parent_pct=improvement_parent,
        calmar_ratio=calmar,
        parent_calmar_ratio=parent_calmar,
        excess_cagr_pct=excess_cagr,
        years_beating_spy=years_beating,
        years_losing_to_spy=years_losing,
        months_beating_spy=months_beating,
        months_losing_to_spy=months_losing,
        trades=trades,
        min_trades=min_trades,
    )

    parent_run_id = parent_path.name if parent_path is not None else str(manifest.get("parent_run_id") or "")
    parent_strategy_id = str(
        manifest.get("parent_strategy_id")
        or parent_manifest.get("strategy_id")
        or ""
    )

    row = {
        "run_id": path.name,
        "strategy_id": str(manifest.get("strategy_id") or ""),
        "parent_run_id": parent_run_id,
        "parent_strategy_id": parent_strategy_id,
        "decision": dd_decision,
        "dd_first_decision": dd_decision,
        "strategy_cagr_pct": _round_or_blank(strategy_cagr),
        "spy_cagr_pct": _round_or_blank(spy_cagr),
        "excess_cagr_pct": _round_or_blank(excess_cagr),
        "strategy_max_drawdown_pct": _round_or_blank(strategy_dd),
        "spy_max_drawdown_pct": _round_or_blank(spy_dd),
        "parent_max_drawdown_pct": _round_or_blank(parent_dd),
        "drawdown_improvement_vs_parent_pct": _round_or_blank(improvement_parent),
        "drawdown_improvement_vs_spy_pct": _round_or_blank(improvement_spy),
        "calmar_ratio": _round_or_blank(calmar),
        "parent_calmar_ratio": _round_or_blank(parent_calmar),
        "years_beating_spy": years_beating,
        "years_losing_to_spy": years_losing,
        "months_beating_spy": months_beating,
        "months_losing_to_spy": months_losing,
        "trades": trades,
        "dd_first_score": round(score, 6),
        "dd_first_rejection_reason": "; ".join(dict.fromkeys(rejection_reasons)),
    }

    return {
        "audit_status": "completed" if not missing_files else "completed_with_missing_files",
        "evaluation_mode": "dd_first",
        "decision": dd_decision,
        "dd_first_decision": dd_decision,
        "dd_first_rejection_reason": row["dd_first_rejection_reason"],
        "reasons": rejection_reasons,
        "blocking_issues": rejection_reasons,
        "warnings": warnings,
        "can_move_parent": False,
        "can_promote_baseline": False,
        "flags": [flag for flag, enabled in {"duplicate_artifact": duplicate_artifact, "metric_no_effect": metric_no_effect}.items() if enabled],
        "dd_first": row,
        "parent_comparison": {
            "parent_run_id": parent_run_id,
            "parent_strategy_id": parent_strategy_id,
            "parent_cagr_pct": parent_cagr,
            "parent_max_drawdown_pct": parent_dd,
            "parent_calmar_ratio": parent_calmar,
            "drawdown_improvement_vs_parent_pct": improvement_parent,
        },
    }


def append_dd_first_summary(report_path: str | Path, row: dict[str, Any]) -> None:
    path = Path(report_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not path.exists() or path.stat().st_size == 0
    with path.open("a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=DD_FIRST_COLUMNS, extrasaction="ignore", delimiter=";")
        if write_header:
            writer.writeheader()
        writer.writerow({key: _csv_value(row.get(key, "")) for key in DD_FIRST_COLUMNS})


def write_dd_first_summary(report_path: str | Path, rows: list[dict[str, Any]]) -> None:
    path = Path(report_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=DD_FIRST_COLUMNS, extrasaction="ignore", delimiter=";")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _csv_value(row.get(key, "")) for key in DD_FIRST_COLUMNS})


def find_latest_run_for_strategy(runs_dir: str | Path, strategy_id: str) -> Path | None:
    root = Path(runs_dir)
    candidates: list[Path] = []
    for run_dir in root.iterdir() if root.exists() else []:
        if not run_dir.is_dir():
            continue
        manifest_path = run_dir / "run_manifest.json"
        if not manifest_path.exists():
            continue
        try:
            manifest = _read_json(manifest_path)
        except json.JSONDecodeError:
            continue
        if manifest.get("strategy_id") == strategy_id:
            candidates.append(run_dir)
    if not candidates:
        return None
    return sorted(candidates, key=lambda p: p.stat().st_mtime, reverse=True)[0]


def row_from_audit_or_run(run_dir: str | Path, parent_run_dir: str | Path | None = None, min_trades: int = 50) -> dict[str, Any]:
    path = Path(run_dir)
    audit_path = path / "audit.json"
    if audit_path.exists():
        audit = _read_json(audit_path)
        if isinstance(audit.get("dd_first"), dict):
            return audit["dd_first"]
    return evaluate_dd_first_run(path, parent_run_dir=parent_run_dir, min_trades=min_trades)["dd_first"]


def _dd_first_score(**kwargs: Any) -> float:
    improvement = max(float(kwargs.get("drawdown_improvement_vs_parent_pct") or 0.0), 0.0)
    calmar = float(kwargs.get("calmar_ratio") or 0.0)
    parent_calmar = float(kwargs.get("parent_calmar_ratio") or 0.0)
    excess = max(float(kwargs.get("excess_cagr_pct") or 0.0), 0.0)
    years_w = int(kwargs.get("years_beating_spy") or 0)
    years_l = int(kwargs.get("years_losing_to_spy") or 0)
    months_w = int(kwargs.get("months_beating_spy") or 0)
    months_l = int(kwargs.get("months_losing_to_spy") or 0)
    trades = int(kwargs.get("trades") or 0)
    min_trades = max(int(kwargs.get("min_trades") or 1), 1)
    yearly = years_w / max(years_w + years_l, 1)
    monthly = months_w / max(months_w + months_l, 1)
    trade_score = min(trades / min_trades, 2.0)
    calmar_delta = max(calmar - parent_calmar, 0.0)
    return (4.0 * improvement) + (20.0 * calmar_delta) + excess + (10.0 * yearly) + (5.0 * monthly) + trade_score


def _metric_no_effect(strategy_cagr, parent_cagr, strategy_dd, parent_dd, trades: int, parent_trades: pd.DataFrame | None) -> bool:
    if parent_cagr is None or parent_dd is None or strategy_cagr is None or strategy_dd is None:
        return False
    parent_trade_count = len(parent_trades) if parent_trades is not None else None
    return strategy_cagr == parent_cagr and strategy_dd == parent_dd and (parent_trade_count is None or trades == parent_trade_count)


def _killed_trade_sample(trades: int, parent_trades: pd.DataFrame | None, min_trades: int) -> bool:
    if trades < min_trades:
        return True
    if parent_trades is None:
        return False
    parent_count = len(parent_trades)
    return parent_count >= min_trades and trades < max(min_trades, int(parent_count * 0.5))


def _duplicate_artifact(path: Path, parent_path: Path | None) -> bool:
    if parent_path is None or not parent_path.exists():
        return False
    try:
        return artifacts_are_duplicate(artifact_hashes(path), artifact_hashes(parent_path))
    except Exception:
        return False


def _drawdown_improvement(candidate_dd: float | None, reference_dd: float | None) -> float | None:
    if candidate_dd is None or reference_dd is None or reference_dd == 0:
        return None
    return ((abs(reference_dd) - abs(candidate_dd)) / abs(reference_dd)) * 100.0


def _calmar(cagr: float | None, max_drawdown: float | None) -> float:
    if cagr is None or max_drawdown is None or max_drawdown == 0:
        return 0.0
    return cagr / abs(max_drawdown)


def _costs_are_present(metrics: dict, trades_df: pd.DataFrame | None) -> bool:
    costs = metrics.get("costs", {}) if isinstance(metrics, dict) else {}
    if costs.get("applied") is True and _as_float(costs.get("cost_per_side_pct"), 0.0) > 0:
        return True
    if trades_df is None or trades_df.empty:
        return False
    if {"gross_return_pct", "net_return_pct"}.issubset(trades_df.columns):
        return bool((trades_df["gross_return_pct"] != trades_df["net_return_pct"]).any())
    return False


def _critical_warnings(warnings: list[str]) -> list[str]:
    return [w for w in warnings if any(keyword in w.lower() for keyword in CRITICAL_WARNING_KEYWORDS)]


def _extract_warnings(metrics: dict) -> list[str]:
    diagnostics = metrics.get("diagnostics", {}) if isinstance(metrics, dict) else {}
    raw = diagnostics.get("warnings", [])
    return [str(raw)] if not isinstance(raw, list) else [str(x) for x in raw]


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _read_csv(path: Path) -> pd.DataFrame | None:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8-sig") as f:
        first = next((line for line in f if line.strip()), "")
    if ";" in first:
        return pd.read_csv(path, sep=";", decimal=",")
    return pd.read_csv(path)


def _first_float(*values: Any) -> float | None:
    for value in values:
        parsed = _as_float(value, None)
        if parsed is not None:
            return parsed
    return None


def _as_float(value: Any, default: float | None = None) -> float | None:
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _round_or_blank(value: float | None) -> float | str:
    return "" if value is None else round(float(value), 6)


def _csv_value(value: Any) -> Any:
    if isinstance(value, float):
        return str(value).replace(".", ",")
    return value
