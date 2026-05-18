"""Candidate-under-review state.

Keeps the official current parent unchanged while allowing the research loop to
focus follow-up hypotheses on a promotion candidate such as EXP_044.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


CANDIDATE_FILE = "candidate_under_review.json"


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


def write_json(path: str | Path, payload: Any) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def _resolve_repo_path(path: str | Path | None, repo_root: str | Path = ".") -> Path | None:
    if not path:
        return None
    p = Path(path)
    return p if p.is_absolute() else Path(repo_root) / p


def _run_metrics(runs_dir: str | Path, run_id: str) -> dict[str, Any]:
    run_dir = Path(runs_dir) / run_id
    metrics = read_json(run_dir / "metrics.json", {}) or {}
    spy_summary = read_json(run_dir / "spy_comparison_summary.json", {}) or {}
    audit = read_json(run_dir / "audit.json", {}) or {}
    manifest = read_json(run_dir / "run_manifest.json", {}) or {}
    strategy = metrics.get("strategy", {}) if isinstance(metrics, dict) else {}
    return {
        "run_id": run_id,
        "strategy_id": manifest.get("strategy_id"),
        "hypothesis_id": manifest.get("hypothesis_id") or manifest.get("strategy_id"),
        "strategy_config_path": manifest.get("strategy_config_path") or manifest.get("strategy_config"),
        "parent_run_id": manifest.get("parent_run_id") or audit.get("parent_comparison", {}).get("parent_run_id"),
        "decision": audit.get("decision"),
        "can_move_parent": audit.get("can_move_parent"),
        "cagr_pct": strategy.get("cagr_pct"),
        "max_drawdown_pct": strategy.get("max_drawdown_pct"),
        "total_return_pct": strategy.get("total_return_pct"),
        "months_beating_spy": spy_summary.get("months_beating_spy"),
        "months_losing_to_spy": spy_summary.get("months_losing_to_spy"),
        "years_beating_spy": spy_summary.get("years_beating_spy"),
        "years_losing_to_spy": spy_summary.get("years_losing_to_spy"),
    }


def refresh_candidate_under_review(
    *,
    state_dir: str | Path = "state",
    runs_dir: str | Path = "runs",
    repo_root: str | Path = ".",
) -> dict[str, Any]:
    state = Path(state_dir)
    champions = read_json(state / "champion_runs.json", {}) or {}
    candidate_run_id = champions.get("baseline_candidate_run_id")
    if not candidate_run_id:
        payload = {
            "status": "none",
            "reason": "no_baseline_candidate_run_id",
            "updated_at": now_iso(),
        }
        write_json(state / CANDIDATE_FILE, payload)
        return payload

    current_parent = read_json(state / "current_parent.json", {}) or {}
    snapshot = _run_metrics(runs_dir, str(candidate_run_id))
    config_path = snapshot.get("strategy_config_path")
    resolved_config = _resolve_repo_path(config_path, repo_root)
    if not resolved_config or not resolved_config.exists():
        payload = {
            "status": "blocked",
            "reason": "candidate_config_missing",
            "candidate_run_id": candidate_run_id,
            "strategy_config_path": config_path,
            "updated_at": now_iso(),
        }
        write_json(state / CANDIDATE_FILE, payload)
        return payload

    payload = {
        "status": "active",
        "updated_at": now_iso(),
        "candidate_run_id": candidate_run_id,
        "candidate_strategy_id": snapshot.get("strategy_id"),
        "candidate_hypothesis_id": snapshot.get("hypothesis_id"),
        "candidate_config_path": str(Path(config_path).as_posix()),
        "official_parent_run_id": current_parent.get("current_parent_run_id"),
        "official_parent_strategy_id": current_parent.get("current_parent_strategy_id"),
        "review_goal": "Preserve candidate CAGR/return benefits while reducing drawdown toward the official parent.",
        "metrics": snapshot,
    }
    write_json(state / CANDIDATE_FILE, payload)
    return payload


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--state-dir", default="state")
    p.add_argument("--runs-dir", default="runs")
    p.add_argument("--repo-root", default=".")
    args = p.parse_args()
    print(json.dumps(refresh_candidate_under_review(state_dir=args.state_dir, runs_dir=args.runs_dir, repo_root=args.repo_root), indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
