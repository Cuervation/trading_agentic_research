"""Champion and parent governance for autonomous research."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def read_json(path: str | Path, default: Any) -> Any:
    p = Path(path)
    if not p.exists():
        return default
    return json.loads(p.read_text(encoding="utf-8-sig"))


def write_json(path: str | Path, payload: Any) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def run_metrics(run_dir: str | Path) -> dict:
    p = Path(run_dir)
    metrics = read_json(p / "metrics.json", {})
    spy = read_json(p / "spy_comparison_summary.json", {})
    manifest = read_json(p / "run_manifest.json", {})
    strategy = metrics.get("strategy", {})
    return {
        "run_id": p.name,
        "parent_run_id": manifest.get("parent_run_id"),
        "hypothesis_id": manifest.get("hypothesis_id"),
        "family": manifest.get("hypothesis_family"),
        "cagr": _float(spy.get("strategy_cagr_pct", strategy.get("cagr_pct"))),
        "spy_cagr": _float(spy.get("spy_cagr_pct", metrics.get("spy", {}).get("cagr_pct"))),
        "excess_cagr": _float(spy.get("excess_cagr_pct")),
        "max_drawdown": _float(strategy.get("max_drawdown_pct")),
        "years_beating_spy": _int(spy.get("years_beating_spy")),
        "years_losing_to_spy": _int(spy.get("years_losing_to_spy")),
        "months_beating_spy": _int(spy.get("months_beating_spy")),
        "months_losing_to_spy": _int(spy.get("months_losing_to_spy")),
    }


def balance_score(metrics: dict) -> float:
    """Prefer robust CAGR, shallow drawdown and year consistency."""
    return (
        float(metrics.get("cagr", 0.0))
        + 5.0 * float(metrics.get("years_beating_spy", 0))
        - 5.0 * float(metrics.get("years_losing_to_spy", 0))
        + float(metrics.get("max_drawdown", 0.0))
    )


def aggressive_score(metrics: dict) -> float:
    return float(metrics.get("cagr", 0.0))


def classify_candidate(candidate: dict, champion: dict | None, parent_run_id: str | None) -> dict:
    """Classify one evaluated run without allowing unsafe parent moves."""
    if not parent_run_id:
        return _classification("rejected", "parent_run_id_missing", False, "rejected_with_learning")

    if not champion:
        return _classification("new_champion", "bootstrap_champion", True, "new_champion")

    candidate_balance = balance_score(candidate)
    champion_balance = balance_score(champion)
    cagr_delta = float(candidate.get("cagr", 0.0)) - float(champion.get("cagr", 0.0))
    dd_delta = float(candidate.get("max_drawdown", 0.0)) - float(champion.get("max_drawdown", 0.0))
    years_delta = int(candidate.get("years_beating_spy", 0)) - int(champion.get("years_beating_spy", 0))

    if candidate_balance > champion_balance:
        return _classification("new_champion", "dominates_best_champion_balance", True, "new_champion")
    if cagr_delta > 0 and dd_delta < 0:
        return _classification("aggressive_champion", "higher_cagr_worse_drawdown", False, "secondary_candidate")
    if cagr_delta > 0 or dd_delta > 0 or years_delta > 0:
        return _classification("secondary_candidate", "improves_one_axis_but_not_champion", False, "secondary_candidate")
    if float(candidate.get("cagr", 0.0)) > float(candidate.get("spy_cagr", 0.0)) and int(candidate.get("years_beating_spy", 0)) > int(candidate.get("years_losing_to_spy", 0)):
        return _classification("secondary_candidate", "beats_spy_but_loses_to_best_champion", False, "secondary_candidate")
    return _classification("rejected", "loses_to_best_champion", False, "rejected_with_learning")


def rebuild_champion_state_from_runs(runs_dir: str | Path = "runs", state_dir: str | Path = "state") -> dict:
    runs = []
    for p in sorted(Path(runs_dir).glob("*_*")):
        if p.is_dir() and (p.name.startswith("AUTO_") or p.name.startswith("EXP_")) and (p / "metrics.json").exists():
            runs.append(run_metrics(p))
    if not runs:
        state = _empty_state()
        write_json(Path(state_dir) / "champion_runs.json", state)
        return state

    best = max(runs, key=balance_score)
    aggressive = max(runs, key=aggressive_score)
    autos = [r for r in runs if str(r["run_id"]).startswith("AUTO_") and r["run_id"] != best["run_id"]]
    secondary = sorted(autos, key=balance_score, reverse=True)[:2]
    state = {
        "version": 1,
        "current_parent_run_id": best["run_id"],
        "best_champion_run_id": best["run_id"],
        "aggressive_champion_run_id": aggressive["run_id"],
        "baseline_candidate_run_id": best["run_id"],
        "manual_review_required": True,
        "secondary_candidates": [r["run_id"] for r in secondary],
        "runs": {r["run_id"]: {**r, "balance_score": balance_score(r), "aggressive_score": aggressive_score(r)} for r in runs},
    }
    write_json(Path(state_dir) / "champion_runs.json", state)
    write_json(
        Path(state_dir) / "current_parent.json",
        {
            "current_parent_run_id": state["current_parent_run_id"],
            "best_champion_run_id": state["best_champion_run_id"],
            "source": "champion_governance_rebuild",
        },
    )
    return state


def update_champion_governance(run_dir: str | Path, state_dir: str | Path = "state", parent_run_id: str | None = None) -> dict:
    path = Path(state_dir) / "champion_runs.json"
    state = read_json(path, _empty_state())
    candidate = run_metrics(run_dir)
    candidate["parent_run_id"] = parent_run_id or candidate.get("parent_run_id")
    runs = state.setdefault("runs", {})
    champion_id = state.get("best_champion_run_id")
    champion = runs.get(champion_id) if champion_id else None
    classification = classify_candidate(candidate, champion, candidate.get("parent_run_id"))
    candidate.update(classification)
    candidate["balance_score"] = balance_score(candidate)
    runs[candidate["run_id"]] = candidate

    if classification["value_delivered"] == "new_champion":
        state["best_champion_run_id"] = candidate["run_id"]
        state["current_parent_run_id"] = candidate["run_id"]
        state["baseline_candidate_run_id"] = candidate["run_id"]
        state["manual_review_required"] = True
        write_json(Path(state_dir) / "current_parent.json", {"current_parent_run_id": candidate["run_id"], "source": "champion_governance"})
    elif classification["decision"] == "aggressive_champion":
        state["aggressive_champion_run_id"] = candidate["run_id"]
    elif classification["decision"] == "secondary_candidate":
        secondary = state.setdefault("secondary_candidates", [])
        if candidate["run_id"] not in secondary:
            secondary.append(candidate["run_id"])

    write_json(path, state)
    return {"state": state, "classification": classification}


def _classification(decision: str, reason: str, can_move_parent: bool, value_delivered: str) -> dict:
    return {
        "decision": decision,
        "reason": reason,
        "can_move_parent": can_move_parent,
        "can_promote_baseline": False,
        "promoted_to_baseline_candidate": decision in {"new_champion", "aggressive_champion"},
        "manual_review_required": decision in {"new_champion", "aggressive_champion"},
        "value_delivered": value_delivered,
    }


def _empty_state() -> dict:
    return {
        "version": 1,
        "current_parent_run_id": None,
        "best_champion_run_id": None,
        "aggressive_champion_run_id": None,
        "baseline_candidate_run_id": None,
        "manual_review_required": True,
        "secondary_candidates": [],
        "runs": {},
    }


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


__all__ = [
    "run_metrics",
    "balance_score",
    "classify_candidate",
    "rebuild_champion_state_from_runs",
    "update_champion_governance",
]
