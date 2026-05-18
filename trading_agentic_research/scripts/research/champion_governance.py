"""Champion/parent governance for research runs.

Separates:
- current_parent_run_id: what future hypotheses should refine.
- best_champion_run_id: best robust strategy found so far.
- aggressive_champion_run_id: highest CAGR candidate with worse drawdown.
- promotion_candidates: candidates requiring manual review.
- secondary_candidates: useful but not main parent.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.research.artifact_index import read_json, write_json
from scripts.research.research_ledger import run_summary

CHAMPION_FILE = "champion_runs.json"
CURRENT_PARENT_FILE = "current_parent.json"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def champion_state_path(state_dir: str | Path) -> Path:
    return Path(state_dir) / CHAMPION_FILE


def load_champion_state(state_dir: str | Path) -> dict[str, Any]:
    payload = read_json(champion_state_path(state_dir), None)
    if not payload:
        payload = {
            "version": 2,
            "best_champion_run_id": None,
            "current_parent_run_id": None,
            "aggressive_champion_run_id": None,
            "baseline_candidate_run_id": None,
            "promotion_candidates": [],
            "secondary_candidates": [],
            "defensive_secondary_candidates": [],
            "champion_runs": [],
            "updated_at": now_iso(),
        }
    payload.setdefault("version", 2)
    payload.setdefault("promotion_candidates", [])
    payload.setdefault("secondary_candidates", [])
    payload.setdefault("defensive_secondary_candidates", [])
    payload.setdefault("champion_runs", [])
    return payload


def save_champion_state(state_dir: str | Path, state: dict[str, Any]) -> None:
    state["updated_at"] = now_iso()
    write_json(champion_state_path(state_dir), state)


def _run_snapshot(run_dir: str | Path, audit: dict[str, Any] | None = None) -> dict[str, Any]:
    summary = run_summary(run_dir)
    return {
        "run_id": summary["run_id"],
        "strategy_id": summary.get("strategy_id"),
        "hypothesis_id": summary.get("hypothesis_id"),
        "parent_run_id": summary.get("parent_run_id"),
        "decision": (audit or {}).get("decision"),
        "strategy_cagr_pct": summary.get("strategy_cagr_pct"),
        "strategy_max_drawdown_pct": summary.get("strategy_max_drawdown_pct"),
        "months_beating_spy": summary.get("months_beating_spy"),
        "months_losing_to_spy": summary.get("months_losing_to_spy"),
        "years_beating_spy": summary.get("years_beating_spy"),
        "years_losing_to_spy": summary.get("years_losing_to_spy"),
        "trades": summary.get("trades"),
        "updated_at": now_iso(),
    }


def _score(snapshot: dict[str, Any]) -> float:
    """Robust score: CAGR + drawdown quality + yearly consistency."""
    cagr = _as_float(snapshot.get("strategy_cagr_pct"))
    dd = _as_float(snapshot.get("strategy_max_drawdown_pct"))  # negative
    years_win = _as_float(snapshot.get("years_beating_spy"))
    years_loss = _as_float(snapshot.get("years_losing_to_spy"))
    months_win = _as_float(snapshot.get("months_beating_spy"))
    months_loss = _as_float(snapshot.get("months_losing_to_spy"))
    # Less negative drawdown is better. Penalize drawdown magnitude moderately.
    return cagr + (0.35 * dd) + (2.0 * (years_win - years_loss)) + (0.05 * (months_win - months_loss))


def _is_clear_best(candidate: dict[str, Any], current: dict[str, Any] | None) -> bool:
    if not current:
        return True
    cagr_delta = _as_float(candidate.get("strategy_cagr_pct")) - _as_float(current.get("strategy_cagr_pct"))
    dd_delta = _as_float(candidate.get("strategy_max_drawdown_pct")) - _as_float(current.get("strategy_max_drawdown_pct"))
    years_delta = _as_float(candidate.get("years_beating_spy")) - _as_float(current.get("years_beating_spy"))
    score_delta = _score(candidate) - _score(current)

    # Clear improvement: better robust score and no severe drawdown/year degradation.
    if score_delta > 1.0 and cagr_delta >= 0.0 and dd_delta >= -3.0 and years_delta >= -1:
        return True
    # Dominance: higher CAGR, lower drawdown, at least same yearly performance.
    if cagr_delta >= 0.0 and dd_delta >= 0.0 and years_delta >= 0:
        return True
    return False


def _is_promotion_candidate(candidate: dict[str, Any], current: dict[str, Any] | None) -> bool:
    if not current:
        return False
    cagr_delta = _as_float(candidate.get("strategy_cagr_pct")) - _as_float(current.get("strategy_cagr_pct"))
    dd_delta = _as_float(candidate.get("strategy_max_drawdown_pct")) - _as_float(current.get("strategy_max_drawdown_pct"))
    months_delta = _as_float(candidate.get("months_beating_spy")) - _as_float(current.get("months_beating_spy"))
    # Example: AUTO_092-like case: mild CAGR/month improvement, small drawdown degradation.
    return cagr_delta > 0.0 and dd_delta >= -4.0 and months_delta >= 0


def _is_aggressive(candidate: dict[str, Any], current: dict[str, Any] | None) -> bool:
    if not current:
        return False
    cagr_delta = _as_float(candidate.get("strategy_cagr_pct")) - _as_float(current.get("strategy_cagr_pct"))
    dd_delta = _as_float(candidate.get("strategy_max_drawdown_pct")) - _as_float(current.get("strategy_max_drawdown_pct"))
    return cagr_delta >= 2.0 and dd_delta < -5.0


def _is_defensive(candidate: dict[str, Any], current: dict[str, Any] | None) -> bool:
    if not current:
        return False
    cagr_delta = _as_float(candidate.get("strategy_cagr_pct")) - _as_float(current.get("strategy_cagr_pct"))
    dd_delta = _as_float(candidate.get("strategy_max_drawdown_pct")) - _as_float(current.get("strategy_max_drawdown_pct"))
    return dd_delta >= 3.0 and cagr_delta < -3.0


def _upsert_snapshot(rows: list[dict[str, Any]], snapshot: dict[str, Any], *, max_items: int = 20) -> list[dict[str, Any]]:
    out = [row for row in rows if row.get("run_id") != snapshot.get("run_id")]
    out.append(snapshot)
    out.sort(key=_score, reverse=True)
    return out[:max_items]


def _snapshot_by_run_id(state: dict[str, Any], run_id: str | None) -> dict[str, Any] | None:
    if not run_id:
        return None
    for bucket in ("champion_runs", "promotion_candidates", "secondary_candidates", "defensive_secondary_candidates"):
        for row in state.get(bucket, []) or []:
            if row.get("run_id") == run_id:
                return row
    return None


def update_current_parent_file(state_dir: str | Path, snapshot: dict[str, Any], reason: str) -> None:
    payload = {
        "current_parent_run_id": snapshot.get("run_id"),
        "current_parent_strategy_id": snapshot.get("strategy_id"),
        "best_champion_run_id": snapshot.get("run_id"),
        "updated_at": now_iso(),
        "updated_from_champion_governance": True,
        "reason": reason,
    }
    write_json(Path(state_dir) / CURRENT_PARENT_FILE, payload)


def update_champion_state(
    *,
    run_dir: str | Path,
    state_dir: str | Path,
    audit: dict[str, Any] | None = None,
    duplicate_info: dict[str, Any] | None = None,
    allow_parent_move: bool = False,
) -> dict[str, Any]:
    """Update champion governance from one completed run.

    Parent movement is conservative and disabled by default. A promoted candidate
    should normally require manual review.
    """
    audit = audit or {}
    duplicate_info = duplicate_info or {}
    snapshot = _run_snapshot(run_dir, audit=audit)
    state = load_champion_state(state_dir)
    current_best = _snapshot_by_run_id(state, state.get("best_champion_run_id"))

    if duplicate_info.get("is_duplicate") or audit.get("duplicate_result") or "duplicate_artifact" in (audit.get("flags") or []):
        decision = {
            "champion_action": "ignored_duplicate",
            "manual_review_required": False,
            "can_move_parent": False,
            "reason": "duplicate_result cannot affect champion governance",
        }
        save_champion_state(state_dir, state)
        return decision

    if audit.get("decision") == "rejected":
        decision = {
            "champion_action": "ignored_rejected",
            "manual_review_required": False,
            "can_move_parent": False,
            "reason": "rejected run cannot move champion",
        }
        save_champion_state(state_dir, state)
        return decision

    action = "secondary_candidate"
    manual_review = False
    can_move_parent = False

    if _is_clear_best(snapshot, current_best):
        state["best_champion_run_id"] = snapshot["run_id"]
        state["champion_runs"] = _upsert_snapshot(state.get("champion_runs", []), snapshot)
        action = "new_best_champion"
        can_move_parent = bool(allow_parent_move)
        if allow_parent_move:
            state["current_parent_run_id"] = snapshot["run_id"]
            update_current_parent_file(state_dir, snapshot, reason="New clear best champion from governance.")
    elif _is_promotion_candidate(snapshot, current_best):
        state["promotion_candidates"] = _upsert_snapshot(state.get("promotion_candidates", []), snapshot)
        state["baseline_candidate_run_id"] = snapshot["run_id"]
        action = "promotion_candidate_manual_review"
        manual_review = True
    elif _is_aggressive(snapshot, current_best):
        current_aggressive = _snapshot_by_run_id(state, state.get("aggressive_champion_run_id"))
        if not current_aggressive or _as_float(snapshot.get("strategy_cagr_pct")) > _as_float(current_aggressive.get("strategy_cagr_pct")):
            state["aggressive_champion_run_id"] = snapshot["run_id"]
        state["secondary_candidates"] = _upsert_snapshot(state.get("secondary_candidates", []), snapshot)
        action = "aggressive_champion"
    elif _is_defensive(snapshot, current_best):
        state["defensive_secondary_candidates"] = _upsert_snapshot(state.get("defensive_secondary_candidates", []), snapshot)
        action = "defensive_secondary_candidate"
    else:
        state["secondary_candidates"] = _upsert_snapshot(state.get("secondary_candidates", []), snapshot)
        action = "secondary_candidate"

    if not state.get("current_parent_run_id") and state.get("best_champion_run_id"):
        state["current_parent_run_id"] = state.get("best_champion_run_id")

    save_champion_state(state_dir, state)
    return {
        "champion_action": action,
        "manual_review_required": manual_review,
        "can_move_parent": can_move_parent,
        "best_champion_run_id": state.get("best_champion_run_id"),
        "current_parent_run_id": state.get("current_parent_run_id"),
        "baseline_candidate_run_id": state.get("baseline_candidate_run_id"),
    }


__all__ = ["load_champion_state", "save_champion_state", "update_champion_state"]
