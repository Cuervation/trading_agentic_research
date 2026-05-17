"""Update empirical evidence and learning memory."""

from __future__ import annotations

import json
from pathlib import Path


def classify_learning_flags(metrics: dict) -> list[str]:
    """Classify key empirical flags from compact metric deltas."""
    flags: list[str] = []
    if float(metrics.get("best_year_contribution_pct", 0.0)) >= 50.0:
        flags.append("concentration_risk")

    cagr_delta = float(metrics.get("cagr_delta_pct", 0.0))
    drawdown_delta = float(metrics.get("max_drawdown_delta_pct", 0.0))

    if cagr_delta > 0 and drawdown_delta < -5.0:
        flags.append("riskier_candidate")
    if abs(cagr_delta) <= 1.0 and drawdown_delta > 3.0:
        flags.append("defensive_improvement")

    if bool(metrics.get("metric_no_effect", False)):
        flags.append("metric_no_effect")
    if float(metrics.get("parent_cagr_delta_pct", 0.0)) < 0 and float(metrics.get("parent_drawdown_delta_pct", 0.0)) < 0:
        flags.append("parent_underperformance")
    return flags


def build_learning_event(
    learning_id: str,
    hypothesis_id: str,
    family: str,
    run_id: str,
    decision: str,
    metrics: dict,
) -> dict:
    """Build one learning event. Baseline promotion is never automatic."""
    return {
        "learning_id": learning_id,
        "hypothesis_id": hypothesis_id,
        "family": family,
        "run_id": run_id,
        "decision": decision,
        "flags": classify_learning_flags(metrics),
        "written_to_learning_memory": True,
        "can_promote_baseline": False,
    }


def family_should_go_to_cooldown(events: list[dict], family: str, threshold: int = 3) -> bool:
    """Return True when a family has repeated failures."""
    failures = [
        event for event in events
        if event.get("family") == family and event.get("decision") == "rejected"
    ]
    return len(failures) >= threshold


def update_subspace_cooldowns(cooldowns: dict, events: list[dict], threshold: int = 3) -> dict:
    """Mark repeatedly failing families as cooldown subspaces."""
    updated = dict(cooldowns)
    updated.setdefault("cooldowns", {})
    families = {event.get("family") for event in events if event.get("family")}

    for family in families:
        if family_should_go_to_cooldown(events, family, threshold=threshold):
            updated["cooldowns"][family] = {
                "reason": "repeated_failed_hypotheses",
                "failure_threshold": threshold,
            }
    return updated


def append_learning_event(memory_path: str | Path, event: dict) -> dict:
    """Upsert learning event into learning_memory.json."""
    path = Path(memory_path)
    memory = json.loads(path.read_text(encoding="utf-8-sig"))
    existing_events = memory.setdefault("learning_events", [])
    memory["learning_events"] = [
        existing for existing in existing_events
        if existing.get("learning_id") != event.get("learning_id")
    ]
    memory["learning_events"].append(event)

    memory["family_summaries"] = _build_family_summaries(memory["learning_events"])

    path.write_text(json.dumps(memory, indent=2, ensure_ascii=False), encoding="utf-8")
    return memory


def _build_family_summaries(events: list[dict]) -> dict:
    summaries: dict[str, dict] = {}
    for event in events:
        family = event["family"]
        summary = summaries.setdefault(
            family,
            {"rejections": 0, "acceptances": 0, "promoted_candidates": 0},
        )
        if event["decision"] == "rejected":
            summary["rejections"] += 1
        elif event["decision"] == "accepted_for_followup":
            summary["acceptances"] += 1
        elif event["decision"] == "promoted_candidate":
            summary["promoted_candidates"] += 1
    return summaries



def build_learning_metrics(metrics_payload: dict, comparison_summary: dict, yearly_rows: list[dict] | None = None) -> dict:
    """Build compact deltas used by the learning layer."""
    strategy = metrics_payload.get("strategy", {})
    spy = metrics_payload.get("spy", {})

    strategy_dd = float(strategy.get("max_drawdown_pct", 0.0))
    spy_dd = float(spy.get("max_drawdown_pct", 0.0))

    learning_metrics = {
        "cagr_delta_pct": float(comparison_summary.get("excess_cagr_pct", 0.0)),
        "max_drawdown_delta_pct": strategy_dd - spy_dd,
        "months_beating_spy": int(comparison_summary.get("months_beating_spy", 0)),
        "months_losing_to_spy": int(comparison_summary.get("months_losing_to_spy", 0)),
        "years_beating_spy": int(comparison_summary.get("years_beating_spy", 0)),
        "years_losing_to_spy": int(comparison_summary.get("years_losing_to_spy", 0)),
    }

    if yearly_rows:
        excess_values = [abs(float(row.get("excess_return_pct", 0.0))) for row in yearly_rows]
        total_abs_excess = sum(excess_values)
        learning_metrics["best_year_contribution_pct"] = (
            max(excess_values) / total_abs_excess * 100.0 if total_abs_excess else 0.0
        )

    return learning_metrics


