"""Run end-to-end V1 backtest and SPY comparison."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtester.data_loader import (
    load_daily_feature_store_folder,
    load_weekly_feature_store,
    validate_feature_store,
)
from backtester.execution import run_strategy_backtest
from backtester.metrics import summarize_performance
from backtester.spy_comparison import (
    build_spy_equity_curve,
    compare_equity_curves,
    compare_monthly,
    compare_yearly,
    summarize_spy_comparison,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run strategy backtest and compare against SPY.")
    parser.add_argument("--weekly-file", required=True, help="Path to weekly feature-store CSV.")
    parser.add_argument("--daily-folder", required=True, help="Folder with daily feature-store CSV files.")
    parser.add_argument("--strategy-config", required=True, help="Path to strategy config JSON.")
    parser.add_argument("--project-config", required=True, help="Path to project config JSON.")
    parser.add_argument("--run-id", required=True, help="Run identifier, e.g. EXP_001.")
    return parser.parse_args()


def load_json(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with p.open("r", encoding="utf-8-sig") as f:
        return json.load(f)


def ensure_valid_feature_store(df, label: str) -> None:
    report = validate_feature_store(df, required_columns=["date", "ticker", "close"], benchmark_ticker="SPY")
    if report["missing_required_columns"]:
        raise ValueError(
            f"{label} missing required columns: {report['missing_required_columns']}"
        )


def build_summary_markdown(
    run_id: str,
    strategy_id: str,
    strategy_metrics: dict,
    spy_metrics: dict,
    comparison_summary: dict,
    yearly_stats_df: pd.DataFrame,
    number_of_trades: int,
    warnings: list[str],
) -> str:
    period = f"{strategy_metrics.get('start_date')} -> {strategy_metrics.get('end_date')}"

    lines = [
        f"# Run Summary - {strategy_id}",
        "",
        f"- Run id: `{run_id}`",
        f"- Strategy: `{strategy_id}`",
        f"- Period: {period}",
        f"- Total return: strategy {strategy_metrics.get('total_return_pct', 0.0):.2f}% vs SPY {spy_metrics.get('total_return_pct', 0.0):.2f}%",
        f"- CAGR: strategy {strategy_metrics.get('cagr_pct', 0.0):.2f}% vs SPY {spy_metrics.get('cagr_pct', 0.0):.2f}%",
        f"- Max drawdown: strategy {strategy_metrics.get('max_drawdown_pct', 0.0):.2f}% vs SPY {spy_metrics.get('max_drawdown_pct', 0.0):.2f}%",
        f"- Months beating/losing SPY: {comparison_summary.get('months_beating_spy', 0)} / {comparison_summary.get('months_losing_to_spy', 0)}",
        f"- Years beating/losing SPY: {comparison_summary.get('years_beating_spy', 0)} / {comparison_summary.get('years_losing_to_spy', 0)}",
        f"- Trades: {number_of_trades}",
        f"- Recommendation hint: {comparison_summary.get('recommendation_hint', 'review')}",
        "",
        "## Yearly Strategy Stats",
    ]

    if yearly_stats_df.empty:
        lines.append("- none")
    else:
        lines.extend(
            [
                "| year | strategy_return_pct | spy_return_pct | excess_return_pct | winner |",
                "|---:|---:|---:|---:|:---|",
            ]
        )
        for _, row in yearly_stats_df.sort_values("year").iterrows():
            lines.append(
                "| {year} | {strategy:.2f}% | {spy:.2f}% | {excess:.2f}% | {winner} |".format(
                    year=int(row["year"]),
                    strategy=float(row["strategy_return_pct"]),
                    spy=float(row["spy_return_pct"]),
                    excess=float(row["excess_return_pct"]),
                    winner=str(row["winner"]),
                )
            )

    lines.extend(
        [
            "",
        "## Warnings",
        ]
    )

    if warnings:
        lines.extend([f"- {w}" for w in warnings])
    else:
        lines.append("- none")

    return "\n".join(lines) + "\n"


def build_yearly_strategy_stats(run_id: str, strategy_id: str, comparison_yearly: pd.DataFrame) -> pd.DataFrame:
    """Return yearly strategy-vs-SPY stats with run and strategy identifiers."""
    if comparison_yearly is None or comparison_yearly.empty:
        return pd.DataFrame(
            columns=[
                "run_id",
                "strategy_id",
                "year",
                "strategy_return_pct",
                "spy_return_pct",
                "excess_return_pct",
                "winner",
            ]
        )

    yearly = comparison_yearly.copy()
    yearly.insert(0, "strategy_id", strategy_id)
    yearly.insert(0, "run_id", run_id)
    return yearly[
        [
            "run_id",
            "strategy_id",
            "year",
            "strategy_return_pct",
            "spy_return_pct",
            "excess_return_pct",
            "winner",
        ]
    ]


def main() -> int:
    args = parse_args()

    strategy_config = load_json(args.strategy_config)
    project_config = load_json(args.project_config)

    weekly_df = load_weekly_feature_store(args.weekly_file)
    daily_df = load_daily_feature_store_folder(args.daily_folder)

    ensure_valid_feature_store(weekly_df, label="weekly feature store")
    ensure_valid_feature_store(daily_df, label="daily feature store")

    result = run_strategy_backtest(
        weekly_df=weekly_df,
        daily_df=daily_df,
        strategy_config=strategy_config,
        project_config=project_config,
    )

    equity_curve = result["equity_curve"]
    trades = result["trades"]
    diagnostics = result["diagnostics"]

    if equity_curve.empty:
        raise ValueError("Backtest produced empty equity curve; cannot continue.")

    strategy_metrics = summarize_performance(equity_curve)

    spy_equity = build_spy_equity_curve(
        daily_df=daily_df,
        start_date=strategy_metrics["start_date"],
        end_date=strategy_metrics["end_date"],
        initial_capital=float(project_config.get("initial_capital", 100000)),
        benchmark_ticker=str(project_config.get("benchmark_ticker", "SPY")),
    )

    spy_metrics = summarize_performance(spy_equity[["date", "equity"]])

    strategy_equity_for_cmp = equity_curve[["date", "equity"]]
    spy_equity_for_cmp = spy_equity[["date", "equity"]]

    comparison_daily = compare_equity_curves(strategy_equity_for_cmp, spy_equity_for_cmp)
    comparison_monthly = compare_monthly(strategy_equity_for_cmp, spy_equity_for_cmp)
    comparison_yearly = compare_yearly(strategy_equity_for_cmp, spy_equity_for_cmp)

    comparison_summary = summarize_spy_comparison(
        monthly_df=comparison_monthly,
        yearly_df=comparison_yearly,
        strategy_metrics=strategy_metrics,
        spy_metrics=spy_metrics,
    )

    run_dir = Path("runs") / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    equity_curve.to_csv(run_dir / "equity_curve.csv", index=False, sep=";", decimal=",")
    trades.to_csv(run_dir / "trades.csv", index=False, sep=";", decimal=",")

    metrics_payload = {
        "strategy": strategy_metrics,
        "spy": spy_metrics,
        "diagnostics": diagnostics,
        "costs": {
            "applied": True,
            "cost_per_side_pct": float(project_config.get("cost_per_side_pct", 0.24)),
        },
    }

    with (run_dir / "metrics.json").open("w", encoding="utf-8") as f:
        json.dump(metrics_payload, f, indent=2, default=str)

    comparison_daily.to_csv(run_dir / "spy_comparison_daily.csv", index=False, sep=";", decimal=",")
    comparison_monthly.to_csv(run_dir / "spy_comparison_monthly.csv", index=False, sep=";", decimal=",")
    comparison_yearly.to_csv(run_dir / "spy_comparison_yearly.csv", index=False, sep=";", decimal=",")
    yearly_stats = build_yearly_strategy_stats(
        run_id=args.run_id,
        strategy_id=str(strategy_config.get("strategy_id", "unknown_strategy")),
        comparison_yearly=comparison_yearly,
    )
    yearly_stats.to_csv(run_dir / "yearly_strategy_stats.csv", index=False, sep=";", decimal=",")

    with (run_dir / "spy_comparison_summary.json").open("w", encoding="utf-8") as f:
        json.dump(comparison_summary, f, indent=2, default=str)

    summary_md = build_summary_markdown(
        run_id=args.run_id,
        strategy_id=str(strategy_config.get("strategy_id", "unknown_strategy")),
        strategy_metrics=strategy_metrics,
        spy_metrics=spy_metrics,
        comparison_summary=comparison_summary,
        yearly_stats_df=yearly_stats,
        number_of_trades=int(len(trades)),
        warnings=list(diagnostics.get("warnings", [])),
    )
    (run_dir / "summary.md").write_text(summary_md, encoding="utf-8")

    print(f"Run completed: {args.run_id}")
    print(f"Output folder: {run_dir}")
    print(f"Rows -> equity: {len(equity_curve)}, trades: {len(trades)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
