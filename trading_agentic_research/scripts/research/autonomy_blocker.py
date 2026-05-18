"""Persist explicit autonomy blockers.

The autonomous loop should never fail silently or return success when it did not
run.  When an operational prerequisite is missing (data paths, parent config,
no hypotheses after fallback), write state/autonomy_blocker.json with the exact
reason and next action.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BLOCKER_FILE = "autonomy_blocker.json"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: str | Path, payload: Any) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def write_autonomy_blocker(
    *,
    state_dir: str | Path = "state",
    reason: str,
    status: str = "blocked",
    errors: list[str] | None = None,
    warnings: list[str] | None = None,
    next_action: str | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "status": status,
        "reason": reason,
        "errors": errors or [],
        "warnings": warnings or [],
        "next_action": next_action or "review_blocker_and_fix_prerequisite",
        "context": context or {},
        "updated_at": now_iso(),
    }
    write_json(Path(state_dir) / BLOCKER_FILE, payload)
    return payload


def clear_autonomy_blocker(*, state_dir: str | Path = "state", reason: str = "cleared") -> dict[str, Any]:
    payload = {
        "status": "clear",
        "reason": reason,
        "errors": [],
        "warnings": [],
        "next_action": "continue_autonomous_loop",
        "context": {},
        "updated_at": now_iso(),
    }
    write_json(Path(state_dir) / BLOCKER_FILE, payload)
    return payload


__all__ = ["write_autonomy_blocker", "clear_autonomy_blocker", "BLOCKER_FILE"]
