"""Write DD_FIRST exposure-refinement reports.

Reads reports/dd_first_summary.csv and emits a compact CSV/Markdown view for
fixed-exposure variants. This does not run backtests and does not touch parent
or baseline state.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


COLUMNS = [
    "run_id",
    "strategy_id",
    "exposure_pct",
    "cagr",
    "spy_cagr",
    "excess_cagr",
    "max_drawdown",
    "parent_max_drawdown",
    "drawdown_improvement_vs_parent_pct",
    "calmar",
    "parent_calmar",
    "years_beating_spy",
    "years_losing_to_spy",
    "months_beating_spy",
    "months_losing_to_spy",
    "trades",
    "decision",
    "value_delivered",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize DD_FIRST fixed exposure refinement.")
    parser.add_argument("--dd-first-summary", default="reports/dd_first_summary.csv")
    parser.add_argument("--reports-dir", default="reports")
    parser.add_argument("--state-dir", default="state")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    rows = load_exposure_rows(args.dd_first_summary)
    out_csv = Path(args.reports_dir) / "dd_first_exposure_refinement_summary.csv"
    out_md = Path(args.reports_dir) / "dd_first_exposure_refinement_summary.md"
    write_csv(out_csv, rows)
    write_markdown(out_md, rows)
    append_learning(args.state_dir)
    print(f"Exposure refinement reports written: rows={len(rows)}")
    return 0


def load_exposure_rows(summary_path: str | Path) -> list[dict[str, Any]]:
    path = Path(summary_path)
    if not path.exists():
        return []
    rows: dict[int, dict[str, Any]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        for raw in csv.DictReader(f, delimiter=";"):
            strategy_id = raw.get("strategy_id", "")
            match = re.search(r"EXPOSURE_(\d+)_V1", strategy_id)
            if not match:
                continue
            exposure = int(match.group(1))
            if exposure not in {50, 55, 60, 65, 70, 75, 85}:
                continue
            rows[exposure] = {
                "run_id": raw.get("run_id", ""),
                "strategy_id": strategy_id,
                "exposure_pct": exposure,
                "cagr": _num(raw.get("strategy_cagr_pct")),
                "spy_cagr": _num(raw.get("spy_cagr_pct")),
                "excess_cagr": _num(raw.get("excess_cagr_pct")),
                "max_drawdown": _num(raw.get("strategy_max_drawdown_pct")),
                "parent_max_drawdown": _num(raw.get("parent_max_drawdown_pct")),
                "drawdown_improvement_vs_parent_pct": _num(raw.get("drawdown_improvement_vs_parent_pct")),
                "calmar": _num(raw.get("calmar_ratio")),
                "parent_calmar": _num(raw.get("parent_calmar_ratio")),
                "years_beating_spy": _int(raw.get("years_beating_spy")),
                "years_losing_to_spy": _int(raw.get("years_losing_to_spy")),
                "months_beating_spy": _int(raw.get("months_beating_spy")),
                "months_losing_to_spy": _int(raw.get("months_losing_to_spy")),
                "trades": _int(raw.get("trades")),
                "decision": raw.get("dd_first_decision") or raw.get("decision", ""),
                "value_delivered": raw.get("value_delivered", ""),
            }
    return [rows[k] for k in sorted(rows)]


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS, delimiter=";")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _csv_value(row.get(key, "")) for key in COLUMNS})


def write_markdown(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    best_dd = sorted(rows, key=lambda r: abs(float(r["max_drawdown"])))[:3]
    best_calmar = sorted(rows, key=lambda r: float(r["calmar"]), reverse=True)[:3]
    best_balanced = sorted(rows, key=balanced_score, reverse=True)[:3]
    lines = [
        "# DD_FIRST Exposure Refinement Summary",
        "",
        "## Ranking 1 - Menor drawdown",
        *table(best_dd),
        "",
        "## Ranking 2 - Mejor Calmar",
        *table(best_calmar),
        "",
        "## Ranking 3 - Mejor balanceado",
        *table(best_balanced),
        "",
        "## Lectura",
        "- Defensive: priorizar menor drawdown con CAGR > SPY y muestra suficiente.",
        "- Balanced: priorizar Calmar, drawdown materialmente menor que parent y anos ganados vs SPY.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def table(rows: list[dict[str, Any]]) -> list[str]:
    out = [
        "| exposure | CAGR | SPY CAGR | excess | max DD | DD improvement | Calmar | years W/L | trades | decision |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in rows:
        out.append(
            f"| {row['exposure_pct']} | {row['cagr']} | {row['spy_cagr']} | {row['excess_cagr']} | "
            f"{row['max_drawdown']} | {row['drawdown_improvement_vs_parent_pct']} | {row['calmar']} | "
            f"{row['years_beating_spy']}/{row['years_losing_to_spy']} | {row['trades']} | {row['decision']} |"
        )
    return out


def balanced_score(row: dict[str, Any]) -> float:
    return (
        float(row["drawdown_improvement_vs_parent_pct"]) * 2.0
        + float(row["calmar"]) * 30.0
        + max(float(row["excess_cagr"]), 0.0)
        + (5.0 if int(row["years_beating_spy"]) > int(row["years_losing_to_spy"]) else 0.0)
    )


def append_learning(state_dir: str) -> None:
    path = Path(state_dir) / "dd_first_learning_memory.json"
    payload = json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else {"events": []}
    lesson = "Exposure reduction partial is the first useful DD_FIRST axis. Monotonic exposure refinement should identify the best fixed exposure between 50 and 75 before testing dynamic regime exposure."
    if not any(event.get("lesson") == lesson for event in payload.get("events", [])):
        payload.setdefault("events", []).append(
            {
                "created_at": datetime.now(timezone.utc).isoformat(),
                "axis": "exposure_reduction_partial",
                "event_type": "exposure_refinement_summary",
                "lesson": lesson,
                "next_axis": "dynamic_regime_exposure_after_fixed_exposure_selection",
            }
        )
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _num(value: Any) -> float:
    try:
        return round(float(str(value).replace(",", ".")), 6)
    except (TypeError, ValueError):
        return 0.0


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _csv_value(value: Any) -> Any:
    if isinstance(value, float):
        return str(value).replace(".", ",")
    return value


if __name__ == "__main__":
    raise SystemExit(main())
