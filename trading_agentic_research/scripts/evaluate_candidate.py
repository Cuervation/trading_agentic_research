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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit a completed strategy run.")
    parser.add_argument("--run-id", required=True, help="Run id under runs/, e.g. EXP_001.")
    parser.add_argument("--runs-dir", default="runs", help="Base runs directory.")
    parser.add_argument("--min-trades", type=int, default=10, help="Minimum trades required for validation.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    run_dir = Path(args.runs_dir) / args.run_id
    if not run_dir.exists() or not run_dir.is_dir():
        raise FileNotFoundError(f"Run folder not found: {run_dir}")

    audit = audit_run_folder(run_dir, min_trades=args.min_trades)
    audit_path = run_dir / "audit.json"
    with audit_path.open("w", encoding="utf-8") as f:
        json.dump(audit, f, indent=2, default=str)

    print(f"Audit completed: {args.run_id}")
    print(f"Decision: {audit['decision']}")
    print(f"Audit file: {audit_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
