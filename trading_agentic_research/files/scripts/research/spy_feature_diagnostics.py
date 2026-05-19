"Diagnose SPY feature availability for market filters."
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd


def _read_csv(path: str | Path) -> pd.DataFrame:
    with Path(path).open("r", encoding="utf-8-sig") as f:
        first = f.readline()
    sep = ";" if ";" in first and "," not in first.split(";")[0] else ","
    decimal = "," if sep == ";" else "."
    return pd.read_csv(path, sep=sep, decimal=decimal)


def diagnose_spy_features(weekly_file: str | Path, benchmark_ticker: str = "SPY") -> dict[str, Any]:
    df = _read_csv(weekly_file)
    report: dict[str, Any] = {"weekly_file": str(weekly_file), "rows": int(len(df)), "columns": list(df.columns), "benchmark_ticker": benchmark_ticker}
    if "ticker" not in df.columns:
        report["status"] = "missing_ticker_column"
        return report
    spy = df[df["ticker"].astype(str) == benchmark_ticker].copy()
    report["spy_rows"] = int(len(spy))
    for col in ["spy_close_vs_sma50_pct", "close_vs_sma50_pct", "spy_close_sma_50_slope_5d_pct", "close_sma_50_slope_5d_pct"]:
        if col in spy.columns:
            values = pd.to_numeric(spy[col], errors="coerce")
            report[col] = {"exists": True, "non_null": int(values.notna().sum()), "null": int(values.isna().sum()), "null_pct": round(float(values.isna().mean() * 100.0), 4) if len(values) else None}
        else:
            report[col] = {"exists": False}
    report["recommended_market_filter_metric"] = "spy_close_vs_sma50_pct" if report.get("spy_close_vs_sma50_pct", {}).get("non_null", 0) else "close_vs_sma50_pct"
    report["status"] = "ok" if report["spy_rows"] else "missing_spy_rows"
    return report


def write_report(report: dict[str, Any], reports_dir: str | Path = "reports") -> Path:
    out = Path(reports_dir) / "spy_feature_diagnostics.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return out


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--weekly-file", required=True)
    p.add_argument("--reports-dir", default="reports")
    p.add_argument("--benchmark-ticker", default="SPY")
    args = p.parse_args()
    report = diagnose_spy_features(args.weekly_file, benchmark_ticker=args.benchmark_ticker)
    out = write_report(report, args.reports_dir)
    print(json.dumps({"output": str(out), **report}, indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
