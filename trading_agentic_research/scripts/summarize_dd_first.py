"""Summarize DD_FIRST audits across run folders."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtester.dd_first import row_from_audit_or_run, write_dd_first_summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate reports/dd_first_summary.csv from DD_FIRST run artifacts.")
    parser.add_argument("--runs-dir", default="runs")
    parser.add_argument("--output", default="reports/dd_first_summary.csv")
    parser.add_argument("--min-trades", type=int, default=50)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    runs_dir = Path(args.runs_dir)
    rows = []
    if runs_dir.exists():
        for run_dir in sorted([p for p in runs_dir.iterdir() if p.is_dir()]):
            if not (run_dir / "metrics.json").exists():
                continue
            audit_path = run_dir / "audit.json"
            if not audit_path.exists() and not (run_dir / "spy_comparison_summary.json").exists():
                continue
            try:
                row = row_from_audit_or_run(run_dir, min_trades=args.min_trades)
            except Exception as exc:
                print(f"Skipping {run_dir.name}: {exc}")
                continue
            if row.get("dd_first_decision") or row.get("strategy_id", "").startswith("HYP_DD_FIRST"):
                rows.append(row)
    write_dd_first_summary(args.output, rows)
    print(f"DD_FIRST summary written: {args.output} rows={len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
