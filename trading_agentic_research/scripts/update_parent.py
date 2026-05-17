"""Safely update current_parent.json from an audited candidate run."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def can_update_parent_from_audit(audit: dict) -> tuple[bool, list[str]]:
    """Return whether audit permits moving current parent."""
    reasons: list[str] = []
    if audit.get("can_promote_baseline") is True:
        reasons.append("Audit attempted automatic baseline promotion, which is forbidden.")
    if audit.get("can_move_parent") is not True:
        reasons.append("Audit does not allow moving parent.")
    if audit.get("decision") not in {"accepted_for_followup", "promoted_candidate"}:
        reasons.append(f"Audit decision cannot move parent: {audit.get('decision')}.")
    if audit.get("blocking_issues"):
        reasons.append("Audit has blocking issues.")
    return not reasons, reasons


def update_current_parent(
    *,
    state_dir: str | Path,
    run_id: str,
    strategy_id: str | None = None,
    audit: dict,
) -> dict:
    """Update state/current_parent.json only when audit explicitly allows it."""
    allowed, reasons = can_update_parent_from_audit(audit)
    if not allowed:
        return {
            "updated": False,
            "run_id": run_id,
            "reasons": reasons,
        }

    state_path = Path(state_dir)
    state_path.mkdir(parents=True, exist_ok=True)
    parent_path = state_path / "current_parent.json"
    if parent_path.exists():
        current = json.loads(parent_path.read_text(encoding="utf-8-sig"))
    else:
        current = {}

    previous_run_id = current.get("current_parent_run_id")
    resolved_strategy_id = strategy_id or current.get("current_parent_strategy_id")
    if not resolved_strategy_id:
        raise ValueError("strategy_id is required when current_parent.json has no current_parent_strategy_id.")

    updated = {
        **current,
        "current_parent_run_id": run_id,
        "current_parent_strategy_id": resolved_strategy_id,
        "previous_parent_run_id": previous_run_id,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "updated_from_audit": True,
        "reason": "Audit allowed parent move; baseline promotion remains manual.",
    }
    parent_path.write_text(json.dumps(updated, indent=2, ensure_ascii=False), encoding="utf-8")
    return {
        "updated": True,
        "run_id": run_id,
        "previous_parent_run_id": previous_run_id,
        "current_parent_path": str(parent_path),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Move current parent only if audit.json allows it.")
    parser.add_argument("--run-id", required=True, help="Candidate run id under runs/.")
    parser.add_argument("--runs-dir", default="runs", help="Base runs directory.")
    parser.add_argument("--state-dir", default="state", help="State directory.")
    parser.add_argument("--strategy-id", default=None, help="Strategy id to store as current parent.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    run_dir = Path(args.runs_dir) / args.run_id
    audit_path = run_dir / "audit.json"
    if not audit_path.exists():
        raise FileNotFoundError(f"Missing audit.json: {audit_path}")

    audit = json.loads(audit_path.read_text(encoding="utf-8-sig"))
    result = update_current_parent(
        state_dir=args.state_dir,
        run_id=args.run_id,
        strategy_id=args.strategy_id,
        audit=audit,
    )

    if result["updated"]:
        print(f"Parent updated to run: {args.run_id}")
        print(f"State file: {result['current_parent_path']}")
        return 0

    print(f"Parent not updated for run: {args.run_id}")
    for reason in result["reasons"]:
        print(f"- {reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
