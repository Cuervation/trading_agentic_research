"""Bibliography gap report for autonomous research.

This report answers: why did the literature/paper fallback generate 0 work?
It classifies every paper-derived idea as generated, duplicate/id-existing,
duplicate-signature, missing features, or potentially selectable.

Outputs:
- state/bibliography_gap_report.json
- reports/bibliography_gap_report.md
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.research.autonomous_hypothesis_factory import (
    existing_ids,
    existing_override_sigs,
    read_json,
    read_jsonl,
    real_override_signature,
)
from scripts.research.literature_hypothesis_miner import (
    all_literature_ideas,
    available_weekly_features,
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: str | Path, payload: Any) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def _missing_task_key(row: dict[str, Any]) -> str:
    return "|".join([
        str(row.get("source_id") or ""),
        str(row.get("paper_title") or ""),
        str(row.get("candidate_suffix") or ""),
        ",".join(sorted(str(x) for x in row.get("missing_features", []) or [])),
    ])


def _status_for_idea(
    *,
    idea: Any,
    parent_run_id: str,
    ids: set[str],
    sigs: set[str],
    features: set[str],
) -> tuple[str, dict[str, Any]]:
    hypothesis_id = f"HYP_LIT_{parent_run_id}_{idea.suffix}"
    missing = sorted(set(idea.required_features).difference(features))
    overrides = dict(idea.overrides)
    overrides["strategy_id"] = hypothesis_id
    overrides.setdefault("strategy_family", idea.family)
    sig = real_override_signature(overrides)

    if hypothesis_id in ids:
        return "id_exists", {"hypothesis_id": hypothesis_id, "signature": sig}
    if missing:
        return "missing_features", {"hypothesis_id": hypothesis_id, "missing_features": missing, "signature": sig}
    if sig in sigs:
        return "duplicate_signature", {"hypothesis_id": hypothesis_id, "signature": sig}
    return "candidate_available", {"hypothesis_id": hypothesis_id, "signature": sig}


def build_bibliography_gap_report(
    *,
    parent_strategy_config_path: str | Path = "configs/generated/HYP_AUTO_TIME_SERIES_MOMENTUM_SEED.json",
    hypothesis_bank_path: str | Path = "bibliography/hypothesis_bank.jsonl",
    paper_ideas_path: str | Path = "bibliography/paper_ideas.jsonl",
    state_dir: str | Path = "state",
    reports_dir: str | Path = "reports",
) -> dict[str, Any]:
    parent = read_json(parent_strategy_config_path, {}) or {}
    bank = read_jsonl(hypothesis_bank_path)
    ids = existing_ids(bank)
    sigs = existing_override_sigs(bank)
    features = available_weekly_features(state_dir)
    current = read_json(Path(state_dir) / "current_parent.json", {}) or {}
    parent_run_id = str(current.get("current_parent_run_id") or "PARENT")
    ideas = all_literature_ideas(parent, paper_ideas_path)
    missing_tasks = read_jsonl(Path(state_dir) / "missing_feature_tasks.jsonl")
    missing_task_keys = {_missing_task_key(row) for row in missing_tasks}

    rows: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    by_family: dict[str, Counter[str]] = defaultdict(Counter)
    missing_feature_counts: Counter[str] = Counter()

    for idea in ideas:
        status, detail = _status_for_idea(
            idea=idea,
            parent_run_id=parent_run_id,
            ids=ids,
            sigs=sigs,
            features=features,
        )
        counts[status] += 1
        by_family[idea.family][status] += 1
        for feature in detail.get("missing_features", []) or []:
            missing_feature_counts[feature] += 1
        rows.append({
            "status": status,
            "family": idea.family,
            "axis": idea.axis,
            "source_id": idea.source_id,
            "paper_title": idea.paper_title,
            "suffix": idea.suffix,
            "required_features": list(idea.required_features),
            "missing_features": detail.get("missing_features", []),
            "hypothesis_id": detail.get("hypothesis_id"),
            "claim": idea.claim,
        })

    payload = {
        "generated_at": now_iso(),
        "parent_run_id": parent_run_id,
        "parent_strategy_config": str(parent_strategy_config_path),
        "paper_ideas_path": str(paper_ideas_path),
        "hypothesis_bank_path": str(hypothesis_bank_path),
        "available_feature_count": len(features),
        "paper_idea_count": len(ideas),
        "status_counts": dict(counts),
        "family_status_counts": {family: dict(counter) for family, counter in sorted(by_family.items())},
        "top_missing_features": dict(missing_feature_counts.most_common(30)),
        "missing_feature_task_count": len(missing_tasks),
        "missing_feature_task_unique_count": len(missing_task_keys),
        "candidate_available_ids": [row["hypothesis_id"] for row in rows if row["status"] == "candidate_available"],
        "rows": rows,
    }

    state_out = Path(state_dir) / "bibliography_gap_report.json"
    report_out = Path(reports_dir) / "bibliography_gap_report.md"
    write_json(state_out, payload)
    write_bibliography_gap_markdown(payload, report_out)
    payload["state_output"] = str(state_out)
    payload["report_output"] = str(report_out)
    return payload


def write_bibliography_gap_markdown(payload: dict[str, Any], path: str | Path) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Bibliography / Paper Gap Report",
        "",
        f"- Generated at: `{payload.get('generated_at')}`",
        f"- Parent run: `{payload.get('parent_run_id')}`",
        f"- Paper ideas classified: **{payload.get('paper_idea_count', 0)}**",
        f"- Available weekly features: **{payload.get('available_feature_count', 0)}**",
        "",
        "## Status counts",
        "",
        "| status | count |",
        "|---|---:|",
    ]
    for status, count in sorted((payload.get("status_counts") or {}).items()):
        lines.append(f"| {status} | {count} |")

    lines.extend(["", "## Family x status", "", "| family | status | count |", "|---|---|---:|"])
    for family, counter in sorted((payload.get("family_status_counts") or {}).items()):
        for status, count in sorted(counter.items()):
            lines.append(f"| {family} | {status} | {count} |")

    lines.extend(["", "## Top missing features", "", "| feature | count |", "|---|---:|"])
    for feature, count in (payload.get("top_missing_features") or {}).items():
        lines.append(f"| {feature} | {count} |")

    available = payload.get("candidate_available_ids") or []
    lines.extend(["", "## Candidate-available paper ideas", ""])
    if available:
        for hid in available[:50]:
            lines.append(f"- `{hid}`")
    else:
        lines.append("No immediately available paper ideas. Check duplicate signatures and missing features above.")

    lines.extend(["", "## Blocked / missing rows", "", "| status | family | suffix | missing_features | hypothesis_id |", "|---|---|---|---|---|"])
    for row in (payload.get("rows") or [])[:120]:
        if row.get("status") == "candidate_available":
            continue
        missing = ", ".join(row.get("missing_features") or [])
        lines.append(f"| {row.get('status')} | {row.get('family')} | {row.get('suffix')} | {missing} | `{row.get('hypothesis_id')}` |")

    p.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    p = argparse.ArgumentParser(description="Build bibliography/paper gap report.")
    p.add_argument("--parent-strategy-config", default="configs/generated/HYP_AUTO_TIME_SERIES_MOMENTUM_SEED.json")
    p.add_argument("--hypothesis-bank", default="bibliography/hypothesis_bank.jsonl")
    p.add_argument("--paper-ideas", default="bibliography/paper_ideas.jsonl")
    p.add_argument("--state-dir", default="state")
    p.add_argument("--reports-dir", default="reports")
    args = p.parse_args()
    print(json.dumps(build_bibliography_gap_report(
        parent_strategy_config_path=args.parent_strategy_config,
        hypothesis_bank_path=args.hypothesis_bank,
        paper_ideas_path=args.paper_ideas,
        state_dir=args.state_dir,
        reports_dir=args.reports_dir,
    ), indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
