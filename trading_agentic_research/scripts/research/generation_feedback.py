"""Generation eligibility feedback for autonomous research.

The autonomous loop can produce new hypotheses that are immediately ineligible
because they are consumed, rejected, accepted, blocked by candidate-review axis
learning, duplicate existing signatures, or rejected by the selector's memory
score. This module records that feedback so future decisions distinguish
"generated rows" from "generated useful work".
"""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.parameter_effect_memory import load_parameter_effect_memory
from scripts.score_hypothesis_against_memory import score_hypothesis_against_memory
from scripts.research.candidate_review_learning import (
    infer_candidate_review_axis,
    is_candidate_review_hypothesis_blocked,
    load_candidate_review_learning,
)
from scripts.research.consumed_hypotheses import consumed_hypothesis_ids

FEEDBACK_JSON = "generation_feedback.json"
FEEDBACK_MD = "generation_feedback.md"


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


def _generated_count(result: dict[str, Any]) -> int:
    if not isinstance(result, dict):
        return 0
    for key in ("generated", "rows_written"):
        if key in result:
            try:
                return int(result.get(key) or 0)
            except (TypeError, ValueError):
                return 0
    nested = result.get("literature_miner") if isinstance(result.get("literature_miner"), dict) else None
    if nested is not None:
        return _generated_count(nested)
    return 0


