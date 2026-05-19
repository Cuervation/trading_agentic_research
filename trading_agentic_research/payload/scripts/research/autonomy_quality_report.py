"""Autonomy-quality report for the research loop.

Strategy performance is not enough. The system must also measure whether the
agent is spending backtests efficiently, avoiding duplicates, learning from
rejections, and producing selectable non-stale hypotheses.
"""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


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


def read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    p = Path(path)
    if not p.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in p.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def _recent(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    return rows[-int(limit):] if rows else []


def build_autonomy_quality_report(*, state_dir: str | Path = "state", reports_dir: str | Path = "reports", lookback: int = 30) -> dict[str, Any]:
    state = Path(state_dir)
    ledger = read_jsonl(state / "research_ledger.jsonl")
    recent = _recent(ledger, lookback)
    batch = read_json(state / "batch_state.json", {}) or {}
    branch = read_json(state / "branch_exhaustion.json", {}) or {}
    effect_index = read_json(state / "strategy_effect_index.json", {}) or {}
    preflight = read_jsonl(state / "preflight_blocked_hypotheses.jsonl")

    values = Counter(str(row.get("value_delivered") or "unknown") for row in recent)
    decisions = Counter(str(row.get("decision") or "unknown") for row in recent)
    families = Counter(str(row.get("family") or "unknown") for row in recent)
    branch_counts = Counter(str(row.get("branch_key") or "unknown") for row in recent if row.get("branch_key"))

    duplicate_like = sum(values[k] for k in values if "duplicate" in k)
    useful_like = sum(values[k] for k in values if k in {"new_champion", "promotion_candidate", "secondary_candidate", "defensive_secondary_candidate", "aggressive_champion"})
    rejected_like = values.get("rejected_with_learning", 0)
    total = max(1, len(recent))

    exhausted = [k for k, v in (branch.get("branches", {}) or {}).items() if isinstance(v, dict) and v.get("status") == "exhausted"]
    payload = {
        "generated_at": now_iso(),
        "lookback": lookback,
        "events": len(recent),
        "batch_status": batch.get("status"),
        "batch_completed": batch.get("completed"),
        "batch_stop_reason": batch.get("stop_reason"),
        "preflight_blocked_total": len(preflight),
        "strategy_effect_signatures": len((effect_index.get("signatures") or {})),
        "value_counts": dict(values),
        "decision_counts": dict(decisions),
        "top_families": dict(families.most_common(10)),
        "top_branches": dict(branch_counts.most_common(10)),
        "duplicate_like_pct": round(100.0 * duplicate_like / total, 2),
        "useful_like_pct": round(100.0 * useful_like / total, 2),
        "rejected_with_learning_pct": round(100.0 * rejected_like / total, 2),
        "exhausted_branches": exhausted[:50],
        "recommendations": [],
    }

    recs: list[str] = payload["recommendations"]
    if payload["duplicate_like_pct"] >= 20:
        recs.append("High duplicate rate: strengthen pre-run strategy-effect guard and branch exhaustion.")
    if useful_like == 0 and len(recent) >= 10:
        recs.append("No useful candidates in recent window: switch mode from local refinement to new family/literature-driven exploration.")
    if exhausted:
        recs.append("Some branches are exhausted: generation should avoid those branches until cooldown expires.")
    if str(batch.get("stop_reason") or "").startswith("consecutive_rejections"):
        recs.append("Batch stopped on consecutive rejections: inspect top rejected families/branches before increasing max_recovery_cycles.")

    return payload


def write_autonomy_quality_report(*, state_dir: str | Path = "state", reports_dir: str | Path = "reports", lookback: int = 30) -> dict[str, Any]:
    payload = build_autonomy_quality_report(state_dir=state_dir, reports_dir=reports_dir, lookback=lookback)
    out_dir = Path(reports_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "autonomy_quality_report.json"
    md_path = out_dir / "autonomy_quality_report.md"
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")

    lines = [
        "# Autonomy Quality Report",
        "",
        f"- Generated at: {payload['generated_at']}",
        f"- Lookback events: {payload['events']}",
        f"- Batch status: {payload.get('batch_status')}",
        f"- Batch completed: {payload.get('batch_completed')}",
        f"- Stop reason: {payload.get('batch_stop_reason')}",
        f"- Preflight blocked total: {payload.get('preflight_blocked_total')}",
        f"- Strategy-effect signatures indexed: {payload.get('strategy_effect_signatures')}",
        f"- Duplicate-like pct: {payload.get('duplicate_like_pct')}%",
        f"- Useful-like pct: {payload.get('useful_like_pct')}%",
        f"- Rejected-with-learning pct: {payload.get('rejected_with_learning_pct')}%",
        "",
        "## Value counts",
        "",
    ]
    for k, v in payload.get("value_counts", {}).items():
        lines.append(f"- {k}: {v}")
    lines.extend(["", "## Top families", ""])
    for k, v in payload.get("top_families", {}).items():
        lines.append(f"- {k}: {v}")
    lines.extend(["", "## Top branches", ""])
    for k, v in payload.get("top_branches", {}).items():
        lines.append(f"- {k}: {v}")
    lines.extend(["", "## Exhausted branches", ""])
    for item in payload.get("exhausted_branches", [])[:25]:
        lines.append(f"- `{item}`")
    lines.extend(["", "## Recommendations", ""])
    if payload.get("recommendations"):
        for item in payload["recommendations"]:
            lines.append(f"- {item}")
    else:
        lines.append("- none")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"report": str(json_path), "markdown": str(md_path), "payload": payload}


def main() -> int:
    import argparse
    p = argparse.ArgumentParser(description="Write autonomy quality report.")
    p.add_argument("--state-dir", default="state")
    p.add_argument("--reports-dir", default="reports")
    p.add_argument("--lookback", type=int, default=30)
    args = p.parse_args()
    print(json.dumps(write_autonomy_quality_report(state_dir=args.state_dir, reports_dir=args.reports_dir, lookback=args.lookback), indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
