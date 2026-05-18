"""Learning helpers for candidate-under-review refinement.

Tracks which candidate-under-review refinement sub-axes have already failed or
duplicated so the selector can switch intelligently instead of stopping or
retrying exhausted axes.

Important autonomy rule
-----------------------
Candidate-review learning is scoped to the active candidate. If the candidate
changes (for example EXP_044 -> EXP_054), stale exhausted axes from the previous
candidate must not silently block the new candidate. Stale HYP_REVIEW rows from
older candidates are also blocked by selector scope and cannot contaminate the
active candidate's learning.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LEARNING_FILE = "candidate_review_learning.json"
REPORT_FILE = "candidate_review_learning.md"


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


def load_candidate_review_learning(state_dir: str | Path = "state") -> dict[str, Any]:
    payload = read_json(Path(state_dir) / LEARNING_FILE, None)
    if not payload:
        payload = {
            "version": 1,
            "candidate_run_id": None,
            "official_parent_run_id": None,
            "attempts": [],
            "axis_stats": {},
            "exhausted_axes": [],
            "updated_at": now_iso(),
        }
    payload.setdefault("attempts", [])
    payload.setdefault("axis_stats", {})
    payload.setdefault("exhausted_axes", [])
    return payload


def save_candidate_review_learning(state_dir: str | Path, payload: dict[str, Any]) -> None:
    payload["updated_at"] = now_iso()
    write_json(Path(state_dir) / LEARNING_FILE, payload)


def candidate_review_run_id_from_hypothesis_id(hypothesis_id: str | None) -> str | None:
    """Extract EXP_###/AUTO_### from HYP_REVIEW_EXP_###_* ids."""
    if not hypothesis_id:
        return None
    match = re.match(r"^HYP_REVIEW_((?:EXP|AUTO)_\d+)_", str(hypothesis_id))
    return match.group(1) if match else None


def is_candidate_review_hypothesis(hypothesis: dict[str, Any] | str | None) -> bool:
    if isinstance(hypothesis, dict):
        hid = str(hypothesis.get("hypothesis_id") or "")
        family = str(hypothesis.get("family") or "")
    else:
        hid = str(hypothesis or "")
        family = ""
    return hid.startswith("HYP_REVIEW_") or family.startswith("candidate_under_review")


def candidate_review_scope_reason(hypothesis: dict[str, Any], *, state_dir: str | Path = "state") -> str | None:
    """Return a block reason when a candidate-review hypothesis is out of scope.

    Rules:
    - If no active candidate is under review, no HYP_REVIEW_* row is selectable.
    - If EXP_054 is active, only HYP_REVIEW_EXP_054_* rows are selectable.
    - Malformed HYP_REVIEW ids are blocked rather than guessed.
    """
    if not is_candidate_review_hypothesis(hypothesis):
        return None

    hid = str(hypothesis.get("hypothesis_id") or "")
    hypothesis_candidate = candidate_review_run_id_from_hypothesis_id(hid)
    candidate = read_json(Path(state_dir) / "candidate_under_review.json", {}) or {}
    active_candidate = candidate.get("candidate_run_id")
    status = candidate.get("status")

    if status != "active" or not active_candidate:
        return "no_active_candidate_under_review"
    if not hypothesis_candidate:
        return "malformed_candidate_review_hypothesis_id"
    if str(hypothesis_candidate) != str(active_candidate):
        return f"stale_candidate_review:{hypothesis_candidate}_not_{active_candidate}"
    return None


def reset_candidate_review_learning_for_candidate(
    *,
    state_dir: str | Path = "state",
    candidate_run_id: str | None,
    official_parent_run_id: str | None = None,
) -> dict[str, Any]:
    """Reset stale candidate-review learning when a new candidate is reviewed."""
    if not candidate_run_id:
        return {"reset": False, "reason": "missing_candidate_run_id"}

    learning = load_candidate_review_learning(state_dir)
    previous = learning.get("candidate_run_id")
    if previous and str(previous) == str(candidate_run_id):
        if official_parent_run_id and learning.get("official_parent_run_id") != official_parent_run_id:
            learning["official_parent_run_id"] = official_parent_run_id
            save_candidate_review_learning(state_dir, learning)
        return {"reset": False, "reason": "same_candidate", "candidate_run_id": str(candidate_run_id)}

    payload = {
        "version": 1,
        "candidate_run_id": str(candidate_run_id),
        "official_parent_run_id": official_parent_run_id,
        "attempts": [],
        "axis_stats": {},
        "exhausted_axes": [],
        "reason": "reset_for_new_candidate_under_review" if previous else "initialized_for_candidate_under_review",
        "previous_candidate_run_id": previous,
        "updated_at": now_iso(),
    }
    save_candidate_review_learning(state_dir, payload)
    return {
        "reset": bool(previous and str(previous) != str(candidate_run_id)),
        "initialized": not bool(previous),
        "reason": payload["reason"],
        "previous_candidate_run_id": previous,
        "candidate_run_id": str(candidate_run_id),
    }


