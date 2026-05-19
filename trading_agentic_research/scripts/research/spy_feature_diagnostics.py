"""Diagnostics for SPY market-filter feature quality."""
from __future__ import annotations
import argparse, json
from pathlib import Path
from typing import Any
import pandas as pd

def _read_csv_auto(path: str | Path) -> pd.DataFrame:
    p=Path(path)
    with p.open("r", encoding="utf-8-sig") as f: first=f.readline()
    sep=";" if ";" in first else ","
    decimal="," if sep == ";" else "."
    return pd.read_csv(p, sep=sep, decimal=decimal, low_memory=False)

def _pct(value: float) -> float:
    return round(float(value)*100.0, 4)

def diagnose_spy_features(weekly_file: str | Path, benchmark_ticker: str="SPY") -> dict[str, Any]:
    df=_read_csv_auto(weekly_file)
    result={"weekly_file":str(weekly_file),"rows":int(len(df)),"columns":list(df.columns),"benchmark_ticker":benchmark_ticker}
    if "ticker" not in df.columns:
        result.update({"status":"error","error":"missing_ticker_column"}); return result
    spy=df[df["ticker"].astype(str)==benchmark_ticker].copy()
    result["spy_rows"]=int(len(spy)); result["status"]="ok" if len(spy) else "error"
    if spy.empty:
        result["error"]="missing_spy_rows"; return result
    metrics=["spy_close_vs_sma50_pct","close_vs_sma50_pct","spy_close_sma_50_slope_5d_pct","close_sma_50_slope_5d_pct"]
    result["metric_quality"]={}
    for col in metrics:
        if col not in spy.columns:
            result["metric_quality"][col]={"exists":False}; continue
        s=pd.to_numeric(spy[col], errors="coerce")
        result["metric_quality"][col]={"exists":True,"non_null":int(s.notna().sum()),"null":int(s.isna().sum()),"null_pct":_pct(s.isna().mean()),"sample_non_null":[float(x) for x in s.dropna().head(5).tolist()]}
    primary=result["metric_quality"].get("spy_close_vs_sma50_pct", {})
    fallback=result["metric_quality"].get("close_vs_sma50_pct", {})
    if primary.get("exists") and primary.get("null_pct",100) >= 95 and fallback.get("exists") and fallback.get("non_null",0) > 0:
        result["recommendation"]="Use close_vs_sma50_pct on the SPY row as fallback for spy_close_vs_sma50_pct."
    elif primary.get("non_null",0) > 0:
        result["recommendation"]="Primary SPY metric is usable."
    elif fallback.get("exists"):
        result["recommendation"]="Primary SPY metric missing; use close_vs_sma50_pct on SPY row."
    else:
        result["recommendation"]="SPY market filter data is not reliable; avoid strict SPY filters until feature store is fixed."
    return result

def write_report(result: dict[str, Any], reports_dir: str | Path="reports") -> Path:
    out=Path(reports_dir); out.mkdir(parents=True, exist_ok=True)
    (out/"spy_feature_diagnostics.json").write_text(json.dumps(result, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    lines=["# SPY Feature Diagnostics","",f"- Weekly file: `{result.get('weekly_file')}`",f"- Rows: {result.get('rows')}",f"- SPY rows: {result.get('spy_rows')}",f"- Status: {result.get('status')}",f"- Recommendation: {result.get('recommendation')}","","| metric | exists | non_null | null_pct | sample_non_null |","|---|---:|---:|---:|---|"]
    for col, info in (result.get("metric_quality") or {}).items():
        lines.append(f"| `{col}` | {info.get('exists')} | {info.get('non_null',0)} | {info.get('null_pct','n/a')} | {info.get('sample_non_null', [])} |")
    md=out/"spy_feature_diagnostics.md"; md.write_text("\n".join(lines)+"\n", encoding="utf-8")
    return md

def main() -> int:
    p=argparse.ArgumentParser(); p.add_argument("--weekly-file", required=True); p.add_argument("--benchmark-ticker", default="SPY"); p.add_argument("--reports-dir", default="reports")
    a=p.parse_args(); r=diagnose_spy_features(a.weekly_file, a.benchmark_ticker); path=write_report(r, a.reports_dir)
    print(json.dumps({"report":str(path), "recommendation":r.get("recommendation")}, ensure_ascii=False)); return 0
if __name__=="__main__": raise SystemExit(main())
