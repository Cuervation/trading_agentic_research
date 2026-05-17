"""Build a compact, auditable analysis package for one run."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    with path.open("r", encoding="utf-8-sig") as f:
        first = ""
        for line in f:
            if line.strip():
                first = line
                break
    if ";" in first:
        return pd.read_csv(path, sep=";", decimal=",")
    return pd.read_csv(path)


def _run_number(run_id: str) -> int | None:
    parts = run_id.split("_")
    if len(parts) != 2 or not parts[1].isdigit():
        return None
    return int(parts[1])


def _previous_run_id(run_id: str) -> str | None:
    n = _run_number(run_id)
    if n is None or n <= 1:
        return None
    return f"EXP_{n - 1:03d}"


def _trade_stats(trades: pd.DataFrame) -> dict:
    if trades.empty:
        return {"trades": 0}
    out = {"trades": int(len(trades))}
    if "net_return_pct" in trades.columns:
        out["avg_net_return_pct"] = float(pd.to_numeric(trades["net_return_pct"], errors="coerce").mean())
        out["median_net_return_pct"] = float(pd.to_numeric(trades["net_return_pct"], errors="coerce").median())
    if {"entry_date", "exit_date"}.issubset(trades.columns):
        entry = pd.to_datetime(trades["entry_date"], errors="coerce")
        exit_ = pd.to_datetime(trades["exit_date"], errors="coerce")
        holding_days = (exit_ - entry).dt.days
        out["avg_holding_days"] = float(holding_days.mean())
        out["median_holding_days"] = float(holding_days.median())
    return out


def _yearly_rows(yearly: pd.DataFrame) -> list[dict]:
    if yearly.empty:
        return []
    expected = ["year", "strategy_return_pct", "spy_return_pct", "excess_return_pct", "winner"]
    cols = [c for c in expected if c in yearly.columns]
    rows = []
    for _, row in yearly[cols].sort_values("year").iterrows():
        rows.append(
            {
                "year": int(row["year"]),
                "strategy_return_pct": float(row["strategy_return_pct"]),
                "spy_return_pct": float(row["spy_return_pct"]),
                "excess_return_pct": float(row["excess_return_pct"]),
                "winner": str(row["winner"]),
            }
        )
    return rows


def _changes_vs_previous(run_id: str, runs_dir: Path, metrics: dict, trades: pd.DataFrame) -> dict:
    previous = _previous_run_id(run_id)
    if previous is None:
        return {"previous_run_id": None}
    prev_dir = runs_dir / previous
    if not prev_dir.exists():
        return {"previous_run_id": previous, "available": False}

    prev_metrics = _read_json(prev_dir / "metrics.json")
    prev_trades = _read_csv(prev_dir / "trades.csv")

    cur_s = metrics.get("strategy", {})
    prev_s = prev_metrics.get("strategy", {})
    return {
        "previous_run_id": previous,
        "available": True,
        "strategy_cagr_delta_pct": float(cur_s.get("cagr_pct", 0.0)) - float(prev_s.get("cagr_pct", 0.0)),
        "strategy_max_drawdown_delta_pct": float(cur_s.get("max_drawdown_pct", 0.0)) - float(prev_s.get("max_drawdown_pct", 0.0)),
        "trades_delta": int(len(trades)) - int(len(prev_trades)),
    }


def _stop_context(run_id: str, state_dir: Path) -> dict:
    batch = _read_json(state_dir / "batch_state.json")
    if not batch:
        return {}
    history = batch.get("history", [])
    run_in_history = any(row.get("run_id") == run_id for row in history if isinstance(row, dict))
    return {
        "batch_status": batch.get("status"),
        "batch_stop_reason": batch.get("stop_reason"),
        "run_in_batch_history": run_in_history,
    }


def build_analysis(run_id: str, runs_dir: Path, state_dir: Path) -> dict:
    run_dir = runs_dir / run_id
    if not run_dir.exists():
        raise FileNotFoundError(f"Run folder not found: {run_dir}")

    metrics = _read_json(run_dir / "metrics.json")
    audit = _read_json(run_dir / "audit.json")
    yearly = _read_csv(run_dir / "yearly_strategy_stats.csv")
    if yearly.empty:
        yearly = _read_csv(run_dir / "spy_comparison_yearly.csv")
    trades = _read_csv(run_dir / "trades.csv")
    evidence = _read_json(state_dir / "evidence_memory.json")

    strategy_id = "unknown_strategy"
    if not yearly.empty and "strategy_id" in yearly.columns and yearly["strategy_id"].notna().any():
        strategy_id = str(yearly["strategy_id"].dropna().iloc[0])

    run_evidence = (evidence.get("runs") or {}).get(run_id, {})
    analysis = {
        "run_id": run_id,
        "strategy_id": strategy_id,
        "hypothesis_id": run_evidence.get("hypothesis_id"),
        "decision": audit.get("decision"),
        "totals": {
            "strategy": metrics.get("strategy", {}),
            "spy": metrics.get("spy", {}),
            "diagnostics": metrics.get("diagnostics", {}),
            "trade_stats": _trade_stats(trades),
        },
        "yearly": _yearly_rows(yearly),
        "changes_vs_previous_run": _changes_vs_previous(run_id, runs_dir, metrics, trades),
        "changes_vs_parent": audit.get("parent_comparison", {}),
        "stop_context": _stop_context(run_id, state_dir),
        "blocking_issues": audit.get("blocking_issues", []),
        "warnings": audit.get("warnings", []),
    }
    return analysis


def render_analysis_md(payload: dict) -> str:
    totals = payload.get("totals", {})
    strategy = totals.get("strategy", {})
    spy = totals.get("spy", {})
    trades = totals.get("trade_stats", {})
    lines = [
        f"# Analysis - {payload.get('run_id')}",
        f"- Strategy: `{payload.get('strategy_id')}`",
        f"- Hypothesis: `{payload.get('hypothesis_id')}`",
        f"- Decision: `{payload.get('decision')}`",
        "",
        "## Totals",
        f"- Strategy total return: {float(strategy.get('total_return_pct', 0.0)):.2f}%",
        f"- Strategy CAGR: {float(strategy.get('cagr_pct', 0.0)):.2f}%",
        f"- Strategy max drawdown: {float(strategy.get('max_drawdown_pct', 0.0)):.2f}%",
        f"- SPY total return: {float(spy.get('total_return_pct', 0.0)):.2f}%",
        f"- SPY CAGR: {float(spy.get('cagr_pct', 0.0)):.2f}%",
        f"- SPY max drawdown: {float(spy.get('max_drawdown_pct', 0.0)):.2f}%",
        f"- Trades: {int(trades.get('trades', 0))}",
    ]

    if payload.get("yearly"):
        lines.extend(
            [
                "",
                "## Year by year",
                "| year | strategy_return_pct | spy_return_pct | excess_return_pct | winner |",
                "|---:|---:|---:|---:|:---|",
            ]
        )
        for row in payload["yearly"]:
            lines.append(
                f"| {row['year']} | {row['strategy_return_pct']:.2f}% | {row['spy_return_pct']:.2f}% | {row['excess_return_pct']:.2f}% | {row['winner']} |"
            )

    lines.extend(
        [
            "",
            "## Changed vs previous run",
            f"- {json.dumps(payload.get('changes_vs_previous_run', {}), ensure_ascii=False)}",
            "",
            "## Changed vs parent",
            f"- {json.dumps(payload.get('changes_vs_parent', {}), ensure_ascii=False)}",
            "",
            "## Why it stopped / status",
            f"- {json.dumps(payload.get('stop_context', {}), ensure_ascii=False)}",
        ]
    )
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Analyze one run with yearly and delta context.")
    p.add_argument("--run-id", required=True)
    p.add_argument("--runs-dir", default="runs")
    p.add_argument("--state-dir", default="state")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    runs_dir = Path(args.runs_dir)
    state_dir = Path(args.state_dir)
    run_dir = runs_dir / args.run_id

    analysis = build_analysis(args.run_id, runs_dir, state_dir)
    (run_dir / "analysis.json").write_text(json.dumps(analysis, indent=2, ensure_ascii=False), encoding="utf-8")
    (run_dir / "analysis.md").write_text(render_analysis_md(analysis), encoding="utf-8")
    print(f"Analysis written: {run_dir / 'analysis.json'}")
    print(f"Analysis written: {run_dir / 'analysis.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

