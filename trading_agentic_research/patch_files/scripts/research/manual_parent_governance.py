"""Repair/enforce manual parent governance.

The autonomous loop may discover a better champion, but this project requires
manual approval before moving the official current parent. This module writes a
parent governance lock and repairs state/current_parent.json so future batches
continue comparing/refining against the approved parent while keeping the best
candidate under review.
"""
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

from scripts.research.parent_state import resolve_strategy_config_path, snapshot_by_run_id
try:
    from scripts.research.research_ledger import run_summary
except Exception:  # pragma: no cover - defensive for partial installs
    run_summary = None

PARENT_LOCK_FILE = "parent_governance_lock.json"
CHAMPION_FILE = "champion_runs.json"
CURRENT_PARENT_FILE = "current_parent.json"


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


def _snapshot_from_run_folder(runs_dir: str | Path, run_id: str) -> dict[str, Any] | None:
    if run_summary is None:
        return None
    run_dir = Path(runs_dir) / run_id
    if not run_dir.exists():
        return None
    try:
        summary = run_summary(run_dir)
    except Exception:
        return None
    return {
        "run_id": run_id,
        "strategy_id": summary.get("strategy_id"),
        "hypothesis_id": summary.get("hypothesis_id") or summary.get("strategy_id"),
        "strategy_cagr_pct": summary.get("strategy_cagr_pct"),
        "strategy_max_drawdown_pct": summary.get("strategy_max_drawdown_pct"),
        "months_beating_spy": summary.get("months_beating_spy"),
        "months_losing_to_spy": summary.get("months_losing_to_spy"),
        "years_beating_spy": summary.get("years_beating_spy"),
        "years_losing_to_spy": summary.get("years_losing_to_spy"),
        "trades": summary.get("trades"),
        "updated_at": now_iso(),
    }


def _choose_pending_candidate(champion: dict[str, Any], official_parent: str, explicit_pending: str | None = None) -> str | None:
    if explicit_pending and str(explicit_pending) != str(official_parent):
        return str(explicit_pending)
    for key in ("pending_parent_candidate_run_id", "best_champion_run_id", "baseline_candidate_run_id"):
        value = champion.get(key)
        if value and str(value) != str(official_parent):
            return str(value)
    for bucket in ("promotion_candidates", "champion_runs", "secondary_candidates"):
        for row in champion.get(bucket, []) or []:
            rid = row.get("run_id")
            if rid and str(rid) != str(official_parent):
                return str(rid)
    return None


def enforce_manual_parent_governance(
    *,
    state_dir: str | Path = "state",
    strategy_registry_path: str | Path = "configs/strategy_registry.json",
    official_parent: str | None = None,
    pending_parent_candidate: str | None = None,
    runs_dir: str | Path = "runs",
    repo_root: str | Path = ROOT,
) -> dict[str, Any]:
    root = Path(repo_root)
    state_path = root / state_dir
    champion_path = state_path / CHAMPION_FILE
    current_parent_path = state_path / CURRENT_PARENT_FILE
    lock_path = state_path / PARENT_LOCK_FILE

    champion = read_json(champion_path, {}) or {}
    existing_lock = read_json(lock_path, {}) or {}
    official = official_parent or existing_lock.get("official_parent_run_id") or champion.get("official_parent_run_id") or champion.get("current_parent_run_id")
    if not official:
        return {
            "status": "skipped",
            "reason": "missing_official_parent",
            "current_parent_path": str(current_parent_path),
        }
    official = str(official)

    snapshot = snapshot_by_run_id(champion, official) or _snapshot_from_run_folder(root / runs_dir, official)
    if not snapshot:
        return {
            "status": "blocked",
            "reason": "official_parent_snapshot_missing",
            "official_parent": official,
            "current_parent_path": str(current_parent_path),
        }

    strategy_id = snapshot.get("strategy_id")
    hypothesis_id = snapshot.get("hypothesis_id") or strategy_id
    config_path = resolve_strategy_config_path(
        strategy_id=strategy_id,
        hypothesis_id=hypothesis_id,
        strategy_registry_path=strategy_registry_path,
        generated_configs_dir="configs/generated",
        repo_root=root,
    )
    if not config_path:
        return {
            "status": "blocked",
            "reason": "official_parent_config_missing",
            "official_parent": official,
            "strategy_id": strategy_id,
            "hypothesis_id": hypothesis_id,
            "current_parent_path": str(current_parent_path),
        }

    pending = _choose_pending_candidate(champion, official, pending_parent_candidate)

    champion.setdefault("champion_runs", [])
    if not snapshot_by_run_id(champion, official):
        champion["champion_runs"].append(snapshot)
    champion["official_parent_run_id"] = official
    champion["current_parent_run_id"] = official
    champion["current_parent_strategy_id"] = strategy_id
    champion["current_parent_hypothesis_id"] = hypothesis_id
    champion["current_parent_config_path"] = config_path
    champion["pending_parent_candidate_run_id"] = pending
    champion["parent_updates_require_manual_approval"] = True
    champion["updated_at"] = now_iso()
    write_json(champion_path, champion)

    lock = {
        "version": 1,
        "parent_updates_require_manual_approval": True,
        "official_parent_run_id": official,
        "pending_parent_candidate_run_id": pending,
        "reason": "manual_parent_governance_enforced",
        "updated_at": now_iso(),
    }
    write_json(lock_path, lock)

    payload = {
        "current_parent_run_id": official,
        "current_parent_strategy_id": strategy_id,
        "current_parent_hypothesis_id": hypothesis_id,
        "current_parent_config_path": config_path,
        "best_champion_run_id": champion.get("best_champion_run_id"),
        "baseline_candidate_run_id": champion.get("baseline_candidate_run_id"),
        "aggressive_champion_run_id": champion.get("aggressive_champion_run_id"),
        "pending_parent_candidate_run_id": pending,
        "parent_updates_require_manual_approval": True,
        "source": "manual_parent_governance",
        "updated_at": now_iso(),
    }
    write_json(current_parent_path, payload)
    return {
        "status": "ok",
        "official_parent": official,
        "pending_parent_candidate_run_id": pending,
        "current_parent_config_path": config_path,
        "current_parent_path": str(current_parent_path),
        "lock_path": str(lock_path),
    }


def main() -> int:
    p = argparse.ArgumentParser(description="Repair/enforce manual parent governance.")
    p.add_argument("--state-dir", default="state")
    p.add_argument("--strategy-registry", default="configs/strategy_registry.json")
    p.add_argument("--official-parent", default=None)
    p.add_argument("--pending-parent-candidate", default=None)
    p.add_argument("--runs-dir", default="runs")
    p.add_argument("--repo-root", default=str(ROOT))
    args = p.parse_args()
    print(json.dumps(enforce_manual_parent_governance(
        state_dir=args.state_dir,
        strategy_registry_path=args.strategy_registry,
        official_parent=args.official_parent,
        pending_parent_candidate=args.pending_parent_candidate,
        runs_dir=args.runs_dir,
        repo_root=args.repo_root,
    ), indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
