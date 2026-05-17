"""Summarize run folders into a compact leaderboard."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize runs with key metrics and decisions.")
    parser.add_argument("--runs-dir", default="runs")
    parser.add_argument("--output", default="reports/runs_summary.csv")
    parser.add_argument("--yearly-output", default="reports/runs_yearly_summary.csv")
    return parser.parse_args()


def _safe_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8-sig"))


def build_runs_summary(runs_dir: Path) -> pd.DataFrame:
    rows: list[dict] = []
    for run_path in sorted(runs_dir.glob("EXP_*")):
        if not run_path.is_dir():
            continue
        metrics = _safe_json(run_path / "metrics.json")
        audit = _safe_json(run_path / "audit.json")
        spy = _safe_json(run_path / "spy_comparison_summary.json")

        strategy = metrics.get("strategy", {})
        rows.append(
            {
                "run_id": run_path.name,
                "decision": audit.get("decision", "pending"),
                "can_move_parent": audit.get("can_move_parent", False),
                "strategy_cagr_pct": strategy.get("cagr_pct"),
                "strategy_max_drawdown_pct": strategy.get("max_drawdown_pct"),
                "spy_cagr_pct": spy.get("spy_cagr_pct"),
                "excess_cagr_pct": spy.get("excess_cagr_pct"),
                "years_beating_spy": spy.get("years_beating_spy"),
                "years_losing_to_spy": spy.get("years_losing_to_spy"),
                "trades": metrics.get("diagnostics", {}).get("number_of_trades"),
            }
        )

    if not rows:
        return pd.DataFrame(
            columns=[
                "run_id",
                "decision",
                "can_move_parent",
                "strategy_cagr_pct",
                "strategy_max_drawdown_pct",
                "spy_cagr_pct",
                "excess_cagr_pct",
                "years_beating_spy",
                "years_losing_to_spy",
                "trades",
            ]
        )

    df = pd.DataFrame(rows)
    df = df.sort_values(by=["decision", "excess_cagr_pct"], ascending=[True, False], na_position="last")
    return df


def _safe_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    with path.open("r", encoding="utf-8-sig") as f:
        first_line = ""
        for line in f:
            if line.strip():
                first_line = line
                break
    if ";" in first_line:
        return pd.read_csv(path, sep=";", decimal=",")
    return pd.read_csv(path)


def build_yearly_runs_summary(runs_dir: Path) -> pd.DataFrame:
    ordered_columns = [
        "run_id",
        "strategy_id",
        "year",
        "strategy_return_pct",
        "spy_return_pct",
        "excess_return_pct",
        "winner",
    ]
    rows: list[pd.DataFrame] = []
    for run_path in sorted(runs_dir.glob("EXP_*")):
        if not run_path.is_dir():
            continue
        yearly_path = run_path / "yearly_strategy_stats.csv"
        yearly = _safe_csv(yearly_path)
        if yearly.empty:
            continue
        required = set(ordered_columns)
        if not required.issubset(yearly.columns):
            continue
        rows.append(yearly[ordered_columns].copy())

    if not rows:
        return pd.DataFrame(
            columns=ordered_columns
        )

    out = pd.concat(rows, ignore_index=True)
    return out.sort_values(by=["year", "run_id"], ascending=[True, True], na_position="last")


def main() -> int:
    args = parse_args()
    runs_dir = Path(args.runs_dir)
    output_path = Path(args.output)
    yearly_output_path = Path(args.yearly_output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    yearly_output_path.parent.mkdir(parents=True, exist_ok=True)

    summary = build_runs_summary(runs_dir)
    yearly_summary = build_yearly_runs_summary(runs_dir)
    summary.to_csv(output_path, index=False, sep=";", decimal=",")
    yearly_summary.to_csv(yearly_output_path, index=False, sep=";", decimal=",")

    print(f"Runs summarized: {len(summary)}")
    print(f"Output: {output_path}")
    print(f"Yearly rows: {len(yearly_summary)}")
    print(f"Yearly output: {yearly_output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
