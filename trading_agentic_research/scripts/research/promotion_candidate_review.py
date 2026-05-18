"""Generate a focused review for the current promotion/baseline candidate."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


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


def _metrics(runs_dir: str | Path, run_id: str | None) -> dict[str, Any]:
    if not run_id:
        return {}
    run_dir = Path(runs_dir) / run_id
    metrics = read_json(run_dir / "metrics.json", {}) or {}
    spy_summary = read_json(run_dir / "spy_comparison_summary.json", {}) or {}
    audit = read_json(run_dir / "audit.json", {}) or {}
    strategy = metrics.get("strategy", {}) if isinstance(metrics, dict) else {}
    return {
        "run_id": run_id,
        "cagr_pct": strategy.get("cagr_pct"),
        "total_return_pct": strategy.get("total_return_pct"),
        "max_drawdown_pct": strategy.get("max_drawdown_pct"),
        "months_beating_spy": spy_summary.get("months_beating_spy"),
        "months_losing_to_spy": spy_summary.get("months_losing_to_spy"),
        "years_beating_spy": spy_summary.get("years_beating_spy"),
        "years_losing_to_spy": spy_summary.get("years_losing_to_spy"),
        "decision": audit.get("decision"),
        "can_move_parent": audit.get("can_move_parent"),
        "can_promote_baseline": audit.get("can_promote_baseline"),
        "warnings": audit.get("warnings", []),
        "parent_comparison": audit.get("parent_comparison", {}),
    }


def _equity_drawdown(runs_dir: str | Path, run_id: str | None) -> dict[str, Any]:
    if not run_id:
        return {}
    path = Path(runs_dir) / run_id / "equity_curve.csv"
    if not path.exists():
        return {}
    try:
        eq = pd.read_csv(path, sep=";", decimal=",")
        eq["date"] = pd.to_datetime(eq["date"], errors="coerce")
        eq["peak"] = eq["equity"].cummax()
        eq["drawdown_pct"] = (eq["equity"] / eq["peak"] - 1.0) * 100
        worst = eq.loc[eq["drawdown_pct"].idxmin()]
        return {
            "final_equity": float(eq["equity"].iloc[-1]),
            "worst_drawdown_pct": float(worst["drawdown_pct"]),
            "worst_drawdown_date": str(worst["date"]),
        }
    except Exception as exc:
        return {"error": str(exc)}


def write_promotion_candidate_review(
    *,
    state_dir: str | Path = "state",
    runs_dir: str | Path = "runs",
    reports_dir: str | Path = "reports",
) -> dict[str, Any]:
    state = Path(state_dir)
    champions = read_json(state / "champion_runs.json", {}) or {}
    current_parent = read_json(state / "current_parent.json", {}) or {}
    parent_run_id = current_parent.get("current_parent_run_id") or champions.get("current_parent_run_id")
    candidate_run_id = champions.get("baseline_candidate_run_id")

    parent = _metrics(runs_dir, parent_run_id)
    candidate = _metrics(runs_dir, candidate_run_id)
    parent_dd = _equity_drawdown(runs_dir, parent_run_id)
    candidate_dd = _equity_drawdown(runs_dir, candidate_run_id)

    payload = {
        "generated_at": now_iso(),
        "official_parent_run_id": parent_run_id,
        "promotion_candidate_run_id": candidate_run_id,
        "parent": parent,
        "candidate": candidate,
        "parent_drawdown": parent_dd,
        "candidate_drawdown": candidate_dd,
        "recommendation": "manual_review_required" if candidate_run_id else "no_candidate",
    }

    if parent and candidate:
        cagr_delta = float(candidate.get("cagr_pct") or 0) - float(parent.get("cagr_pct") or 0)
        dd_delta = float(candidate.get("max_drawdown_pct") or 0) - float(parent.get("max_drawdown_pct") or 0)
        payload["deltas"] = {
            "cagr_delta_pct": cagr_delta,
            "drawdown_delta_pct": dd_delta,
            "months_beating_spy_delta": (candidate.get("months_beating_spy") or 0) - (parent.get("months_beating_spy") or 0),
            "years_losing_spy_delta": (candidate.get("years_losing_to_spy") or 0) - (parent.get("years_losing_to_spy") or 0),
        }
        payload["review_question"] = "Is the extra CAGR worth the drawdown degradation, or should we refine candidate_under_review first?"

    reports = Path(reports_dir)
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "promotion_candidate_review.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")

    md = [
        "# Promotion Candidate Review",
        "",
        f"Generated at: `{payload['generated_at']}`",
        f"Official parent: `{parent_run_id}`",
        f"Promotion candidate: `{candidate_run_id}`",
        "",
        "| metric | parent | candidate |",
        "|---|---:|---:|",
    ]
    for key in ["cagr_pct", "total_return_pct", "max_drawdown_pct", "months_beating_spy", "months_losing_to_spy", "years_beating_spy", "years_losing_to_spy"]:
        md.append(f"| `{key}` | {parent.get(key, '-')} | {candidate.get(key, '-')} |")
    md.extend(["", "## Drawdown", ""])
    md.append(f"- Parent worst DD: `{parent_dd.get('worst_drawdown_pct')}` on `{parent_dd.get('worst_drawdown_date')}`")
    md.append(f"- Candidate worst DD: `{candidate_dd.get('worst_drawdown_pct')}` on `{candidate_dd.get('worst_drawdown_date')}`")
    md.extend(["", "## Recommendation", "", payload["recommendation"], ""])
    if payload.get("review_question"):
        md.extend(["", "## Review question", "", payload["review_question"], ""])
    (reports / "promotion_candidate_review.md").write_text("\n".join(md), encoding="utf-8")
    return payload


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--state-dir", default="state")
    p.add_argument("--runs-dir", default="runs")
    p.add_argument("--reports-dir", default="reports")
    args = p.parse_args()
    print(json.dumps(write_promotion_candidate_review(state_dir=args.state_dir, runs_dir=args.runs_dir, reports_dir=args.reports_dir), indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
