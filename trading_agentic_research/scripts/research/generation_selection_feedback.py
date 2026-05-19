"""Explain why freshly generated hypotheses are or are not selectable.

This module is intentionally diagnostic. It does not move parents, promote
champions, or change decisions. It records the bridge between a generator that
adds rows to bibliography/hypothesis_bank.jsonl and the selector that decides
whether any of those rows are usable.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.parameter_effect_memory import load_parameter_effect_memory
from scripts.score_hypothesis_against_memory import score_hypothesis_against_memory
from scripts.research.autonomous_hypothesis_factory import real_override_signature
from scripts.research.candidate_review_learning import (
    candidate_review_scope_reason,
    is_candidate_review_hypothesis_blocked,
)
from scripts.research.consumed_hypotheses import consumed_hypothesis_ids

FEEDBACK_JSON = "generation_selection_feedback.json"
FEEDBACK_MD = "generation_selection_feedback.md"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: str | Path, default: Any = None) -> Any:
    p = Path(path)
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return default


def write_json(path: str | Path, payload: Any) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    p = Path(path)
    if not p.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in p.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def _repeat_blocked_hypothesis_ids(history: list[dict[str, Any]], max_repeats_per_hypothesis: int = 1) -> set[str]:
    counts = Counter(str(item.get("hypothesis_id")) for item in history if item.get("hypothesis_id"))
    return {hypothesis_id for hypothesis_id, count in counts.items() if count >= max_repeats_per_hypothesis}


def _blocked_signatures(bank: list[dict[str, Any]], blocked_ids: set[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for row in bank:
        hid = str(row.get("hypothesis_id") or "")
        overrides = row.get("strategy_overrides")
        if hid in blocked_ids and isinstance(overrides, dict) and overrides:
            out.setdefault(real_override_signature(overrides), hid)
    return out


def _load_selector_state(state_dir: str | Path, max_repeats_per_hypothesis: int) -> dict[str, Any]:
    state_path = Path(state_dir)
    current_parent = read_json(state_path / "current_parent.json", {}) or {}
    batch_state = read_json(state_path / "batch_state.json", {}) or {}
    rejected_ids = {str(row.get("hypothesis_id")) for row in read_jsonl(state_path / "rejected_hypotheses.jsonl") if row.get("hypothesis_id")}
    accepted_ids = {str(row.get("hypothesis_id")) for row in read_jsonl(state_path / "accepted_hypotheses.jsonl") if row.get("hypothesis_id")}
    consumed_ids = consumed_hypothesis_ids(state_path)
    repeat_blocked = _repeat_blocked_hypothesis_ids(batch_state.get("history", []) or [], max_repeats_per_hypothesis)
    return {
        "learning_memory": read_json(state_path / "learning_memory.json", {}) or {},
        "cooldowns": read_json(state_path / "subspace_cooldowns.json", {}) or {},
        "parameter_effect_memory": load_parameter_effect_memory(state_path / "parameter_effect_memory.json"),
        "current_parent_hypothesis_id": str(
            current_parent.get("current_parent_hypothesis_id") or current_parent.get("current_parent_strategy_id") or ""
        ) or None,
        "rejected_ids": rejected_ids,
        "accepted_ids": accepted_ids,
        "consumed_ids": consumed_ids,
        "repeat_blocked": repeat_blocked,
        "blocked_ids_for_signature": set(rejected_ids).union(accepted_ids).union(consumed_ids),
    }


def diagnose_generated_hypotheses(
    *,
    hypothesis_bank_path: str | Path = "bibliography/hypothesis_bank.jsonl",
    state_dir: str | Path = "state",
    hypothesis_ids: list[str] | set[str] | tuple[str, ...],
    max_repeats_per_hypothesis: int = 1,
) -> dict[str, Any]:
    """Return per-hypothesis selector diagnostics for freshly generated ids."""
    requested = [str(x) for x in hypothesis_ids if x]
    bank = read_jsonl(hypothesis_bank_path)
    by_id = {str(row.get("hypothesis_id")): row for row in bank if row.get("hypothesis_id")}
    selector_state = _load_selector_state(state_dir, max_repeats_per_hypothesis)
    signature_owner = _blocked_signatures(bank, selector_state["blocked_ids_for_signature"])

    selectable: list[str] = []
    blocked: list[dict[str, Any]] = []
    missing: list[str] = []

    for hid in requested:
        row = by_id.get(hid)
        if not row:
            missing.append(hid)
            blocked.append({"hypothesis_id": hid, "reason": "missing_from_hypothesis_bank"})
            continue

        reason: str | None = None
        details: dict[str, Any] = {}
        status = str(row.get("status", "candidate"))
        if status not in {"candidate", "seeded"}:
            reason = "non_candidate_status"
            details["status"] = status
        elif hid in selector_state["rejected_ids"]:
            reason = "rejected"
        elif hid in selector_state["accepted_ids"]:
            reason = "accepted_already"
        elif hid in selector_state["consumed_ids"]:
            reason = "consumed"
        elif hid in selector_state["repeat_blocked"]:
            reason = "repeat_blocked"
        elif selector_state["current_parent_hypothesis_id"] and hid == selector_state["current_parent_hypothesis_id"]:
            reason = "current_parent_hypothesis"
        else:
            scope_reason = candidate_review_scope_reason(row, state_dir=state_dir)
            if scope_reason:
                reason = f"candidate_review_scope:{scope_reason}"
            elif is_candidate_review_hypothesis_blocked(row, state_dir=state_dir):
                reason = "candidate_review_axis_exhausted"
            else:
                overrides = row.get("strategy_overrides")
                if isinstance(overrides, dict) and overrides:
                    sig = real_override_signature(overrides)
                    owner = signature_owner.get(sig)
                    if owner and owner != hid:
                        reason = "duplicate_signature_blocked"
                        details["duplicate_signature_of_hypothesis_id"] = owner
                if not reason:
                    score = score_hypothesis_against_memory(
                        row,
                        selector_state["learning_memory"],
                        selector_state["cooldowns"],
                    )
                    if score.get("decision") == "rejected":
                        reason = "selector_memory_rejected"
                        details["score"] = score

        if reason:
            blocked.append({
                "hypothesis_id": hid,
                "family": row.get("family"),
                "reason": reason,
                **details,
            })
        else:
            selectable.append(hid)

    return {
        "timestamp": now_iso(),
        "generated_ids": requested,
        "selectable": selectable,
        "blocked": blocked,
        "missing": missing,
        "generated_count": len(requested),
        "selectable_count": len(selectable),
        "blocked_count": len(blocked),
        "missing_count": len(missing),
        "summary_by_reason": dict(Counter(str(row.get("reason")) for row in blocked)),
    }


def record_generation_selection_feedback(
    *,
    state_dir: str | Path = "state",
    reports_dir: str | Path = "reports",
    phase: str,
    generation_result: dict[str, Any],
    diagnosis: dict[str, Any],
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    state_path = Path(state_dir)
    payload = read_json(state_path / FEEDBACK_JSON, None) or {"version": 1, "events": []}
    event = {
        "timestamp": now_iso(),
        "phase": phase,
        "generated": int(generation_result.get("generated", generation_result.get("rows_written", 0)) or 0),
        "generation_reason": generation_result.get("reason"),
        "hypotheses": generation_result.get("hypotheses", []),
        "selectable_count": diagnosis.get("selectable_count", 0),
        "selectable": diagnosis.get("selectable", []),
        "blocked_count": diagnosis.get("blocked_count", 0),
        "summary_by_reason": diagnosis.get("summary_by_reason", {}),
        "blocked": diagnosis.get("blocked", [])[:50],
        "context": context or {},
    }
    payload.setdefault("events", []).append(event)
    payload["updated_at"] = now_iso()
    write_json(state_path / FEEDBACK_JSON, payload)
    write_generation_selection_feedback_report(state_dir=state_dir, reports_dir=reports_dir)
    return event


def write_generation_selection_feedback_report(*, state_dir: str | Path = "state", reports_dir: str | Path = "reports") -> dict[str, Any]:
    payload = read_json(Path(state_dir) / FEEDBACK_JSON, None) or {"events": []}
    events = payload.get("events", []) or []
    out = Path(reports_dir) / FEEDBACK_MD
    out.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Generation → Selection Feedback",
        "",
        f"- Generated at: {now_iso()}",
        f"- Events: {len(events)}",
        "",
        "## Recent events",
        "",
        "| phase | generated | selectable | top selectable | reasons |",
        "|---|---:|---:|---|---|",
    ]
    for event in events[-30:]:
        reasons = ", ".join(f"{k}:{v}" for k, v in (event.get("summary_by_reason") or {}).items())
        top = ", ".join((event.get("selectable") or [])[:3])
        lines.append(
            f"| {event.get('phase', '')} | {event.get('generated', 0)} | {event.get('selectable_count', 0)} | {top} | {reasons} |"
        )
    lines.extend(["", "## Last blocked details", ""])
    if events:
        for row in (events[-1].get("blocked") or [])[:25]:
            lines.append(f"- `{row.get('hypothesis_id')}` family={row.get('family')} reason={row.get('reason')}")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"report": str(out), "events": len(events)}
