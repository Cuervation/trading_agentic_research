"""Evaluate a completed run folder, write audit.json, and persist learning.

This replacement keeps the original behavior and adds:
- global duplicate detection via state/artifact_hash_index.json
- research_ledger.jsonl event per run
- champion/current-parent governance updates
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtester.validation import audit_run_folder
from scripts.update_evidence_memory import persist_learning_from_run
from scripts.research.artifact_index import (
    apply_duplicate_to_audit,
    find_duplicate_artifact,
    update_artifact_index,
)
from scripts.research.champion_governance import update_champion_state
from scripts.research.research_ledger import append_run_to_ledger


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit a completed strategy run.")
    parser.add_argument("--run-id", required=True, help="Run id under runs/, e.g. EXP_001 or AUTO_001.")
    parser.add_argument("--runs-dir", default="runs", help="Base runs directory.")
    parser.add_argument(
        "--parent-run-id",
        default=None,
        help="Optional current parent run id. If provided, candidate must also be compared against it.",
    )
    parser.add_argument("--min-trades", type=int, default=10, help="Minimum trades required for validation.")
    parser.add_argument(
        "--hypothesis-id",
        default="HYP_BASELINE_MOMENTUM_TREND_V1",
        help="Hypothesis id to link this run to.",
    )
    parser.add_argument(
        "--family",
        default="cross_sectional_momentum",
        help="Hypothesis family to update in learning memory.",
    )
    parser.add_argument("--state-dir", default="state", help="State directory for learning/evidence memories.")
    parser.add_argument(
        "--allow-parent-update",
        action="store_true",
        help="Allow clear best champion to update current_parent.json. Default is conservative/manual.",
    )
    return parser.parse_args()


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def main() -> int:
    args = parse_args()
    run_dir = Path(args.runs_dir) / args.run_id
    if not run_dir.exists() or not run_dir.is_dir():
        raise FileNotFoundError(f"Run folder not found: {run_dir}")

    parent_run_dir = Path(args.runs_dir) / args.parent_run_id if args.parent_run_id else None

    audit = audit_run_folder(run_dir, min_trades=args.min_trades, parent_run_dir=parent_run_dir)

    # Detect historical duplicates globally, not only parent/last_run.
    duplicate_info = find_duplicate_artifact(run_dir, args.state_dir)
    if duplicate_info.get("is_duplicate"):
        audit = apply_duplicate_to_audit(audit, duplicate_info)

    audit_path = run_dir / "audit.json"
    _write_json(audit_path, audit)

    # Persist original learning memory/evidence outputs.
    learning_result = persist_learning_from_run(
        run_dir=run_dir,
        state_dir=args.state_dir,
        run_id=args.run_id,
        hypothesis_id=args.hypothesis_id,
        family=args.family,
        audit=audit,
    )

    # Update artifact index after audit so the current run becomes known.
    index_result = update_artifact_index(run_dir, args.state_dir)

    # Update champion governance and research ledger.
    champion_decision = update_champion_state(
        run_dir=run_dir,
        state_dir=args.state_dir,
        audit=audit,
        duplicate_info=duplicate_info,
        allow_parent_move=bool(args.allow_parent_update),
    )
    ledger_event = append_run_to_ledger(
        run_dir=run_dir,
        state_dir=args.state_dir,
        audit=audit,
        duplicate_info=duplicate_info,
        champion_decision=champion_decision,
    )

    print(f"Audit completed: {args.run_id}")
    print(f"Decision: {audit['decision']}")
    if duplicate_info.get("is_duplicate"):
        print(f"Global duplicate: {duplicate_info.get('duplicate_of_run_id')}")
    if args.parent_run_id:
        print(f"Parent comparison: {args.parent_run_id}")
        print(f"Can move parent: {audit['can_move_parent']}")
    print(f"Audit file: {audit_path}")
    print(f"Learning event: {learning_result['learning_event']['learning_id']}")
    print(f"Artifact index updated: {index_result.get('index_path')}")
    print(f"Champion action: {champion_decision.get('champion_action')}")
    print(f"Ledger value: {ledger_event.get('value_delivered')}")
    print("Baseline promotion: blocked (manual review required)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
