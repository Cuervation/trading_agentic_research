"""Drawdown-first scoring and reporting helpers."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import pandas as pd


DD_FIRST_COLUMNS = [
    "run_id",
    "strategy_id",
    "parent_id",
    "cagr",
    "spy_cagr",
    "excess_spy_cagr",
    "max_drawdown",
    "parent_max_drawdown",
    "drawdown_improvement_pct",
    "calmar",
    "spy_years",
    "spy_months",
    "trades",
    "decision",
    "rejection_reason",
    "dd_first_score",
    "drawdown_score",
    "calmar_score",
    "excess_spy_cagr_score",
    "yearly_spy_consistency_score",
    "monthly_consistency_score",
    "trade_count_score",
]


def evaluate_dd_first_run(
    run_dir: str | Path,
    *,
    parent_run_dir: str | Path | None = None,
    min_trades: int = 50,
    min_month_margin: int = 3,
    min_year_margin: int = 1,
) -> dict[str, Any]:
    """Evaluate a run with DD_FIRST lexicographic rules.

    This does not promote baselines or move current_parent. It only creates a
    local audit payload and a row for reports/dd_first_summary.csv.
    """
    path = Path(run_dir)
    metrics = _read_json(path / "metrics.json")
    summary = _read_json(path / "spy_comparison_summary.json")
    manifest = _read_json(path / "run_manifest.json")
    trades = _read_csv(path / "trades.csv")

    strategy_metrics = metrics.get("strategy", {}) if isinstance(metrics, dict) else {}
    spy_metrics = metrics.get("spy", {}) if isinstance(metrics, dict) else {}

    cagr = _as_float(strategy_metrics.get("cagr_pct"))
    spy_cagr = _as_float(spy_metrics.get("cagr_pct"))
    excess_spy_cagr = _as_float(summary.get("excess_cagr_pct"), cagr - spy_cagr)
    max_drawdown = _as_float(strategy_metrics.get("max_drawdown_pct"))
    trades_count = int(len(trades)) if trades is not None else 0
    spy_years = int(summary.get("years_beating_spy", 0) or 0)
    spy_year_losses = int(summary.get("years_losing_to_spy", 0) or 0)
    spy_months = int(summary.get("months_beating_spy", 0) or 0)
    spy_month_losses = int(summary.get("months_losing_to_spy", 0) or 0)

    parent_metrics: dict[str, Any] = {}
    parent_id = str(manifest.get("parent_run_id") or manifest.get("parent_strategy_id") or "")
    if parent_run_dir is not None:
        parent_path = Path(parent_run_dir)
        parent_id = parent_path.name
        if (parent_path / "metrics.json").exists():
            parent_metrics = _read_json(parent_path / "metrics.json").get("strategy", {})

    parent_max_drawdown = _as_float(parent_metrics.get("max_drawdown_pct")) if parent_metrics else None
    parent_cagr = _as_float(parent_metrics.get("cagr_pct")) if parent_metrics else None
    calmar = _calmar(cagr, max_drawdown)
    parent_calmar = _calmar(parent_cagr, parent_max_drawdown) if parent_cagr is not None and parent_max_drawdown is not None else None
    drawdown_improvement_pct = _drawdown_improvement(max_drawdown, parent_max_drawdown)

    scores = {
        "drawdown_score": _drawdown_score(max_drawdown, parent_max_drawdown),
        "calmar_score": calmar,
        "excess_spy_cagr_score": max(excess_spy_cagr, 0.0),
        "yearly_spy_consistency_score": _consistency_score(spy_years, spy_year_losses),
        "monthly_consistency_score": _consistency_score(spy_months, spy_month_losses),
        "trade_count_score": min(trades_count / float(min_trades), 2.0),
    }
    dd_first_score = round(
        (4.0 * scores["drawdown_score"])
        + (2.0 * scores["calmar_score"])
        + scores["excess_spy_cagr_score"]
        + scores["yearly_spy_consistency_score"]
        + scores["monthly_consistency_score"]
        + scores["trade_count_score"],
        6,
    )

    rejection_reasons = _dd_first_rejection_reasons(
        trades_count=trades_count,
        min_trades=min_trades,
        max_drawdown=max_drawdown,
        parent_max_drawdown=parent_max_drawdown,
        calmar=calmar,
        parent_calmar=parent_calmar,
        excess_spy_cagr=excess_spy_cagr,
        spy_years=spy_years,
        spy_year_losses=spy_year_losses,
        spy_months=spy_months,
        spy_month_losses=spy_month_losses,
        min_month_margin=min_month_margin,
        min_year_margin=min_year_margin,
    )
    decision = "accepted_for_dd_followup" if not rejection_reasons else "rejected"

    row = {
        "run_id": path.name,
        "strategy_id": str(manifest.get("strategy_id") or ""),
        "parent_id": parent_id,
        "cagr": round(cagr, 6),
        "spy_cagr": round(spy_cagr, 6),
        "excess_spy_cagr": round(excess_spy_cagr, 6),
        "max_drawdown": round(max_drawdown, 6),
        "parent_max_drawdown": round(parent_max_drawdown, 6) if parent_max_drawdown is not None else "",
        "drawdown_improvement_pct": round(drawdown_improvement_pct, 6) if drawdown_improvement_pct is not None else "",
        "calmar": round(calmar, 6),
        "spy_years": spy_years,
        "spy_months": spy_months,
        "trades": trades_count,
        "decision": decision,
        "rejection_reason": "; ".join(rejection_reasons),
        "dd_first_score": dd_first_score,
        **{key: round(value, 6) for key, value in scores.items()},
    }

    return {
        "evaluation_mode": "dd_first",
        "decision": decision,
        "rejection_reasons": rejection_reasons,
        "can_move_parent": False,
        "can_promote_baseline": False,
        "scores": scores | {"dd_first_score": dd_first_score},
        "row": row,
        "parent_comparison": {
            "parent_run_id": parent_id,
            "parent_cagr_pct": parent_cagr,
            "parent_max_drawdown_pct": parent_max_drawdown,
            "parent_calmar": parent_calmar,
            "drawdown_improvement_pct": drawdown_improvement_pct,
        },
    }


def append_dd_first_summary(report_path: str | Path, row: dict[str, Any]) -> None:
    path = Path(report_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not path.exists()
    with path.open("a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=DD_FIRST_COLUMNS, extrasaction="ignore")
        if write_header:
            writer.writeheader()
        writer.writerow(row)


def find_latest_run_for_strategy(runs_dir: str | Path, strategy_id: str) -> Path | None:
    root = Path(runs_dir)
    candidates: list[Path] = []
    run_dirs = root.iterdir() if root.exists() else []
    for run_dir in run_dirs:
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


def _dd_first_rejection_reasons(
    *,
    trades_count: int,
    min_trades: int,
    max_drawdown: float,
    parent_max_drawdown: float | None,
    calmar: float,
    parent_calmar: float | None,
    excess_spy_cagr: float,
    spy_years: int,
    spy_year_losses: int,
    spy_months: int,
    spy_month_losses: int,
    min_month_margin: int,
    min_year_margin: int,
) -> list[str]:
    reasons: list[str] = []
    if trades_count < min_trades:
        reasons.append(f"insufficient_trades:{trades_count}<{min_trades}")
    if parent_max_drawdown is not None and abs(max_drawdown) >= abs(parent_max_drawdown):
        reasons.append("drawdown_not_improved_vs_parent")
    if parent_calmar is not None and calmar <= parent_calmar:
        reasons.append("calmar_not_improved_vs_parent")
    if excess_spy_cagr <= 0:
        reasons.append("non_positive_excess_spy_cagr")
    if spy_years <= spy_year_losses or (spy_years - spy_year_losses) < min_year_margin:
        reasons.append("insufficient_yearly_spy_consistency")
    if spy_months <= spy_month_losses or (spy_months - spy_month_losses) < min_month_margin:
        reasons.append("insufficient_monthly_spy_consistency")
    return reasons


def _drawdown_improvement(max_drawdown: float, parent_max_drawdown: float | None) -> float | None:
    if parent_max_drawdown is None or parent_max_drawdown == 0:
        return None
    return ((abs(parent_max_drawdown) - abs(max_drawdown)) / abs(parent_max_drawdown)) * 100.0


def _drawdown_score(max_drawdown: float, parent_max_drawdown: float | None) -> float:
    if parent_max_drawdown is None:
        return max(0.0, 100.0 - abs(max_drawdown)) / 100.0
    improvement = _drawdown_improvement(max_drawdown, parent_max_drawdown)
    return (improvement or 0.0) / 10.0


def _calmar(cagr: float | None, max_drawdown: float | None) -> float:
    if cagr is None or max_drawdown is None or max_drawdown == 0:
        return 0.0
    return cagr / abs(max_drawdown)


def _consistency_score(wins: int, losses: int) -> float:
    total = wins + losses
    return (wins / total) if total > 0 else 0.0


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _read_csv(path: Path) -> pd.DataFrame | None:
    if not path.exists():
        return None
    return pd.read_csv(path, sep=";", decimal=",")


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
