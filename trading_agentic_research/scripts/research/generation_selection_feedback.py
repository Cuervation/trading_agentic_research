"""Generation -> selection feedback for autonomous research.

The hypothesis generators may append new rows to the hypothesis bank, but the
selector can still reject all of them because of cooldowns, consumed/rejected
ids, duplicate real override signatures, candidate-review scope, or memory
scores. This module diagnoses newly generated hypothesis ids with
selector-equivalent rules and records both JSON and Markdown feedback.
"""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.parameter_effect_memory import load_parameter_effect_memory
from scripts.score_hypothesis_against_memory import score_hypothesis_against_memory
from scripts.select_next_hypothesis import load_hypothesis_bank, read_json, read_jsonl
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


def write_json(path: str | Path, payload: Any) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def _repeat_blocked_hypothesis_ids(history: list[dict[str, Any]], max_repeats_per_hypothesis: int = 1) -> set[str]:
    counts = Counter(str(item.get("hypothesis_id")) for item in history if item.get("hypothesis_id"))
    return {hypothesis_id for hypothesis_id, count in counts.items() if count >= max_repeats_per_hypothesis}


def _blocked_override_signatures(bank: list[dict[str, Any]], blocked_ids: set[str]) -> set[str]:
    signatures: set[str] = set()
    for row in bank:
        hid = str(row.get("hypothesis_id") or "")
        overrides = row.get("strategy_overrides")
        if hid in blocked_ids and isinstance(overrides, dict) and overrides:
            signatures.add(real_override_signature(overrides))
    return signatures


