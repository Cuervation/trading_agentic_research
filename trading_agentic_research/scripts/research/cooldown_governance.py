"""Central cooldown governance for autonomous research.

Single source of truth for cooldown semantics.

Rules:
- mode == "hard" blocks while active. If hard has no cooldown_until, it stays active until normalized/removed.
- mode == "soft" is advisory only and must not block selection or generation by itself.
- Legacy entries without mode and without cooldown_until are soft/advisory.
- Entries with future cooldown_until are hard-active unless explicitly marked mode: soft.
- Expired dated cooldowns do not block.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class CooldownStatus:
    family: str
    status: str
    blocks_selection: bool
    blocks_generation: bool
    reason: str
    mode: str | None = None
    cooldown_until: str | None = None


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


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


def parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except (TypeError, ValueError):
        return None


def _entry_flag(entry: dict[str, Any], *names: str) -> bool:
    return any(bool(entry.get(name)) for name in names)


def cooldown_entry_status(entry: Any, *, family: str = "", now: datetime | None = None) -> CooldownStatus:
    """Classify a cooldown entry as hard-active, soft, expired, or invalid."""
    now = now or now_utc()
    if not entry:
        return CooldownStatus(family=family, status="none", blocks_selection=False, blocks_generation=False, reason="no_cooldown")
    if not isinstance(entry, dict):
        return CooldownStatus(family=family, status="hard_active", blocks_selection=True, blocks_generation=True, reason="malformed_cooldown_entry", mode="hard")

    mode_raw = str(entry.get("mode") or entry.get("cooldown_type") or "").strip().lower()
    mode = mode_raw if mode_raw in {"hard", "soft", "advisory"} else None
    reason = str(entry.get("reason") or "family_cooldown")
    until_raw = entry.get("cooldown_until")
    until = parse_dt(until_raw)

    if mode in {"soft", "advisory"}:
        return CooldownStatus(
            family=family,
            status="soft",
            blocks_selection=False,
            blocks_generation=False,
            reason=reason,
            mode="soft",
            cooldown_until=str(until_raw) if until_raw else None,
        )

    explicit_hard = mode == "hard" or _entry_flag(entry, "hard", "blocks_selection", "blocks_generation", "force_block")
    if explicit_hard:
        if until_raw and until is not None and until <= now:
            return CooldownStatus(family=family, status="expired", blocks_selection=False, blocks_generation=False, reason=reason, mode="hard", cooldown_until=str(until_raw))
        return CooldownStatus(family=family, status="hard_active", blocks_selection=True, blocks_generation=True, reason=reason, mode="hard", cooldown_until=str(until_raw) if until_raw else None)

    if until_raw:
        if until is None:
            return CooldownStatus(family=family, status="hard_active", blocks_selection=True, blocks_generation=True, reason="invalid_cooldown_until", mode="hard", cooldown_until=str(until_raw))
        if until > now:
            return CooldownStatus(family=family, status="hard_active", blocks_selection=True, blocks_generation=True, reason=reason, mode="hard", cooldown_until=str(until_raw))
        return CooldownStatus(family=family, status="expired", blocks_selection=False, blocks_generation=False, reason=reason, mode=None, cooldown_until=str(until_raw))

    # Legacy repeated-failure entry. Advisory only.
    return CooldownStatus(family=family, status="soft_legacy", blocks_selection=False, blocks_generation=False, reason=reason, mode="soft")


def cooldown_map(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    cooldowns = payload.get("cooldowns", {})
    return cooldowns if isinstance(cooldowns, dict) else {}


def cooldown_status_for_family(cooldowns_payload: dict[str, Any] | None, family: str, *, now: datetime | None = None) -> CooldownStatus:
    entry = cooldown_map(cooldowns_payload).get(family)
    return cooldown_entry_status(entry, family=family, now=now)


def is_hard_cooldown_active(cooldowns_payload: dict[str, Any] | None, family: str, now: datetime | None = None) -> bool:
    return cooldown_status_for_family(cooldowns_payload, family, now=now).blocks_selection


def is_soft_cooldown(cooldowns_payload: dict[str, Any] | None, family: str, now: datetime | None = None) -> bool:
    return cooldown_status_for_family(cooldowns_payload, family, now=now).status in {"soft", "soft_legacy"}


def cooldown_reason(cooldowns_payload: dict[str, Any] | None, family: str) -> str | None:
    entry = cooldown_map(cooldowns_payload).get(family)
    if not entry:
        return None
    if isinstance(entry, dict):
        return str(entry.get("reason") or "family_cooldown")
    return "malformed_cooldown_entry"


def hard_active_cooldown_family_names(cooldowns_payload: dict[str, Any] | None, *, now: datetime | None = None) -> set[str]:
    """Return hard-active cooldown family names from an already-loaded cooldown payload."""
    out: set[str] = set()
    for family, entry in cooldown_map(cooldowns_payload).items():
        status = cooldown_entry_status(entry, family=str(family), now=now)
        if status.blocks_generation or status.blocks_selection:
            out.add(str(family))
    return out


def soft_cooldown_family_names(cooldowns_payload: dict[str, Any] | None, *, now: datetime | None = None) -> set[str]:
    out: set[str] = set()
    for family, entry in cooldown_map(cooldowns_payload).items():
        status = cooldown_entry_status(entry, family=str(family), now=now)
        if status.status in {"soft", "soft_legacy"}:
            out.add(str(family))
    return out


def hard_active_cooldown_families(state_dir: str | Path | dict[str, Any] = "state", *, now: datetime | None = None) -> set[str]:
    """Return hard-active cooldown families.

    Compatibility behavior:
    - if a cooldown payload/dict is passed, classify it directly;
    - if a path/state_dir is passed, read state_dir/subspace_cooldowns.json.

    This prevents old call sites from crashing while keeping the preferred
    state_dir-based API available.
    """
    if isinstance(state_dir, dict):
        return hard_active_cooldown_family_names(state_dir, now=now)
    return hard_active_cooldown_family_names(
        read_json(Path(state_dir) / "subspace_cooldowns.json", {}) or {},
        now=now,
    )


def cooldown_inventory(state_dir: str | Path = "state", *, now: datetime | None = None) -> dict[str, Any]:
    payload = read_json(Path(state_dir) / "subspace_cooldowns.json", {}) or {}
    rows = []
    counts: dict[str, int] = {}
    for family, entry in sorted(cooldown_map(payload).items()):
        status = cooldown_entry_status(entry, family=str(family), now=now)
        row = {
            "family": family,
            "status": status.status,
            "mode": status.mode,
            "reason": status.reason,
            "cooldown_until": status.cooldown_until,
            "blocks_selection": status.blocks_selection,
            "blocks_generation": status.blocks_generation,
        }
        rows.append(row)
        counts[status.status] = counts.get(status.status, 0) + 1
    return {
        "version": payload.get("version"),
        "normalization_policy": payload.get("normalization_policy", {}),
        "counts": counts,
        "rows": rows,
        "hard_active_families": [row["family"] for row in rows if row["blocks_selection"] or row["blocks_generation"]],
        "soft_families": [row["family"] for row in rows if row["status"] in {"soft", "soft_legacy"}],
    }
