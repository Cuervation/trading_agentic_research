"""Evaluate real backtest artifacts for autonomous research."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtester.validation import audit_run_folder


def evaluate_completed_run(run_dir: str | Path, parent_run_dir: str | Path | None = None, hypothesis: dict | None = None) -> dict:
    """Audit a completed run folder and enrich with normalized research fields."""
    run_path = Path(run_dir)
    audit = _read_json(run_path / "audit.json") if (run_path / "audit.json").exists() else audit_run_folder(run_path, parent_run_dir=parent_run_dir)
    metrics = _read_json(run_path / "metrics.json")
    comparison = _read_json(run_path / "spy_comparison_summary.json")
    trades = _read_csv(run_path / "trades.csv")

    decision = str(audit.get("decision"))
    promoted = decision == "promoted_candidate"
    accepted = decision == "accepted_for_followup"
    trade_counts = _trade_win_loss_tie_counts(trades)

    return {
        **audit,
        "run_id": run_path.name,
        "hypothesis_id": (hypothesis or {}).get("hypothesis_id"),
        "decision": decision,
        "accepted_for_followup": accepted,
        "promoted_to_baseline_candidate": promoted,
        "manual_review_required": promoted,
        "can_move_parent": bool(audit.get("can_move_parent")) and decision in {"accepted_for_followup", "promoted_candidate"},
        "can_promote_baseline": False,
        "strategy_cagr": _float(comparison.get("strategy_cagr_pct", metrics.get("strategy", {}).get("cagr_pct"))),
        "spy_cagr": _float(comparison.get("spy_cagr_pct", metrics.get("spy", {}).get("cagr_pct"))),
        "excess_cagr": _float(comparison.get("excess_cagr_pct")),
        "total_return_strategy": _float(metrics.get("strategy", {}).get("total_return_pct")),
        "total_return_spy": _float(metrics.get("spy", {}).get("total_return_pct")),
        "max_drawdown_strategy": _float(metrics.get("strategy", {}).get("max_drawdown_pct")),
        "max_drawdown_spy": _float(metrics.get("spy", {}).get("max_drawdown_pct")),
        "trades": int(len(trades)) if trades is not None else 0,
        **trade_counts,
        "months_beating_spy": int(comparison.get("months_beating_spy", 0)),
        "months_losing_to_spy": int(comparison.get("months_losing_to_spy", 0)),
        "months_tied_spy": int(comparison.get("months_tied_spy", 0)),
        "years_beating_spy": int(comparison.get("years_beating_spy", 0)),
        "years_losing_to_spy": int(comparison.get("years_losing_to_spy", 0)),
        "years_tied_spy": int(comparison.get("years_tied_spy", 0)),
        "evaluation_source": "real_artifacts",
    }


def _trade_win_loss_tie_counts(trades: pd.DataFrame | None) -> dict:
    if trades is None or trades.empty or "net_return_pct" not in trades.columns:
        return {"trade_wins": 0, "trade_ties": 0, "trade_losses": 0}
    values = pd.to_numeric(trades["net_return_pct"], errors="coerce").fillna(0.0)
    return {
        "trade_wins": int((values > 1.0).sum()),
        "trade_ties": int(((values >= 0.0) & (values <= 1.0)).sum()),
        "trade_losses": int((values < 0.0).sum()),
    }


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _read_csv(path: Path) -> pd.DataFrame | None:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8-sig") as f:
        first = f.readline()
    sep = ";" if ";" in first else ","
    return pd.read_csv(path, sep=sep, decimal="," if sep == ";" else ".")


def _float(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


__all__ = ["evaluate_completed_run"]
