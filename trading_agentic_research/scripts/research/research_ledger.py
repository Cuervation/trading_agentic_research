"""Research ledger for continuous-learning runs.

Each run should leave explicit value, even when rejected:
- new_champion / promotion_candidate
- secondary_candidate / defensive_secondary_candidate
- rejected_with_learning
- duplicate_blocked / metric_no_effect_blocked
- missing_artifacts
"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.research.artifact_index import build_artifact_signature, read_json, write_json

LEDGER_FILE = "research_ledger.jsonl"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _read_csv_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        sample = f.read(4096)
        f.seek(0)
        lines = sample.splitlines()
        first = lines[0] if lines else ""
        delimiter = ";" if ";" in first else ","
        reader = csv.DictReader(f, delimiter=delimiter)
        return list(reader)


def run_summary(run_dir: str | Path) -> dict[str, Any]:
    path = Path(run_dir)
    metrics = read_json(path / "metrics.json", {}) or {}
    comparison = read_json(path / "spy_comparison_summary.json", {}) or {}
    manifest = read_json(path / "run_manifest.json", {}) or {}
    trades_path = path / "trades.csv"
    trades_count = 0
    if trades_path.exists():
        try:
            trades_count = sum(1 for _ in trades_path.open("r", encoding="utf-8-sig")) - 1
            trades_count = max(0, trades_count)
        except OSError:
            trades_count = 0

    strategy = metrics.get("strategy", {}) if isinstance(metrics, dict) else {}
    spy = metrics.get("spy", {}) if isinstance(metrics, dict) else {}
    return {
        "run_id": path.name,
        "strategy_id": manifest.get("strategy_id") or strategy.get("strategy_id"),
        "hypothesis_id": manifest.get("hypothesis_id") or manifest.get("strategy_id"),
        "parent_run_id": manifest.get("parent_run_id"),
        "strategy_cagr_pct": _as_float(comparison.get("strategy_cagr_pct", strategy.get("cagr_pct"))),
        "spy_cagr_pct": _as_float(comparison.get("spy_cagr_pct", spy.get("cagr_pct"))),
        "excess_cagr_pct": _as_float(comparison.get("excess_cagr_pct")),
        "strategy_total_return_pct": _as_float(strategy.get("total_return_pct")),
        "spy_total_return_pct": _as_float(spy.get("total_return_pct")),
        "strategy_max_drawdown_pct": _as_float(strategy.get("max_drawdown_pct")),
        "spy_max_drawdown_pct": _as_float(spy.get("max_drawdown_pct")),
        "months_beating_spy": _as_int(comparison.get("months_beating_spy")),
        "months_losing_to_spy": _as_int(comparison.get("months_losing_to_spy")),
        "years_beating_spy": _as_int(comparison.get("years_beating_spy")),
        "years_losing_to_spy": _as_int(comparison.get("years_losing_to_spy")),
        "trades": trades_count,
        "has_audit": (path / "audit.json").exists(),
        "has_manifest": (path / "run_manifest.json").exists(),
    }


def classify_value_delivered(
    *,
    run_dir: str | Path,
    audit: dict[str, Any] | None,
    duplicate_info: dict[str, Any] | None = None,
    champion_decision: dict[str, Any] | None = None,
) -> str:
    audit = audit or {}
    duplicate_info = duplicate_info or {}
    champion_decision = champion_decision or {}
    flags = set(audit.get("flags", []) or [])
    decision = str(audit.get("decision", ""))

    if duplicate_info.get("is_duplicate") or audit.get("duplicate_result") or "duplicate_result" in flags or "duplicate_artifact" in flags:
        return "duplicate_blocked"
    if "metric_no_effect" in flags:
        return "metric_no_effect_blocked"
    if champion_decision.get("champion_action") == "new_best_champion":
        return "new_champion"
    if champion_decision.get("champion_action") == "promotion_candidate_manual_review":
        return "promotion_candidate"
    if champion_decision.get("champion_action") == "aggressive_champion":
        return "aggressive_champion"
    if champion_decision.get("champion_action") == "defensive_secondary_candidate":
        return "defensive_secondary_candidate"
    if decision == "promoted_candidate":
        return "promotion_candidate"
    if decision == "accepted_for_followup":
        return "secondary_candidate"
    if decision == "rejected":
        return "rejected_with_learning"
    sig = build_artifact_signature(run_dir)
    if sig.get("missing_artifacts"):
        return "missing_artifacts"
    return "review_needed"


def build_learning_sentence(summary: dict[str, Any], audit: dict[str, Any], value_delivered: str, duplicate_info: dict[str, Any] | None = None) -> str:
    duplicate_info = duplicate_info or {}
    run_id = summary.get("run_id")
    if value_delivered == "duplicate_blocked":
        return f"{run_id} duplicated artifact signature first seen in {duplicate_info.get('duplicate_of_run_id') or audit.get('duplicate_of_run_id')}; do not repeat this effective result."
    if value_delivered == "new_champion":
        return f"{run_id} became a new champion with CAGR {summary.get('strategy_cagr_pct'):.2f}% and drawdown {summary.get('strategy_max_drawdown_pct'):.2f}%."
    if value_delivered == "promotion_candidate":
        return f"{run_id} is a promotion candidate; review CAGR/drawdown tradeoff before moving parent."
    if value_delivered == "defensive_secondary_candidate":
        return f"{run_id} looks defensive: likely useful for lower drawdown but not a main parent without review."
    if value_delivered == "secondary_candidate":
        return f"{run_id} produced a non-duplicate follow-up candidate; keep as secondary evidence."
    if value_delivered == "metric_no_effect_blocked":
        return f"{run_id} had metric_no_effect; this hypothesis/config path should be blocked or changed materially."
    if value_delivered == "missing_artifacts":
        return f"{run_id} lacks required artifacts; it cannot govern parent/champion state."
    return f"{run_id} was rejected with evidence; use the audit reasons to avoid repeating this direction."


def next_action_for(value_delivered: str) -> str:
    return {
        "duplicate_blocked": "block_signature_and_try_different_axis",
        "metric_no_effect_blocked": "improve_materiality_or_abandon_axis",
        "new_champion": "manual_review_then_refine_champion",
        "promotion_candidate": "manual_review_or_refine_drawdown",
        "aggressive_champion": "keep_as_aggressive_reference_not_parent",
        "defensive_secondary_candidate": "store_as_defensive_variant",
        "secondary_candidate": "compare_against_champion_before_followup",
        "rejected_with_learning": "avoid_same_axis_or_search_new_literature",
        "missing_artifacts": "repair_run_outputs_before_learning",
    }.get(value_delivered, "manual_review")


def build_ledger_event(
    *,
    run_dir: str | Path,
    audit: dict[str, Any] | None = None,
    duplicate_info: dict[str, Any] | None = None,
    champion_decision: dict[str, Any] | None = None,
) -> dict[str, Any]:
    path = Path(run_dir)
    audit = audit if audit is not None else read_json(path / "audit.json", {}) or {}
    summary = run_summary(path)
    artifact = build_artifact_signature(path)
    value = classify_value_delivered(
        run_dir=path,
        audit=audit,
        duplicate_info=duplicate_info,
        champion_decision=champion_decision,
    )
    return {
        "event_id": f"LEDGER_{summary['run_id']}",
        "created_at": now_iso(),
        "run_id": summary["run_id"],
        "hypothesis_id": summary.get("hypothesis_id"),
        "strategy_id": summary.get("strategy_id"),
        "parent_run_id": summary.get("parent_run_id"),
        "decision": audit.get("decision"),
        "value_delivered": value,
        "learned": build_learning_sentence(summary, audit, value, duplicate_info=duplicate_info),
        "next_action": next_action_for(value),
        "artifact_signature": artifact.get("artifact_signature"),
        "duplicate_of_run_id": (duplicate_info or {}).get("duplicate_of_run_id") or audit.get("duplicate_of_run_id"),
        "flags": audit.get("flags", []),
        "metrics": summary,
        "champion_decision": champion_decision or {},
    }


def ledger_path(state_dir: str | Path) -> Path:
    return Path(state_dir) / LEDGER_FILE


def read_ledger(state_dir: str | Path) -> list[dict[str, Any]]:
    path = ledger_path(state_dir)
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def append_ledger_event(state_dir: str | Path, event: dict[str, Any]) -> dict[str, Any]:
    path = ledger_path(state_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [row for row in read_ledger(state_dir) if row.get("run_id") != event.get("run_id")]
    rows.append(event)
    path.write_text("".join(json.dumps(row, ensure_ascii=False, default=str) + "\n" for row in rows), encoding="utf-8")
    return event


def append_run_to_ledger(
    *,
    run_dir: str | Path,
    state_dir: str | Path,
    audit: dict[str, Any] | None = None,
    duplicate_info: dict[str, Any] | None = None,
    champion_decision: dict[str, Any] | None = None,
) -> dict[str, Any]:
    event = build_ledger_event(
        run_dir=run_dir,
        audit=audit,
        duplicate_info=duplicate_info,
        champion_decision=champion_decision,
    )
    return append_ledger_event(state_dir, event)


__all__ = [
    "run_summary",
    "build_ledger_event",
    "append_run_to_ledger",
    "read_ledger",
    "classify_value_delivered",
]
