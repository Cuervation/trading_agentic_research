"""Cooldown health report for autonomous research."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.research.cooldown_governance import read_json, summarize_cooldowns, write_json

CRITICAL_PREFIXES = ("paper_", "feature_space_", "candidate_under_review_")
CRITICAL_FAMILIES = {
    "paper_time_series_momentum",
    "paper_quality_momentum",
    "paper_regime_filter",
    "paper_trend_following",
    "paper_low_vol_momentum",
    "feature_space_momentum",
    "feature_space_trend_following",
    "feature_space_quality_momentum",
    "feature_space_composite_confirmation",
    "feature_space_composite_concentration",
    "feature_space_composite_exit",
    "feature_space_regime",
}


def _is_critical(family: str) -> bool:
    return family in CRITICAL_FAMILIES or family.startswith(CRITICAL_PREFIXES)


def cooldown_health_report(*, state_dir: str | Path = "state", reports_dir: str | Path = "reports") -> dict[str, Any]:
    payload = read_json(Path(state_dir) / "subspace_cooldowns.json", {"cooldowns": {}}) or {"cooldowns": {}}
    summary = summarize_cooldowns(payload)
    hard = set(summary.get("hard_active", []))
    soft = set(summary.get("soft_active", []))
    expired = set(summary.get("expired", []))

    critical_hard = sorted(f for f in hard if _is_critical(f))
    critical_soft = sorted(f for f in soft if _is_critical(f))
    legacy_soft = [
        row["family"]
        for row in summary.get("families", [])
        if row.get("status") == "soft_active" and row.get("legacy_without_until")
    ]

    recommendations = []
    if critical_hard:
        recommendations.append("Review critical hard cooldowns; these block autonomous generation/selection.")
    if legacy_soft:
        recommendations.append("Legacy cooldowns are advisory. If a family keeps producing duplicates, set severity='hard' with cooldown_until.")
    if expired:
        recommendations.append("Run normalize_cooldowns.py --prune-expired to remove expired cooldown entries.")

    out = {
        **summary,
        "critical_hard": critical_hard,
        "critical_soft": critical_soft,
        "legacy_soft": sorted(legacy_soft),
        "recommendations": recommendations,
    }

    reports = Path(reports_dir)
    reports.mkdir(parents=True, exist_ok=True)
    write_json(Path(state_dir) / "cooldown_health_report.json", out)
    write_json(reports / "cooldown_health_report.json", out)

    md = [
        "# Cooldown Health Report",
        "",
        f"Generated at: `{out['generated_at']}`",
        "",
        "## Summary",
        "",
        f"- Hard active: **{len(hard)}**",
        f"- Soft active: **{len(soft)}**",
        f"- Expired: **{len(expired)}**",
        f"- Critical hard: **{len(critical_hard)}**",
        f"- Critical soft: **{len(critical_soft)}**",
        "",
        "## Critical hard cooldowns",
        "",
    ]
    md.extend([f"- `{x}`" for x in critical_hard] or ["- none"])
    md.extend(["", "## Critical soft cooldowns", ""])
    md.extend([f"- `{x}`" for x in critical_soft] or ["- none"])
    md.extend(["", "## Legacy soft cooldowns", ""])
    md.extend([f"- `{x}`" for x in sorted(legacy_soft)] or ["- none"])
    md.extend(["", "## Recommendations", ""])
    md.extend([f"- {x}" for x in recommendations] or ["- none"])
    md.extend(["", "## All cooldowns", "", "| family | status | reason | until |", "|---|---|---|---|"])
    for row in summary.get("families", []):
        md.append(f"| `{row['family']}` | {row['status']} | {row.get('reason') or ''} | {row.get('cooldown_until') or ''} |")
    (reports / "cooldown_health_report.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    return out


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--state-dir", default="state")
    p.add_argument("--reports-dir", default="reports")
    args = p.parse_args()
    print(json.dumps(cooldown_health_report(state_dir=args.state_dir, reports_dir=args.reports_dir), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
