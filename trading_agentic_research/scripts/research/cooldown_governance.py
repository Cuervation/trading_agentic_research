"""Cooldown governance helpers for autonomous research.

v2 separates cooldowns into hard and soft:
- hard cooldown: blocks selector/generator while active;
- soft cooldown: advisory memory, does not block by itself;
- legacy entries without cooldown_until are soft by default.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HARD_VALUES = {"hard", "blocking", "block", "strict", "permanent"}
SOFT_VALUES = {"soft", "advisory", "warn", "warning", "legacy_soft"}


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


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


def load_cooldown_payload(source: str | Path | dict | None = None) -> dict[str, Any]:
    if source is None:
        return {"version": 2, "cooldowns": {}}
    if isinstance(source, dict):
        return source
    p = Path(source)
    if p.is_dir():
        p = p / "subspace_cooldowns.json"
    return read_json(p, {"version": 2, "cooldowns": {}}) or {"version": 2, "cooldowns": {}}


def cooldown_entry_status(entry: Any, *, now: datetime | None = None) -> str:
    """Classify one cooldown entry: hard_active, soft_active, expired, inactive."""
    if not entry:
        return "inactive"
    if not isinstance(entry, dict):
        return "soft_active"
    if entry.get("enabled") is False or entry.get("disabled") is True:
        return "inactive"

    raw_kind = (
        entry.get("severity")
        or entry.get("cooldown_type")
        or entry.get("mode")
        or entry.get("level")
        or entry.get("type")
    )
    kind = str(raw_kind or "").strip().lower()
    explicit_hard = bool(entry.get("hard") is True or entry.get("permanent") is True or kind in HARD_VALUES)
    explicit_soft = bool(entry.get("soft") is True or kind in SOFT_VALUES)

    until = parse_dt(entry.get("cooldown_until"))
    if until is not None:
        current = now or now_utc()
        if until <= current:
            return "expired"
        return "soft_active" if explicit_soft and not explicit_hard else "hard_active"

    if explicit_hard:
        return "hard_active"
    return "soft_active"


def cooldowns_map(payload_or_state: str | Path | dict | None) -> dict[str, Any]:
    payload = load_cooldown_payload(payload_or_state)
    cooldowns = payload.get("cooldowns", {}) if isinstance(payload, dict) else {}
    return cooldowns if isinstance(cooldowns, dict) else {}


def family_cooldown_status(payload_or_state: str | Path | dict | None, family: str, *, now: datetime | None = None) -> str:
    return cooldown_entry_status(cooldowns_map(payload_or_state).get(str(family)), now=now)


def is_hard_cooldown_active(payload_or_state: str | Path | dict | None, family: str, *, now: datetime | None = None) -> bool:
    return family_cooldown_status(payload_or_state, family, now=now) == "hard_active"


def is_soft_cooldown_active(payload_or_state: str | Path | dict | None, family: str, *, now: datetime | None = None) -> bool:
    return family_cooldown_status(payload_or_state, family, now=now) == "soft_active"


def cooldown_reason(payload_or_state: str | Path | dict | None, family: str) -> str | None:
    entry = cooldowns_map(payload_or_state).get(str(family))
    if not isinstance(entry, dict):
        return "family_cooldown" if entry else None
    return str(entry.get("reason") or "family_cooldown")


def hard_cooldown_families(payload_or_state: str | Path | dict | None, *, now: datetime | None = None) -> set[str]:
    return {str(f) for f, e in cooldowns_map(payload_or_state).items() if cooldown_entry_status(e, now=now) == "hard_active"}


def soft_cooldown_families(payload_or_state: str | Path | dict | None, *, now: datetime | None = None) -> set[str]:
    return {str(f) for f, e in cooldowns_map(payload_or_state).items() if cooldown_entry_status(e, now=now) == "soft_active"}


def expired_cooldown_families(payload_or_state: str | Path | dict | None, *, now: datetime | None = None) -> set[str]:
    return {str(f) for f, e in cooldowns_map(payload_or_state).items() if cooldown_entry_status(e, now=now) == "expired"}


def summarize_cooldowns(payload_or_state: str | Path | dict | None, *, now: datetime | None = None) -> dict[str, Any]:
    cooldowns = cooldowns_map(payload_or_state)
    rows = []
    counts = {"hard_active": 0, "soft_active": 0, "expired": 0, "inactive": 0}
    for family, entry in sorted(cooldowns.items()):
        status = cooldown_entry_status(entry, now=now)
        counts[status] = counts.get(status, 0) + 1
        rows.append({
            "family": family,
            "status": status,
            "reason": entry.get("reason") if isinstance(entry, dict) else None,
            "severity": entry.get("severity") if isinstance(entry, dict) else None,
            "cooldown_until": entry.get("cooldown_until") if isinstance(entry, dict) else None,
            "legacy_without_until": isinstance(entry, dict) and not entry.get("cooldown_until"),
        })
    return {
        "generated_at": now_utc().isoformat(),
        "counts": counts,
        "families": rows,
        "hard_active": [r["family"] for r in rows if r["status"] == "hard_active"],
        "soft_active": [r["family"] for r in rows if r["status"] == "soft_active"],
        "expired": [r["family"] for r in rows if r["status"] == "expired"],
    }