def infer_candidate_review_axis(hypothesis: dict[str, Any] | str | None) -> str:
    if isinstance(hypothesis, dict):
        hid = str(hypothesis.get("hypothesis_id") or "")
        family = str(hypothesis.get("family") or "")
    else:
        hid = str(hypothesis or "")
        family = ""
    text = f"{hid} {family}".upper()
    if "TOPN" in text or "TOP_N" in text:
        return "top_n"
    if "EXIT" in text:
        return "exit"
    if "TRAILING" in text or "STOP" in text:
        return "trailing"
    if "REGIME" in text or "SPY" in text:
        return "regime"
    if "VOL" in text or "ATR" in text:
        return "volatility"
    return "unknown"


def candidate_review_priority(hypothesis: dict[str, Any]) -> int:
    """Lower is better. Prefer TOPN diversification before trailing/exit."""
    if not is_candidate_review_hypothesis(hypothesis):
        return 50
    axis = infer_candidate_review_axis(hypothesis)
    return {"top_n": 0, "regime": 1, "volatility": 1, "trailing": 2, "exit": 3, "unknown": 4}.get(axis, 4)


def is_candidate_review_hypothesis_blocked(hypothesis: dict[str, Any], *, state_dir: str | Path = "state") -> bool:
    if not is_candidate_review_hypothesis(hypothesis):
        return False
    axis = infer_candidate_review_axis(hypothesis)
    learning = load_candidate_review_learning(state_dir)
    return axis in set(learning.get("exhausted_axes", []) or [])


def _duplicate_of_from_audit(audit: dict[str, Any]) -> str | None:
    for key in ("duplicate_of_run_id", "global_duplicate_of", "duplicate_run_id"):
        if audit.get(key):
            return str(audit.get(key))
    dup = audit.get("duplicate_info")
    if isinstance(dup, dict):
        return dup.get("duplicate_of_run_id") or dup.get("run_id")
    return None


def update_candidate_review_learning_from_run(
    *,
    run_dir: str | Path,
    state_dir: str | Path = "state",
    audit: dict[str, Any] | None = None,
    rejection_threshold: int = 2,
) -> dict[str, Any]:
    run_path = Path(run_dir)
    audit = audit or read_json(run_path / "audit.json", {}) or {}
    manifest = read_json(run_path / "run_manifest.json", {}) or {}
    hypothesis_id = str(manifest.get("hypothesis_id") or manifest.get("strategy_id") or "")
    strategy = manifest.get("strategy") if isinstance(manifest.get("strategy"), dict) else {}
    if not hypothesis_id:
        hypothesis_id = str(strategy.get("hypothesis_id") or strategy.get("strategy_id") or audit.get("hypothesis_id") or "")
    family = str(manifest.get("family") or strategy.get("strategy_family") or "")
    if not hypothesis_id.startswith("HYP_REVIEW_") and not family.startswith("candidate_under_review"):
        return {"updated": False, "reason": "not_candidate_review_hypothesis", "hypothesis_id": hypothesis_id}

    candidate_state = read_json(Path(state_dir) / "candidate_under_review.json", {}) or {}
    active_candidate = candidate_state.get("candidate_run_id")
    hypothesis_candidate = candidate_review_run_id_from_hypothesis_id(hypothesis_id)

    if active_candidate and hypothesis_candidate and str(hypothesis_candidate) != str(active_candidate):
        return {
            "updated": False,
            "reason": "stale_candidate_review_hypothesis",
            "hypothesis_id": hypothesis_id,
            "hypothesis_candidate_run_id": hypothesis_candidate,
            "active_candidate_run_id": active_candidate,
        }
    if candidate_state.get("status") and candidate_state.get("status") != "active":
        return {
            "updated": False,
            "reason": "candidate_under_review_not_active",
            "hypothesis_id": hypothesis_id,
            "candidate_status": candidate_state.get("status"),
        }

    axis = infer_candidate_review_axis({"hypothesis_id": hypothesis_id, "family": family})
    decision = str(audit.get("decision") or "")
    duplicate_of = _duplicate_of_from_audit(audit)
    is_duplicate = bool(
        duplicate_of
        or audit.get("duplicate_result")
        or "duplicate_artifact" in (audit.get("flags") or [])
        or (audit.get("artifact_hashes") or {}).get("duplicate_artifact")
    )

    learning = load_candidate_review_learning(state_dir)
    if active_candidate and learning.get("candidate_run_id") and str(learning.get("candidate_run_id")) != str(active_candidate):
        reset_candidate_review_learning_for_candidate(
            state_dir=state_dir,
            candidate_run_id=str(active_candidate),
            official_parent_run_id=candidate_state.get("official_parent_run_id"),
        )
        learning = load_candidate_review_learning(state_dir)

    learning["candidate_run_id"] = active_candidate or hypothesis_candidate or learning.get("candidate_run_id")
    learning["official_parent_run_id"] = candidate_state.get("official_parent_run_id") or learning.get("official_parent_run_id")
    attempts = [row for row in learning.get("attempts", []) if row.get("run_id") != run_path.name]
    attempts.append({
        "run_id": run_path.name,
        "hypothesis_id": hypothesis_id,
        "family": family,
        "axis": axis,
        "decision": decision,
        "duplicate": is_duplicate,
        "duplicate_of_run_id": duplicate_of,
        "updated_at": now_iso(),
    })
    learning["attempts"] = attempts
    axis_rows = [row for row in attempts if row.get("axis") == axis]
    rejects = sum(1 for row in axis_rows if row.get("decision") == "rejected")
    duplicates = sum(1 for row in axis_rows if row.get("duplicate"))
    successes = sum(1 for row in axis_rows if row.get("decision") in {"accepted_for_followup", "promoted_candidate"})
    learning.setdefault("axis_stats", {})[axis] = {
        "attempts": len(axis_rows),
        "rejections": rejects,
        "duplicates": duplicates,
        "successes": successes,
        "last_run_id": run_path.name,
    }
    exhausted = set(learning.get("exhausted_axes", []) or [])
    if is_duplicate or rejects >= rejection_threshold:
        exhausted.add(axis)
    learning["exhausted_axes"] = sorted(exhausted)
    save_candidate_review_learning(state_dir, learning)
    return {"updated": True, "axis": axis, "decision": decision, "duplicate": is_duplicate, "exhausted_axes": learning["exhausted_axes"]}


