"""Normalize cooldown state for cooldown governance v2."""
from __future__ import annotations

import argparse
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


def normalize_cooldowns(*, state_dir: str | Path = "state", mode: str = "convert-legacy-to-soft") -> dict[str, Any]:
    path = Path(state_dir) / "subspace_cooldowns.json"
    payload = read_json(path, {}) or {}
    payload.setdefault("version", 2)
    cooldowns = payload.setdefault("cooldowns", {})
    if not isinstance(cooldowns, dict):
        cooldowns = {}
        payload["cooldowns"] = cooldowns

    changed = []
    unchanged = []
    for family, entry in list(cooldowns.items()):
        if not isinstance(entry, dict):
            cooldowns[family] = {
                "mode": "hard",
                "reason": "malformed_legacy_cooldown_entry",
                "original_entry": str(entry),
                "normalized_at": now_iso(),
            }
            changed.append({"family": family, "action": "malformed_to_hard"})
            continue

        status_before = cooldown_entry_status(entry, family=str(family))
        has_until = bool(entry.get("cooldown_until"))
        has_mode = bool(entry.get("mode") or entry.get("cooldown_type"))
        explicit_hard = bool(entry.get("hard") or entry.get("blocks_selection") or entry.get("blocks_generation") or entry.get("force_block"))

        if mode == "convert-legacy-to-soft" and not has_until and not has_mode and not explicit_hard:
            entry["mode"] = "soft"
            entry["legacy_without_until"] = True
            entry["blocks_selection"] = False
            entry["blocks_generation"] = False
            entry["normalized_at"] = now_iso()
            changed.append({"family": family, "action": "legacy_to_soft", "previous_status": status_before.status})
        else:
            unchanged.append({"family": family, "status": status_before.status})

    payload["version"] = 2
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
        "changed_count": len(changed),
        "unchanged_count": len(unchanged),
        "changed": changed,
        "unchanged_sample": unchanged[:20],
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--state-dir", default="state")
    p.add_argument("--mode", default="convert-legacy-to-soft", choices=["convert-legacy-to-soft"])
    args = p.parse_args()
    import json
    print(json.dumps(normalize_cooldowns(state_dir=args.state_dir, mode=args.mode), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
