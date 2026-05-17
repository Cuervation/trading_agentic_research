"""Rebuild SPY comparison artifacts from an existing run folder."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtester.spy_comparison import compare_monthly, compare_yearly, summarize_spy_comparison


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Missing file: {path}")
    with path.open("r", encoding="utf-8-sig") as f:
        first = ""
        for line in f:
            if line.strip():
                first = line
                break
    if ";" in first:
        return pd.read_csv(path, sep=";", decimal=",")
    return pd.read_csv(path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Recompute monthly/yearly SPY comparisons for a run.")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--runs-dir", default="runs")
    return parser.parse_args()


def rebuild_spy_outputs(run_dir: Path) -> dict:
    daily_cmp = _read_csv(run_dir / "spy_comparison_daily.csv")
    metrics = json.loads((run_dir / "metrics.json").read_text(encoding="utf-8-sig"))

    required = {"date", "strategy_equity", "spy_equity"}
    missing = required - set(daily_cmp.columns)
    if missing:
        raise ValueError(f"spy_comparison_daily.csv missing columns: {sorted(missing)}")

    strategy_equity = daily_cmp[["date", "strategy_equity"]].rename(columns={"strategy_equity": "equity"})
    spy_equity = daily_cmp[["date", "spy_equity"]].rename(columns={"spy_equity": "equity"})

    monthly = compare_monthly(strategy_equity, spy_equity)
    yearly = compare_yearly(strategy_equity, spy_equity)
    summary = summarize_spy_comparison(monthly, yearly, metrics.get("strategy", {}), metrics.get("spy", {}))

    monthly.to_csv(run_dir / "spy_comparison_monthly.csv", index=False, sep=";", decimal=",")
    yearly.to_csv(run_dir / "spy_comparison_yearly.csv", index=False, sep=";", decimal=",")
    (run_dir / "spy_comparison_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def main() -> int:
    args = parse_args()
    run_dir = Path(args.runs_dir) / args.run_id
    if not run_dir.exists():
        raise FileNotFoundError(f"Run folder not found: {run_dir}")
    summary = rebuild_spy_outputs(run_dir)
    print(f"SPY comparison rebuilt for {args.run_id}: {summary.get('recommendation_hint', 'review')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
