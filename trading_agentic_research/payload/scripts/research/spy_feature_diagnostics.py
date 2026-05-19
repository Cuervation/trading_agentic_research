"""SPY feature diagnostics for market-filter reliability.

Many generated hypotheses depend on SPY regime/market filters. If SPY features
are NaN and the signal builder falls back, the experiment may not be testing the
claimed mechanism. This diagnostic turns that into an explicit report.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd


SPY_METRIC_CANDIDATES = (
    "spy_close_vs_sma50_pct",
    "close_vs_sma50_pct",
    "close_vs_sma52w_pct",
    "spy_close_sma_50_slope_5d_pct",
    "close_sma_50_slope_5d_pct",
)


def _pct(n: int, d: int) -> float:
    return round((100.0 * n / d), 4) if d else 0.0


def diagnose_weekly_df(df: pd.DataFrame, benchmark_ticker: str = "SPY") -> dict[str, Any]:
    if df is None or df.empty:
        return {"ok": False, "reason": "empty_weekly_df"}
    if "ticker" not in df.columns:
        return {"ok": False, "reason": "missing_ticker_column", "columns": list(df.columns)}

    out: dict[str, Any] = {
        "ok": True,
        "benchmark_ticker": benchmark_ticker,
        "rows": int(len(df)),
        "columns": list(df.columns),
    }
    spy = df[df["ticker"].astype(str) == str(benchmark_ticker)].copy()
    out["spy_rows"] = int(len(spy))
    out["spy_row_pct"] = _pct(len(spy), len(df))
    if spy.empty:
        out["ok"] = False
        out["reason"] = "missing_spy_rows"
        return out

    metric_report: dict[str, Any] = {}
    for col in SPY_METRIC_CANDIDATES:
        if col not in spy.columns:
            metric_report[col] = {"exists": False}
            continue
        series = pd.to_numeric(spy[col], errors="coerce")
        nan_count = int(series.isna().sum())
        metric_report[col] = {
            "exists": True,
            "non_null": int(series.notna().sum()),
            "nan_count": nan_count,
            "nan_pct": _pct(nan_count, len(spy)),
            "min": float(series.min()) if series.notna().any() else None,
            "max": float(series.max()) if series.notna().any() else None,
        }
    out["metrics"] = metric_report

    preferred = metric_report.get("spy_close_vs_sma50_pct", {})
    direct = metric_report.get("close_vs_sma50_pct", {})
    out["market_filter_reliability"] = {
        "preferred_metric_usable_pct": 100.0 - float(preferred.get("nan_pct", 100.0) if preferred.get("exists") else 100.0),
        "direct_spy_metric_usable_pct": 100.0 - float(direct.get("nan_pct", 100.0) if direct.get("exists") else 100.0),
        "recommendation": "ok",
    }
    if not preferred.get("exists") or float(preferred.get("nan_pct", 100.0)) > 20.0:
        if direct.get("exists") and float(direct.get("nan_pct", 100.0)) <= 20.0:
            out["market_filter_reliability"]["recommendation"] = "use_close_vs_sma50_pct_for_spy_row_fallback"
        else:
            out["market_filter_reliability"]["recommendation"] = "critical_fix_spy_market_filter_features"
    return out


def diagnose_weekly_file(weekly_file: str | Path, benchmark_ticker: str = "SPY") -> dict[str, Any]:
    p = Path(weekly_file)
    if not p.exists():
        return {"ok": False, "reason": "weekly_file_not_found", "weekly_file": str(p)}
    df = pd.read_csv(p)
    report = diagnose_weekly_df(df, benchmark_ticker=benchmark_ticker)
    report["weekly_file"] = str(p)
    return report


def write_spy_feature_diagnostics(
    *,
    weekly_file: str | Path,
    reports_dir: str | Path = "reports",
    benchmark_ticker: str = "SPY",
) -> dict[str, Any]:
    report = diagnose_weekly_file(weekly_file, benchmark_ticker=benchmark_ticker)
    out_dir = Path(reports_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "spy_feature_diagnostics.json"
    md_path = out_dir / "spy_feature_diagnostics.md"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")

    lines = ["# SPY Feature Diagnostics", "", f"- OK: {report.get('ok')}", f"- Reason: {report.get('reason', '')}", f"- Weekly file: `{report.get('weekly_file', weekly_file)}`", f"- SPY rows: {report.get('spy_rows', 0)}", "", "## Market filter reliability", ""]
    rel = report.get("market_filter_reliability", {}) or {}
    for k, v in rel.items():
        lines.append(f"- {k}: {v}")
    lines.extend(["", "## Metrics", "", "| metric | exists | non_null | nan_pct | min | max |", "|---|---:|---:|---:|---:|---:|"])
    for col, row in (report.get("metrics", {}) or {}).items():
        lines.append(f"| {col} | {row.get('exists')} | {row.get('non_null', '')} | {row.get('nan_pct', '')} | {row.get('min', '')} | {row.get('max', '')} |")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"report": str(json_path), "markdown": str(md_path), "diagnostics": report}


def main() -> int:
    import argparse
    p = argparse.ArgumentParser(description="Diagnose SPY weekly features used by market filters.")
    p.add_argument("--weekly-file", required=True)
    p.add_argument("--reports-dir", default="reports")
    p.add_argument("--benchmark-ticker", default="SPY")
    args = p.parse_args()
    print(json.dumps(write_spy_feature_diagnostics(
        weekly_file=args.weekly_file,
        reports_dir=args.reports_dir,
        benchmark_ticker=args.benchmark_ticker,
    ), indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
