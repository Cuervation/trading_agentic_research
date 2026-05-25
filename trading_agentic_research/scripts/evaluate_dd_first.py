"""Evaluate a completed run with drawdown-first rules."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtester.dd_first import append_dd_first_summary, evaluate_dd_first_run, find_latest_run_for_strategy


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Write DD_FIRST audit and reports/dd_first_summary.csv.")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--runs-dir", default="runs")
    parser.add_argument("--reports-dir", default="reports")
    parser.add_argument("--parent-run-id", default=None)
    parser.add_argument("--parent-strategy-id", default=None)
    parser.add_argument("--min-trades", type=int, default=50)
    parser.add_argument("--output", default=None)
    return parser.parse_args()


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _resolve_parent_run(args: argparse.Namespace, run_dir: Path) -> Path | None:
    if args.parent_run_id:
        parent = Path(args.runs_dir) / args.parent_run_id
        return parent if parent.exists() else None
    manifest_path = run_dir / "run_manifest.json"
    manifest = _read_json(manifest_path) if manifest_path.exists() else {}
    parent_strategy_id = args.parent_strategy_id or manifest.get("parent_strategy_id")
    if not parent_strategy_id:
        return None
    return find_latest_run_for_strategy(args.runs_dir, str(parent_strategy_id))


def main() -> int:
    args = parse_args()
    run_dir = Path(args.runs_dir) / args.run_id
    if not run_dir.exists():
        raise FileNotFoundError(f"Run folder not found: {run_dir}")

    parent_run = _resolve_parent_run(args, run_dir)
    audit = evaluate_dd_first_run(run_dir, parent_run_dir=parent_run, min_trades=args.min_trades)

    audit_path = run_dir / "audit.json"
    audit_path.write_text(json.dumps(audit, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    output_path = Path(args.output) if args.output else Path(args.reports_dir) / "dd_first_summary.csv"
    append_dd_first_summary(output_path, audit["dd_first"])

    print(f"DD_FIRST audit completed: {args.run_id}")
    print(f"Decision: {audit['dd_first_decision']}")
    print(f"Report: {output_path}")
    if parent_run is not None:
        print(f"Parent run: {parent_run.name}")
    print("Parent/baseline promotion: blocked by DD_FIRST mode")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
