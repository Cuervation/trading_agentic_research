"""Normalize legacy subspace cooldowns."""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.research.cooldown_governance import cooldown_entry_status, read_json, write_json


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_cooldowns(
    *,
    state_dir: str | Path = "state",
    mode: str = "convert-legacy-to-soft",
    prune_expired: bool = False,
    backup: bool = True,
) -> dict[str, Any]:
    path = Path(state_dir) / "subspace_cooldowns.json"
    payload = read_json(path, {"version": 2, "cooldowns": {}}) or {"version": 2, "cooldowns": {}}
    cooldowns = payload.setdefault("cooldowns", {})
    if not isinstance(cooldowns, dict):
        raise ValueError("subspace_cooldowns.json has invalid 'cooldowns' payload")

    backup_path = None
    if backup and path.exists():
        backup_path = path.with_suffix(f".backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
        shutil.copy2(path, backup_path)

    converted, pruned, kept_hard, kept_soft = [], [], [], []
    now = datetime.now(timezone.utc)
    for family in list(cooldowns.keys()):
        entry = cooldowns.get(family)
        if not isinstance(entry, dict):
            cooldowns[family] = {
                "reason": "legacy_non_object_cooldown",
                "severity": "soft",
                "legacy_normalized_at": now_iso(),
                "legacy_original_value": entry,
            }
            converted.append(family)
            continue

        status = cooldown_entry_status(entry, now=now)
        if prune_expired and status == "expired":
            del cooldowns[family]
            pruned.append(family)
            continue

        has_until = bool(entry.get("cooldown_until"))
        has_kind = any(entry.get(k) for k in ("severity", "cooldown_type", "mode", "level", "type", "hard", "soft", "permanent"))
        if mode == "convert-legacy-to-soft" and not has_until and not has_kind:
            entry["severity"] = "soft"
            entry["legacy_permanent_converted"] = True
            entry["legacy_normalized_at"] = now_iso()
            entry.setdefault("selection_policy", "advisory_not_blocking")
            converted.append(family)
        elif status == "hard_active":
            kept_hard.append(family)
        elif status == "soft_active":
            kept_soft.append(family)

    payload["version"] = max(int(payload.get("version", 1) or 1), 2)
    payload["updated_at"] = now_iso()
    payload["normalization_policy"] = {
        "mode": mode,
        "legacy_without_until": "soft_not_blocking",
        "dated_or_explicit_hard": "hard_blocking",
    }
    write_json(path, payload)
    return {
        "status": "ok",
        "path": str(path),
        "backup_path": str(backup_path) if backup_path else None,
        "converted_to_soft": converted,
        "pruned_expired": pruned,
        "kept_hard": kept_hard,
        "kept_soft": kept_soft,
        "cooldown_count": len(cooldowns),
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--state-dir", default="state")
    p.add_argument("--mode", default="convert-legacy-to-soft", choices=["convert-legacy-to-soft"])
    p.add_argument("--prune-expired", action="store_true")
    p.add_argument("--no-backup", action="store_true")
    args = p.parse_args()
    print(json.dumps(normalize_cooldowns(
        state_dir=args.state_dir,
        mode=args.mode,
        prune_expired=bool(args.prune_expired),
        backup=not bool(args.no_backup),
    ), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
