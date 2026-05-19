"""Cooldown health report for autonomous research."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.research.cooldown_governance import cooldown_inventory, write_json


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_cooldown_health_report(*, state_dir: str | Path = "state", reports_dir: str | Path = "reports") -> dict[str, Any]:
    inv = cooldown_inventory(state_dir)
    payload = {"generated_at": now_iso(), "state_dir": str(state_dir), **inv}
    reports = Path(reports_dir)
    reports.mkdir(parents=True, exist_ok=True)
    write_json(Path(state_dir) / "cooldown_health_report.json", payload)
    write_json(reports / "cooldown_health_report.json", payload)

    rows = payload.get("rows", [])
    md = [
        "# Cooldown Health Report",
        "",
        f"Generated at: `{payload['generated_at']}`",
        "",
        "## Summary",
        "",
    ]
    for k, v in sorted((payload.get("counts") or {}).items()):
        md.append(f"- **{k}**: {v}")
    md.extend(["", "## Hard-active cooldown families", ""])
    hard = payload.get("hard_active_families") or []
    md.extend([f"- `{x}`" for x in hard] if hard else ["- none"])
    md.extend(["", "## Soft/advisory cooldown families", ""])
    soft = payload.get("soft_families") or []
    md.extend([f"- `{x}`" for x in soft] if soft else ["- none"])
    md.extend([
        "",
        "## Details",
        "",
        "| family | status | mode | blocks selection | blocks generation | reason | until |",
        "|---|---|---|:---:|:---:|---|---|",
    ])
    for row in rows:
        md.append(
            f"| `{row['family']}` | {row['status']} | {row.get('mode') or ''} | "
            f"{str(row['blocks_selection']).lower()} | {str(row['blocks_generation']).lower()} | "
            f"{row.get('reason') or ''} | {row.get('cooldown_until') or ''} |"
        )
    (reports / "cooldown_health_report.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    return payload


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--state-dir", default="state")
    p.add_argument("--reports-dir", default="reports")
    args = p.parse_args()
    print(json.dumps(write_cooldown_health_report(state_dir=args.state_dir, reports_dir=args.reports_dir), indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
