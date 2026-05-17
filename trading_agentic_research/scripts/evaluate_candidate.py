"""Evaluate a completed run folder and write audit.json."""

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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit a completed strategy run.")
    parser.add_argument("--run-id", required=True, help="Run id under runs/, e.g. EXP_001.")
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
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    run_dir = Path(args.runs_dir) / args.run_id
    if not run_dir.exists() or not run_dir.is_dir():
        raise FileNotFoundError(f"Run folder not found: {run_dir}")

    parent_run_dir = Path(args.runs_dir) / args.parent_run_id if args.parent_run_id else None
    audit = audit_run_folder(run_dir, min_trades=args.min_trades, parent_run_dir=parent_run_dir)
    audit_path = run_dir / "audit.json"
    with audit_path.open("w", encoding="utf-8") as f:
        json.dump(audit, f, indent=2, default=str)

    learning_result = persist_learning_from_run(
        run_dir=run_dir,
        state_dir=args.state_dir,
        run_id=args.run_id,
        hypothesis_id=args.hypothesis_id,
        family=args.family,
        audit=audit,
    )

    print(f"Audit completed: {args.run_id}")
    print(f"Decision: {audit['decision']}")
    if args.parent_run_id:
        print(f"Parent comparison: {args.parent_run_id}")
        print(f"Can move parent: {audit['can_move_parent']}")
    print(f"Audit file: {audit_path}")
    print(f"Learning event: {learning_result['learning_event']['learning_id']}")
    print("Baseline promotion: blocked (manual review required)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