def persist_learning_from_run(
    *,
    run_dir: str | Path,
    state_dir: str | Path,
    run_id: str,
    hypothesis_id: str,
    family: str,
    audit: dict,
) -> dict:
    """Persist audit outcome into learning/evidence memories and cooldowns."""
    run_path = Path(run_dir)
    state_path = Path(state_dir)
    state_path.mkdir(parents=True, exist_ok=True)

    metrics_payload = _read_json(run_path / "metrics.json")
    comparison_summary = _read_json(run_path / "spy_comparison_summary.json")
    yearly_rows = _read_csv_rows(run_path / "spy_comparison_yearly.csv")
    learning_metrics = build_learning_metrics(metrics_payload, comparison_summary, yearly_rows)
    parent_comparison = audit.get("parent_comparison")
    if isinstance(parent_comparison, dict) and parent_comparison.get("parent_available"):
        learning_metrics.update(
            {
                "parent_cagr_delta_pct": float(parent_comparison.get("excess_cagr_vs_parent_pct", 0.0)),
                "parent_drawdown_delta_pct": float(parent_comparison.get("drawdown_delta_vs_parent_pct", 0.0)),
                "months_beating_parent": int(parent_comparison.get("months_beating_parent", 0)),
                "months_losing_to_parent": int(parent_comparison.get("months_losing_to_parent", 0)),
                "years_beating_parent": int(parent_comparison.get("years_beating_parent", 0)),
                "years_losing_to_parent": int(parent_comparison.get("years_losing_to_parent", 0)),
            }
        )

    learning_id = f"LEARN_{run_id}"
    event = build_learning_event(
        learning_id=learning_id,
        hypothesis_id=hypothesis_id,
        family=family,
        run_id=run_id,
        decision=audit["decision"],
        metrics=learning_metrics,
    )

    learning_memory_path = state_path / "learning_memory.json"
    if not learning_memory_path.exists():
        learning_memory_path.write_text(
            json.dumps({"version": 1, "family_summaries": {}, "learning_events": []}, indent=2),
            encoding="utf-8",
        )
    memory = append_learning_event(learning_memory_path, event)

    evidence_memory_path = state_path / "evidence_memory.json"
    if evidence_memory_path.exists():
        evidence = _read_json(evidence_memory_path)
    else:
        evidence = {"version": 1, "runs": {}, "hypothesis_evidence": {}}

    evidence.setdefault("runs", {})[run_id] = {
        "hypothesis_id": hypothesis_id,
        "family": family,
        "learning_id": learning_id,
        "decision": audit["decision"],
        "metrics": learning_metrics,
        "can_promote_baseline": False,
    }
    hypothesis_runs = evidence.setdefault("hypothesis_evidence", {}).setdefault(hypothesis_id, [])
    if run_id not in hypothesis_runs:
        hypothesis_runs.append(run_id)
    evidence_memory_path.write_text(json.dumps(evidence, indent=2, ensure_ascii=False), encoding="utf-8")

    line_payload = {
        "hypothesis_id": hypothesis_id,
        "family": family,
        "run_id": run_id,
        "learning_id": learning_id,
        "decision": audit["decision"],
        "flags": event["flags"],
    }
    target_jsonl = (
        state_path / "rejected_hypotheses.jsonl"
        if audit["decision"] == "rejected"
        else state_path / "accepted_hypotheses.jsonl"
    )
    opposite_jsonl = (
        state_path / "accepted_hypotheses.jsonl"
        if audit["decision"] == "rejected"
        else state_path / "rejected_hypotheses.jsonl"
    )
    _remove_jsonl_match(opposite_jsonl, line_payload, unique_keys=("hypothesis_id", "run_id"))
    _append_unique_jsonl(target_jsonl, line_payload, unique_keys=("hypothesis_id", "run_id"))

    cooldowns_path = state_path / "subspace_cooldowns.json"
    if cooldowns_path.exists():
        cooldowns = _read_json(cooldowns_path)
    else:
        cooldowns = {"version": 1, "cooldowns": {}, "default_failure_threshold": 3}
    threshold = int(cooldowns.get("default_failure_threshold", 3))
    cooldowns = update_subspace_cooldowns(cooldowns, memory.get("learning_events", []), threshold=threshold)
    cooldowns_path.write_text(json.dumps(cooldowns, indent=2, ensure_ascii=False), encoding="utf-8")

    return {
        "learning_event": event,
        "learning_memory_path": str(learning_memory_path),
        "evidence_memory_path": str(evidence_memory_path),
        "cooldowns_path": str(cooldowns_path),
    }


def _append_unique_jsonl(path: Path, payload: dict, unique_keys: tuple[str, ...]) -> None:
    rows = []
    if path.exists():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if all(row.get(key) == payload.get(key) for key in unique_keys):
                continue
            rows.append(row)
    rows.append(payload)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def _remove_jsonl_match(path: Path, payload: dict, unique_keys: tuple[str, ...]) -> None:
    if not path.exists():
        return
    rows = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if all(row.get(key) == payload.get(key) for key in unique_keys):
            continue
        rows.append(row)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _read_csv_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8-sig").splitlines()
    if not text:
        return []
    sep = ";" if ";" in text[0] else ","
    headers = text[0].split(sep)
    rows = []
    for line in text[1:]:
        if not line.strip():
            continue
        values = line.split(sep)
        row = {}
        for key, value in zip(headers, values):
            row[key] = value.replace(",", ".") if sep == ";" else value
        rows.append(row)
    return rows