def rebuild_candidate_review_learning(*, runs_dir: str | Path = "runs", state_dir: str | Path = "state") -> dict[str, Any]:
    write_json(Path(state_dir) / LEARNING_FILE, {
        "version": 1,
        "candidate_run_id": (read_json(Path(state_dir) / "candidate_under_review.json", {}) or {}).get("candidate_run_id"),
        "official_parent_run_id": (read_json(Path(state_dir) / "candidate_under_review.json", {}) or {}).get("official_parent_run_id"),
        "attempts": [],
        "axis_stats": {},
        "exhausted_axes": [],
        "updated_at": now_iso(),
    })
    count = 0
    skipped = 0
    for run_dir in sorted(Path(runs_dir).glob("*")):
        if run_dir.is_dir() and (run_dir / "audit.json").exists():
            result = update_candidate_review_learning_from_run(run_dir=run_dir, state_dir=state_dir)
            if result.get("updated"):
                count += 1
            else:
                skipped += 1
    return {"rebuilt": count, "skipped": skipped, "path": str(Path(state_dir) / LEARNING_FILE)}


def write_candidate_review_learning_report(*, state_dir: str | Path = "state", reports_dir: str | Path = "reports") -> dict[str, Any]:
    learning = load_candidate_review_learning(state_dir)
    out = Path(reports_dir) / REPORT_FILE
    out.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Candidate Review Learning",
        "",
        f"- Generated at: {now_iso()}",
        f"- Candidate under review: `{learning.get('candidate_run_id')}`",
        f"- Official parent: `{learning.get('official_parent_run_id')}`",
        f"- Exhausted axes: {', '.join(learning.get('exhausted_axes', []) or []) or 'none'}",
        "",
        "## Axis stats",
        "",
        "| axis | attempts | rejections | duplicates | successes | last_run |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for axis, stats in sorted((learning.get("axis_stats") or {}).items()):
        lines.append(f"| {axis} | {stats.get('attempts', 0)} | {stats.get('rejections', 0)} | {stats.get('duplicates', 0)} | {stats.get('successes', 0)} | {stats.get('last_run_id', '')} |")
    lines.extend(["", "## Recent attempts", ""])
    for row in learning.get("attempts", [])[-20:]:
        lines.append(f"- `{row.get('run_id')}` `{row.get('hypothesis_id')}` axis={row.get('axis')} decision={row.get('decision')} duplicate={row.get('duplicate')}")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"report": str(out), "exhausted_axes": learning.get("exhausted_axes", [])}


def main() -> int:
    import argparse
    p = argparse.ArgumentParser(description="Maintain candidate-under-review learning state.")
    p.add_argument("--runs-dir", default="runs")
    p.add_argument("--state-dir", default="state")
    p.add_argument("--reports-dir", default="reports")
    p.add_argument("--rebuild", action="store_true")
    p.add_argument("--report", action="store_true")
    args = p.parse_args()
    payload: dict[str, Any] = {}
    if args.rebuild:
        payload["rebuild"] = rebuild_candidate_review_learning(runs_dir=args.runs_dir, state_dir=args.state_dir)
    if args.report or not payload:
        payload["report"] = write_candidate_review_learning_report(state_dir=args.state_dir, reports_dir=args.reports_dir)
    print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