def record_generation_feedback(
    *,
    state_dir: str | Path = "state",
    reports_dir: str | Path = "reports",
    phase: str,
    generation_result: dict[str, Any],
    eligibility_before: dict[str, Any] | None = None,
    eligibility_after: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    state_path = Path(state_dir)
    payload = read_json(state_path / FEEDBACK_JSON, None) or {"version": 1, "events": []}
    before = eligibility_before or {}
    after = eligibility_after or {}
    generated = _generated_count(generation_result)
    eligible_after = bool(after.get("eligible"))
    event = {
        "timestamp": now_iso(),
        "phase": phase,
        "generated": generated,
        "eligible_after_generation": eligible_after,
        "eligible_hypothesis_id": after.get("hypothesis_id"),
        "eligible_family": after.get("family"),
        "reason": generation_result.get("reason") if isinstance(generation_result, dict) else None,
        "before_reason": before.get("reason"),
        "after_reason": after.get("reason"),
        "generation_result": generation_result,
        "context": context or {},
    }
    if generated > 0 and not eligible_after:
        event["warning"] = "generated_but_no_eligible_hypothesis"
    if generated == 0 and phase == "candidate_under_review":
        event["warning"] = event.get("warning") or "candidate_review_generated_zero"
    payload.setdefault("events", []).append(event)
    payload["updated_at"] = now_iso()
    write_json(state_path / FEEDBACK_JSON, payload)
    write_generation_feedback_report(state_dir=state_dir, reports_dir=reports_dir)
    return event


def _candidate_review_hypotheses(candidate_run_id: str | None, hypothesis_bank: str | Path) -> list[dict[str, Any]]:
    if not candidate_run_id:
        return []
    prefix = f"HYP_REVIEW_{candidate_run_id}_"
    return [row for row in read_jsonl(hypothesis_bank) if str(row.get("hypothesis_id", "")).startswith(prefix)]


def _repeat_blocked_hypothesis_ids(history: list[dict[str, Any]], max_repeats_per_hypothesis: int = 1) -> set[str]:
    counts = Counter(str(item.get("hypothesis_id")) for item in history if item.get("hypothesis_id"))
    return {hypothesis_id for hypothesis_id, count in counts.items() if count >= max_repeats_per_hypothesis}


def _selector_diagnostics_for_candidate_review(
    *,
    state_dir: str | Path,
    rows: list[dict[str, Any]],
    max_repeats_per_hypothesis: int = 1,
) -> dict[str, Any]:
    """Explain whether candidate-review rows are selectable by selector-equivalent rules.

    This mirrors choose_next_hypothesis filters closely enough for exhaustion
    decisions, while preserving diagnostics for the feedback report.
    """
    state_path = Path(state_dir)
    learning_memory = read_json(state_path / "learning_memory.json", {}) or {}
    cooldowns = read_json(state_path / "subspace_cooldowns.json", {}) or {}
    current_parent = read_json(state_path / "current_parent.json", {}) or {}
    parameter_effect_memory = load_parameter_effect_memory(state_path / "parameter_effect_memory.json")
    rejected_ids = {str(row.get("hypothesis_id")) for row in read_jsonl(state_path / "rejected_hypotheses.jsonl") if row.get("hypothesis_id")}
    accepted_ids = {str(row.get("hypothesis_id")) for row in read_jsonl(state_path / "accepted_hypotheses.jsonl") if row.get("hypothesis_id")}
    consumed_ids = consumed_hypothesis_ids(state_path)
    batch_state = read_json(state_path / "batch_state.json", {}) or {}
    repeat_blocked = _repeat_blocked_hypothesis_ids(batch_state.get("history", []) or [], max_repeats_per_hypothesis)
    current_parent_hypothesis_id = str(
        current_parent.get("current_parent_hypothesis_id") or current_parent.get("current_parent_strategy_id") or ""
    )

    selectable: list[str] = []
    blocked: list[dict[str, Any]] = []
    for row in rows:
        hid = str(row.get("hypothesis_id") or "")
        status = str(row.get("status", "candidate"))
        reason: str | None = None
        score: dict[str, Any] | None = None

        if status not in {"candidate", "seeded"}:
            reason = "non_candidate_status"
        elif hid in rejected_ids:
            reason = "rejected"
        elif current_parent_hypothesis_id and hid == current_parent_hypothesis_id:
            reason = "current_parent_hypothesis"
        elif hid in consumed_ids:
            reason = "consumed"
        elif hid in repeat_blocked:
            reason = "repeat_blocked"
        elif is_candidate_review_hypothesis_blocked(row, state_dir=state_path):
            reason = "candidate_review_axis_exhausted"
        elif hid in accepted_ids:
            reason = "accepted_already"
        else:
            score = score_hypothesis_against_memory(row, learning_memory, cooldowns)
            if score.get("decision") == "rejected":
                reason = "selector_memory_rejected"

        axis = infer_candidate_review_axis(row)
        if reason:
            blocked.append({"hypothesis_id": hid, "axis": axis, "reason": reason, "score": score or {}})
        else:
            selectable.append(hid)

    return {
        "selectable_remaining": selectable,
        "blocked": blocked,
        "counts": {
            "rows": len(rows),
            "selectable": len(selectable),
            "blocked": len(blocked),
            "rejected": len(rejected_ids),
            "accepted": len(accepted_ids),
            "consumed": len(consumed_ids),
            "repeat_blocked": len(repeat_blocked),
        },
    }


def maybe_mark_candidate_review_exhausted(
    *,
    state_dir: str | Path = "state",
    hypothesis_bank: str | Path = "bibliography/hypothesis_bank.jsonl",
    generation_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Mark candidate_under_review as review_exhausted when no useful review work remains.

    Earlier versions only checked if rows looked syntactically candidate-like.
    That was too optimistic: rows can still be rejected by consumed/rejected/
    accepted/cooldown/memory selector rules. This version uses selector-equivalent
    diagnostics before leaving the candidate active.
    """
    state_path = Path(state_dir)
    candidate_path = state_path / "candidate_under_review.json"
    candidate = read_json(candidate_path, {}) or {}
    if candidate.get("status") != "active":
        return generation_result or {"generated": 0, "reason": "candidate_not_active"}

    result = dict(generation_result or {})
    candidate_run_id = candidate.get("candidate_run_id")
    rows = _candidate_review_hypotheses(str(candidate_run_id) if candidate_run_id else None, hypothesis_bank)

    learning = load_candidate_review_learning(state_dir)
    exhausted_axes = set(learning.get("exhausted_axes", []) or [])
    consumed = consumed_hypothesis_ids(state_dir)
    rejected = {str(row.get("hypothesis_id")) for row in read_jsonl(state_path / "rejected_hypotheses.jsonl") if row.get("hypothesis_id")}
    accepted = {str(row.get("hypothesis_id")) for row in read_jsonl(state_path / "accepted_hypotheses.jsonl") if row.get("hypothesis_id")}

    eligible_like: list[str] = []
    blocked: list[dict[str, str]] = []
    for row in rows:
        hid = str(row.get("hypothesis_id") or "")
        axis = infer_candidate_review_axis(row)
        if axis in exhausted_axes:
            reason = "axis_exhausted"
        elif hid in consumed:
            reason = "consumed"
        elif hid in rejected:
            reason = "rejected"
        elif hid in accepted:
            reason = "accepted_already"
        elif str(row.get("status", "candidate")) not in {"candidate", "seeded"}:
            reason = "non_candidate_status"
        else:
            eligible_like.append(hid)
            continue
        blocked.append({"hypothesis_id": hid, "axis": axis, "reason": reason})

    selector_diag = _selector_diagnostics_for_candidate_review(state_dir=state_dir, rows=rows)
    result["candidate_review_selectable_remaining"] = selector_diag["selectable_remaining"]
    result["candidate_review_selector_blocked"] = selector_diag["blocked"][:50]
    result["candidate_review_selector_counts"] = selector_diag["counts"]

    if selector_diag["selectable_remaining"]:
        # Keep previous human-friendly diagnostics, but make selector truth primary.
        result.setdefault("candidate_review_eligible_remaining", eligible_like)
        result.setdefault("candidate_review_blocked", blocked[:20])
        return result

    # Mark exhausted when either there are existing rows and all are blocked by
    # real selector-equivalent rules, or the factory explicitly says no new work
    # exists for an active review.
    reason = str(result.get("reason") or "")
    generated = _generated_count(result)
    should_exhaust = bool(rows) or (generated == 0 and reason in {
        "no_new_candidate_under_review_hypotheses",
        "candidate_under_review_already_exhausted",
        "no_candidate_review_hypotheses",
    })
    if not should_exhaust:
        return result

    candidate["status"] = "review_exhausted"
    candidate["reason"] = "no_selector_eligible_candidate_review_hypotheses"
    candidate["review_exhausted_at"] = now_iso()
    candidate["blocked_hypotheses"] = selector_diag["blocked"][-50:]
    candidate["selector_counts"] = selector_diag["counts"]
    write_json(candidate_path, candidate)

    result["candidate_review_status"] = "review_exhausted"
    result["candidate_review_blocked"] = blocked[:20]
    result["candidate_review_exhaustion_reason"] = "no_selector_eligible_candidate_review_hypotheses"
    result.setdefault("reason", "candidate_review_exhausted")
    return result


def write_generation_feedback_report(*, state_dir: str | Path = "state", reports_dir: str | Path = "reports") -> dict[str, Any]:
    payload = read_json(Path(state_dir) / FEEDBACK_JSON, None) or {"events": []}
    events = payload.get("events", []) or []
    out = Path(reports_dir) / FEEDBACK_MD
    out.parent.mkdir(parents=True, exist_ok=True)

    lines = [
        "# Generation Eligibility Feedback",
        "",
        f"- Generated at: {now_iso()}",
        f"- Events: {len(events)}",
        "",
        "## Recent events",
        "",
        "| phase | generated | eligible_after | hypothesis | family | reason | warning |",
        "|---|---:|:---:|---|---|---|---|",
    ]
    for event in events[-25:]:
        lines.append(
            "| {phase} | {generated} | {eligible} | {hypothesis} | {family} | {reason} | {warning} |".format(
                phase=event.get("phase", ""),
                generated=event.get("generated", 0),
                eligible="yes" if event.get("eligible_after_generation") else "no",
                hypothesis=event.get("eligible_hypothesis_id") or "",
                family=event.get("eligible_family") or "",
                reason=str(event.get("reason") or event.get("after_reason") or "").replace("|", "/"),
                warning=event.get("warning", ""),
            )
        )
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"report": str(out), "events": len(events)}
