"""SPY feature diagnostics for market-filter reliability."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any
import pandas as pd

def diagnose_spy_features(weekly_file: str | Path, benchmark_ticker: str = "SPY") -> dict[str, Any]:
    df = pd.read_csv(weekly_file)
    if "ticker" not in df.columns:
        return {"ok": False, "reason": "missing_ticker_column"}
    spy = df[df["ticker"].astype(str) == benchmark_ticker].copy()
    out: dict[str, Any] = {"ok": True, "benchmark_ticker": benchmark_ticker, "rows_total": int(len(df)), "rows_spy": int(len(spy)), "metrics": {}}
    for col in ["spy_close_vs_sma50_pct", "close_vs_sma50_pct", "close_vs_sma52w_pct", "spy_close_sma_50_slope_5d_pct"]:
        if col in spy.columns:
            s = pd.to_numeric(spy[col], errors="coerce")
            out["metrics"][col] = {"exists": True, "non_null": int(s.notna().sum()), "null": int(s.isna().sum()), "null_pct": float(s.isna().mean() * 100) if len(s) else 100.0}
        else:
            out["metrics"][col] = {"exists": False}
    out["recommended_market_filter_metric_order"] = ["spy_close_vs_sma50_pct", "close_vs_sma50_pct", "close_vs_sma52w_pct"]
    return out

def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--weekly-file", required=True)
    p.add_argument("--reports-dir", default="reports")
    p.add_argument("--benchmark-ticker", default="SPY")
    args = p.parse_args()
    result = diagnose_spy_features(args.weekly_file, benchmark_ticker=args.benchmark_ticker)
    out = Path(args.reports_dir) / "spy_feature_diagnostics.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    print(f"Output: {out}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