def diagnose_generated_hypotheses(
    *,
    generated_ids: list[str] | set[str],
    hypothesis_bank: str | Path = "bibliography/hypothesis_bank.jsonl",
    state_dir: str | Path = "state",
    prefer_unseen: bool = True,
    max_repeats_per_hypothesis: int = 1,
    learning_memory: dict[str, Any] | None = None,
    cooldowns: dict[str, Any] | None = None,
    parameter_effect_memory: dict[str, Any] | None = None,
    current_parent: dict[str, Any] | None = None,
    rejected_ids: set[str] | None = None,
    accepted_ids: set[str] | None = None,
    consumed_ids: set[str] | None = None,
    repeat_blocked_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Return selector-equivalent diagnostics for newly generated hypotheses."""
    state_path = Path(state_dir)
    ids = [str(x) for x in generated_ids if x]
    unique_ids = list(dict.fromkeys(ids))
    bank = load_hypothesis_bank(hypothesis_bank)
    by_id = {str(row.get("hypothesis_id")): row for row in bank if row.get("hypothesis_id")}

    learning_memory = learning_memory if learning_memory is not None else (
        read_json(state_path / "learning_memory.json") if (state_path / "learning_memory.json").exists() else {}
    )
    cooldowns = cooldowns if cooldowns is not None else (
        read_json(state_path / "subspace_cooldowns.json") if (state_path / "subspace_cooldowns.json").exists() else {}
    )
    parameter_effect_memory = parameter_effect_memory if parameter_effect_memory is not None else load_parameter_effect_memory(
        state_path / "parameter_effect_memory.json"
    )
    current_parent = current_parent if current_parent is not None else (
        read_json(state_path / "current_parent.json") if (state_path / "current_parent.json").exists() else {}
    )
    rejected_ids = {str(x) for x in (rejected_ids if rejected_ids is not None else {row.get("hypothesis_id") for row in read_jsonl(state_path / "rejected_hypotheses.jsonl")}) if x}
    accepted_ids = {str(x) for x in (accepted_ids if accepted_ids is not None else {row.get("hypothesis_id") for row in read_jsonl(state_path / "accepted_hypotheses.jsonl")}) if x}
    consumed_ids = {str(x) for x in (consumed_ids if consumed_ids is not None else consumed_hypothesis_ids(state_path)) if x}
    if repeat_blocked_ids is None:
        batch_state = read_json(state_path / "batch_state.json") if (state_path / "batch_state.json").exists() else {}
        repeat_blocked_ids = _repeat_blocked_hypothesis_ids(batch_state.get("history", []) or [], max_repeats_per_hypothesis)
    repeat_blocked_ids = {str(x) for x in repeat_blocked_ids if x}

    signature_block_ids = set(rejected_ids).union(consumed_ids).union(repeat_blocked_ids)
    if prefer_unseen:
        signature_block_ids.update(accepted_ids)
    blocked_signatures = _blocked_override_signatures(bank, signature_block_ids)
    current_parent_hypothesis_id = str(
        current_parent.get("current_parent_hypothesis_id") or current_parent.get("current_parent_strategy_id") or ""
    ) or None

    selectable: list[str] = []
    blocked: list[dict[str, Any]] = []
    missing: list[str] = []

    for hid in unique_ids:
        row = by_id.get(hid)
        if not row:
            missing.append(hid)
            blocked.append({"hypothesis_id": hid, "reason": "missing_from_hypothesis_bank"})
            continue

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
        elif hid in repeat_blocked_ids:
            reason = "repeat_blocked"
        elif prefer_unseen and hid in accepted_ids:
            reason = "accepted_already"
        else:
            scope_reason = candidate_review_scope_reason(row, state_dir=state_path)
            if scope_reason:
                reason = f"candidate_review_scope:{scope_reason}"
            elif is_candidate_review_hypothesis_blocked(row, state_dir=state_path):
                reason = "candidate_review_axis_exhausted"

        overrides = row.get("strategy_overrides")
        if reason is None and isinstance(overrides, dict) and overrides and hid not in signature_block_ids:
            sig = real_override_signature(overrides)
            if sig in blocked_signatures:
                reason = "duplicate_signature_blocked"

        if reason is None:
            score = score_hypothesis_against_memory(row, learning_memory, cooldowns)
            if score.get("decision") == "rejected":
                reason = "selector_memory_rejected"

        if reason is None:
            selectable.append(hid)
        else:
            blocked.append({
                "hypothesis_id": hid,
                "family": row.get("family"),
                "axis": row.get("axis"),
                "reason": reason,
                "score": score or {},
            })

    reason_counts: dict[str, int] = {}
    for row in blocked:
        reason = str(row.get("reason") or "unknown")
        reason_counts[reason] = reason_counts.get(reason, 0) + 1

    return {
        "generated_ids": unique_ids,
        "selectable_ids": selectable,
        "blocked": blocked,
        "missing_ids": missing,
        "counts": {
            "generated": len(unique_ids),
            "selectable": len(selectable),
            "blocked": len(blocked),
            "missing": len(missing),
            "rejected": len(rejected_ids),
            "accepted": len(accepted_ids),
            "consumed": len(consumed_ids),
            "repeat_blocked": len(repeat_blocked_ids),
        },
        "reason_counts": reason_counts,
    }


def record_generation_selection_feedback(
    *,
    state_dir: str | Path = "state",
    reports_dir: str | Path = "reports",
    phase: str,
    generation_result: dict[str, Any],
    diagnostics: dict[str, Any],
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    state_path = Path(state_dir)
    payload = read_json(state_path / FEEDBACK_JSON) if (state_path / FEEDBACK_JSON).exists() else {"version": 1, "events": []}
    event = {
        "timestamp": now_iso(),
        "phase": phase,
        "generated": int(generation_result.get("generated", 0) or 0),
        "hypotheses": generation_result.get("hypotheses", []),
        "selectable_ids": diagnostics.get("selectable_ids", []),
        "blocked": diagnostics.get("blocked", []),
        "counts": diagnostics.get("counts", {}),
        "reason_counts": diagnostics.get("reason_counts", {}),
        "generation_result": generation_result,
        "context": context or {},
    }
    if event["generated"] > 0 and not event["selectable_ids"]:
        event["warning"] = "generated_but_none_selectable"
    payload.setdefault("events", []).append(event)
    payload["updated_at"] = now_iso()
    write_json(state_path / FEEDBACK_JSON, payload)
    write_generation_selection_feedback_report(state_dir=state_dir, reports_dir=reports_dir)
    return event


def write_generation_selection_feedback_report(*, state_dir: str | Path = "state", reports_dir: str | Path = "reports") -> dict[str, Any]:
    payload = read_json(Path(state_dir) / FEEDBACK_JSON) if (Path(state_dir) / FEEDBACK_JSON).exists() else {"events": []}
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
        "| phase | generated | selectable | top block reasons | warning |",
        "|---|---:|---:|---|---|",
    ]
    for event in events[-25:]:
        reasons = event.get("reason_counts", {}) or {}
        top = ", ".join(f"{k}:{v}" for k, v in sorted(reasons.items(), key=lambda kv: (-kv[1], kv[0]))[:4])
        lines.append(
            f"| {event.get('phase', '')} | {event.get('generated', 0)} | {len(event.get('selectable_ids', []) or [])} | {top} | {event.get('warning', '')} |"
        )

    if events:
        last = events[-1]
        lines.extend(["", "## Last blocked hypotheses", ""])
        for row in (last.get("blocked", []) or [])[:30]:
            lines.append(
                f"- `{row.get('hypothesis_id')}` family={row.get('family')} axis={row.get('axis')} reason={row.get('reason')}"
            )

    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"report": str(out), "events": len(events)}


def main() -> int:
    import argparse

    p = argparse.ArgumentParser(description="Diagnose why generated hypotheses are or are not selectable.")
    p.add_argument("--hypothesis-bank", default="bibliography/hypothesis_bank.jsonl")
    p.add_argument("--state-dir", default="state")
    p.add_argument("--reports-dir", default="reports")
    p.add_argument("--ids", nargs="*", default=[])
    p.add_argument("--record", action="store_true")
    args = p.parse_args()

    diagnostics = diagnose_generated_hypotheses(
        generated_ids=args.ids,
        hypothesis_bank=args.hypothesis_bank,
        state_dir=args.state_dir,
    )
    if args.record:
        record_generation_selection_feedback(
            state_dir=args.state_dir,
            reports_dir=args.reports_dir,
            phase="manual",
            generation_result={"generated": len(args.ids), "hypotheses": args.ids, "reason": "manual_diagnostics"},
            diagnostics=diagnostics,
        )
    print(json.dumps(diagnostics, indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
