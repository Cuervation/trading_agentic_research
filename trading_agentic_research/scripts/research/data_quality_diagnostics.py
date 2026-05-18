"""Data quality diagnostics for autonomous backtest inputs."""
from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


WATCH_COLUMNS = [
    "spy_close_vs_sma50_pct",
    "spy_channel_r2",
    "spy_channel_slope_pct",
    "ret_52w_pct",
    "close_vs_sma52w_pct",
    "atr_14w_pct",
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: str | Path, default: Any = None) -> Any:
    p = Path(path)
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return default


def write_json(path: str | Path, payload: Any) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def read_csv_auto(path: str | Path, nrows: int | None = None) -> pd.DataFrame:
    return pd.read_csv(path, sep=None, engine="python", nrows=nrows)


def diagnose_data_quality(
    *,
    weekly_file: str | Path | None = None,
    state_dir: str | Path = "state",
    reports_dir: str | Path = "reports",
    max_warn_nan_pct: float = 20.0,
) -> dict[str, Any]:
    if not weekly_file:
        resolved = read_json(Path(state_dir) / "data_paths_resolved.json", {}) or {}
        weekly_file = resolved.get("weekly_file")
    if not weekly_file:
        payload = {"status": "blocked", "reason": "missing_weekly_file", "generated_at": now_iso()}
        write_json(Path(reports_dir) / "data_quality_diagnostics.json", payload)
        return payload

    df = read_csv_auto(weekly_file)
    # normalize signal_date only for diagnostics; do not mutate source file.
    if "date" not in df.columns and "signal_date" in df.columns:
        df = df.rename(columns={"signal_date": "date"})

    rows = int(len(df))
    columns = list(df.columns)
    col_reports = []
    warnings: list[str] = []
    for col in WATCH_COLUMNS:
        if col not in df.columns:
            col_reports.append({"column": col, "exists": False, "nan_pct": None, "non_null": 0})
            warnings.append(f"missing_watch_column:{col}")
            continue
        nan_pct = float(df[col].isna().mean() * 100) if rows else 100.0
        non_null = int(df[col].notna().sum())
        col_reports.append({"column": col, "exists": True, "nan_pct": round(nan_pct, 4), "non_null": non_null})
        if nan_pct > max_warn_nan_pct:
            warnings.append(f"high_nan_pct:{col}:{nan_pct:.2f}")

    spy_rows = int((df.get("ticker", pd.Series(dtype=str)).astype(str).str.upper() == "SPY").sum()) if "ticker" in df.columns else 0
    payload = {
        "status": "warning" if warnings else "ok",
        "generated_at": now_iso(),
        "weekly_file": str(weekly_file),
        "rows": rows,
        "columns": len(columns),
        "has_signal_date": "signal_date" in columns,
        "has_date": "date" in columns,
        "spy_rows": spy_rows,
        "watch_columns": col_reports,
        "warnings": warnings,
    }

    reports = Path(reports_dir)
    reports.mkdir(parents=True, exist_ok=True)
    write_json(reports / "data_quality_diagnostics.json", payload)

    md = [
        "# Data Quality Diagnostics",
        "",
        f"Generated at: `{payload['generated_at']}`",
        f"Weekly file: `{payload['weekly_file']}`",
        f"Rows: **{rows}**",
        f"SPY rows: **{spy_rows}**",
        "",
        "| column | exists | nan % | non-null |",
        "|---|:---:|---:|---:|",
    ]
    for item in col_reports:
        md.append(f"| `{item['column']}` | {str(item['exists']).lower()} | {item['nan_pct'] if item['nan_pct'] is not None else '-'} | {item['non_null']} |")
    md.extend(["", "## Warnings", ""])
    md.extend([f"- {w}" for w in warnings] if warnings else ["- none"])
    (reports / "data_quality_diagnostics.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    return payload


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--weekly-file", default=None)
    p.add_argument("--state-dir", default="state")
    p.add_argument("--reports-dir", default="reports")
    p.add_argument("--max-warn-nan-pct", type=float, default=20.0)
    args = p.parse_args()
    print(json.dumps(diagnose_data_quality(weekly_file=args.weekly_file, state_dir=args.state_dir, reports_dir=args.reports_dir, max_warn_nan_pct=args.max_warn_nan_pct), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
