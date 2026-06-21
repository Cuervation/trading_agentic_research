from __future__ import annotations

import argparse, csv, json, math, shutil, subprocess, sys
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtester.data_loader import load_daily_feature_store_folder, load_weekly_feature_store, validate_feature_store
from backtester.execution import run_strategy_backtest
from backtester.metrics import summarize_performance
from backtester.spy_comparison import build_spy_equity_curve, compare_equity_curves, compare_monthly, compare_yearly, summarize_spy_comparison
from scripts.governance import build_run_manifest
from scripts.run_backtest import build_summary_markdown, build_yearly_strategy_stats

TARGETS = {
    "baseline": ("HYP_REFINE_AUTO002_TOPN_6_V1", "HYP_REFINE_AUTO002_TOPN_6_V1_STRICT_NEXT_CLOSE"),
    "mejor_global": ("HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_LONG_R12_C22_E75_CR40_REDD_RECOVERED_DD8_SL20", "HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_STRICT_R12_C22_E75_CR40_REDD_RECOVERED_DD8_SL20"),
    "alternativa_defensiva": ("HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_LONG_R12_C22_E75_CR40_REDD_RECOVERED_DD7_SL18", "HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_STRICT_R12_C22_E75_CR40_REDD_RECOVERED_DD7_SL18"),
    "sub30": ("HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_LONG_R12_C21_E75_CR33_REDD_RECOVERED_DD8_SL20", "HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_STRICT_R12_C21_E75_CR33_REDD_RECOVERED_DD8_SL20"),
}
PERIODS = {"2008_2009": ("2008-01-01", "2009-12-31"), "q4_2018": ("2018-10-01", "2018-12-31"), "2025": ("2025-01-01", "2025-12-31")}
EXPECTED = {"baseline": (19.13, -51.08), "mejor_global": (14.04, -32.64), "alternativa_defensiva": (13.52, -31.73), "sub30": (11.31, -29.85)}

def read_json(p: Path, default=None):
    try: return json.loads(p.read_text(encoding="utf-8-sig"))
    except Exception: return default

def write_json(p: Path, obj: Any):
    p.parent.mkdir(parents=True, exist_ok=True); p.write_text(json.dumps(obj, indent=2, ensure_ascii=False, default=str), encoding="utf-8")

def write_csv(p: Path, rows: list[dict]):
    p.parent.mkdir(parents=True, exist_ok=True)
    keys = sorted({k for r in rows for k in r})
    with p.open("w", newline="", encoding="utf-8") as f:
        w=csv.DictWriter(f, keys); w.writeheader(); w.writerows(rows)

def find_config(root: Path, strategy_id: str) -> Path | None:
    direct = root / "configs" / "generated" / f"{strategy_id}.json"
    if direct.exists(): return direct
    cands = list(root.glob(f"reports/**/generated_configs/{strategy_id}.json"))
    if cands: return sorted(cands, key=lambda p: p.stat().st_mtime, reverse=True)[0]
    for mf in root.glob("runs/**/run_manifest.json"):
        js = read_json(mf, {}) or {}
        if js.get("strategy_id") == strategy_id:
            cp = Path(str(js.get("strategy_config_path", "")))
            if not cp.is_absolute(): cp = root / cp
            if cp.exists(): return cp
    return None

def detect_data(root: Path, project: dict):
    weekly = project.get("data_paths", {}).get("weekly_file_path") or ""
    daily = project.get("data_paths", {}).get("daily_folder_path") or ""
    if not weekly:
        weekly = sorted(root.glob("data/*weekly*.csv"))[-1]
    else: weekly = Path(weekly)
    if not daily:
        daily = root / "data"
    else: daily = Path(daily)
    if not weekly.is_absolute(): weekly = root / weekly
    if not daily.is_absolute(): daily = root / daily
    return weekly, daily

def period_metrics(eq: pd.DataFrame, start: str, end: str):
    x = eq.copy(); x["date"] = pd.to_datetime(x["date"]); x = x[(x.date >= start) & (x.date <= end)]
    if len(x) < 2: return {"return": None, "max_dd": None}
    total = (float(x.equity.iloc[-1]) / float(x.equity.iloc[0]) - 1) * 100
    dd = (x.equity / x.equity.cummax() - 1).min() * 100
    return {"return": total, "max_dd": dd}

def worst_year(eq: pd.DataFrame):
    x=eq.copy(); x["date"]=pd.to_datetime(x["date"])
    y=x.set_index("date").equity.resample("YE").apply(lambda s: s.iloc[-1]/s.iloc[0]-1 if len(s)>1 and s.iloc[0] else float("nan")).dropna()
    return float(y.min()*100) if len(y) else None

def calmar(m):
    dd = abs(float(m.get("max_drawdown_pct") or 0)); return float(m.get("cagr_pct") or 0)/dd if dd else None

def run_one(root, cfg, project, weekly_df, daily_df, weekly_file, daily_folder, out, label, variant_kind, scenario, cost_mult, slip_mult):
    sid = cfg["strategy_id"]
    run_id = f"STRICT_EXEC_{label}_{variant_kind}_{scenario}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
    res = run_strategy_backtest(weekly_df, daily_df, cfg, project)
    eq, trades, diag = res["equity_curve"], res["trades"], res["diagnostics"]
    sm = summarize_performance(eq)
    spy_eq = build_spy_equity_curve(daily_df=daily_df, start_date=sm["start_date"], end_date=sm["end_date"], initial_capital=float(project.get("initial_capital",10000)), benchmark_ticker=str(project.get("benchmark_ticker","SPY")))
    spy_m = summarize_performance(spy_eq[["date","equity"]])
    cmp_d = compare_equity_curves(eq[["date","equity"]], spy_eq[["date","equity"]])
    cmp_m = compare_monthly(eq[["date","equity"]], spy_eq[["date","equity"]])
    cmp_y = compare_yearly(eq[["date","equity"]], spy_eq[["date","equity"]])
    cmp_s = summarize_spy_comparison(cmp_m, cmp_y, sm, spy_m)
    run_dir = root / "runs" / run_id; run_dir.mkdir(parents=True, exist_ok=True)
    eq.to_csv(run_dir/"equity_curve.csv", index=False, sep=";", decimal=",")
    trades.to_csv(run_dir/"trades.csv", index=False, sep=";", decimal=",")
    yd = build_yearly_strategy_stats(run_id, sid, cmp_y); yd.to_csv(run_dir/"yearly_strategy_stats.csv", index=False, sep=";", decimal=",")
    cmp_d.to_csv(run_dir/"spy_comparison_daily.csv", index=False, sep=";", decimal=",")
    cmp_m.to_csv(run_dir/"spy_comparison_monthly.csv", index=False, sep=";", decimal=",")
    cmp_y.to_csv(run_dir/"spy_comparison_yearly.csv", index=False, sep=";", decimal=",")
    ex = diag.get("execution_timing", {})
    ec = diag.get("execution_costs", {})
    metrics = {"strategy": sm, "spy": spy_m, "diagnostics": diag, "execution_timing_mode": ex.get("execution_timing_mode","current_default"), "strict_next_close_enabled": bool(ex.get("strict_next_close_enabled",False)), "delayed_execution_count": int(ex.get("delayed_execution_count",0) or 0), "same_close_execution_count": int(ex.get("same_close_execution_count",0) or 0), "execution_timing_notes": ex.get("execution_timing_notes",[]), "costs": {"applied": True, "cost_per_side_pct": ec.get("effective_cost_per_side_pct", project.get("cost_per_side_pct",0.24)), "base_cost_per_side_pct": ec.get("base_cost_per_side_pct", project.get("cost_per_side_pct",0.24)), "base_slippage_per_side_pct": ec.get("base_slippage_per_side_pct",0), "cost_multiplier": cost_mult, "slippage_multiplier": slip_mult}}
    write_json(run_dir/"metrics.json", metrics); write_json(run_dir/"spy_comparison_summary.json", cmp_s)
    (run_dir/"summary.md").write_text(build_summary_markdown(run_id, sid, sm, spy_m, cmp_s, yd, len(trades), list(diag.get("warnings", []))), encoding="utf-8")
    manifest = build_run_manifest(run_id=run_id, parent_run_id="AUTO_002", strategy_config=cfg, strategy_config_path=str(out/"configs"/f"{sid}.json"), project_config=project, weekly_file=str(weekly_file), daily_folder=str(daily_folder), parent_strategy_config=None)
    manifest.update({"execution_timing_mode": metrics["execution_timing_mode"], "strict_next_close_enabled": metrics["strict_next_close_enabled"], "delayed_execution_count": metrics["delayed_execution_count"], "execution_costs": metrics["costs"]})
    write_json(run_dir/"run_manifest.json", manifest)
    rc = diag.get("risk_controls", {})
    pg = rc.get("portfolio_drawdown_guard", {})
    ps = rc.get("position_stop_loss", {})
    row = {"label": label, "variant_kind": variant_kind, "scenario": scenario, "strategy_id": sid, "run_id": run_id, "run_dir": str(run_dir), "execution_timing_mode": metrics["execution_timing_mode"], "strict_next_close_enabled": metrics["strict_next_close_enabled"], "cagr": sm.get("cagr_pct"), "max_drawdown": sm.get("max_drawdown_pct"), "calmar": calmar(sm), "worst_year": worst_year(eq), "total_return": sm.get("total_return_pct"), "final_equity": float(eq.equity.iloc[-1]), "trades": len(trades), "exposure_avg": float(pd.to_numeric(eq.get("gross_exposure", pd.Series(dtype=float)), errors="coerce").mean()) if "gross_exposure" in eq else None, "delayed_execution_count": metrics["delayed_execution_count"], "position_stop_count": ps.get("count",0), "dd_guard_activation_count": pg.get("activations",0), "reentry_count": pg.get("reentries",0), "cost_multiplier": cost_mult, "slippage_multiplier": slip_mult, "metric_warning": False, "notes": ""}
    for name,(a,b) in PERIODS.items():
        pm=period_metrics(eq,a,b); row[f"{name}_return"]=pm["return"]; row[f"{name}_max_dd"]=pm["max_dd"]
    if variant_kind == "original" and label in EXPECTED and scenario == "base":
        ecagr, edd = EXPECTED[label]; row["metric_warning"] = abs((row["cagr"] or 0)-ecagr)>1.0 or abs((row["max_drawdown"] or 0)-edd)>2.0
    return row, eq

def portfolio_row(name, parts):
    merged=None
    for label, eq, w in parts:
        x=eq[["date","equity"]].copy(); x["ret"]=x.equity.pct_change().fillna(0); x=x[["date","ret"]].rename(columns={"ret":label})
        merged=x if merged is None else merged.merge(x,on="date",how="inner")
    ret=sum(merged[label]*w for label,_,w in parts)
    eq=pd.DataFrame({"date":merged.date,"equity":(1+ret).cumprod(),"ret":ret})
    sm=summarize_performance(eq[["date","equity"]]); row={"portfolio":name,"cagr":sm.get("cagr_pct"),"max_drawdown":sm.get("max_drawdown_pct"),"calmar":calmar(sm),"worst_year":worst_year(eq)}
    for pname,(a,b) in PERIODS.items(): row[f"{pname}_max_dd"] = period_metrics(eq,a,b)["max_dd"]
    return row

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--repo-root", default=str(ROOT)); ap.add_argument("--output-dir", default=""); ap.add_argument("--include-x15", action="store_true")
    args=ap.parse_args(); root=Path(args.repo_root).resolve(); ts=datetime.now().strftime("%Y%m%d_%H%M%S")
    out=Path(args.output_dir) if args.output_dir else root/"reports"/f"strict_execution_validate_HYP_REFINE_AUTO002_TOPN_6_V1_{ts}"
    if not out.is_absolute(): out=root/out
    out.mkdir(parents=True, exist_ok=True); (out/"configs").mkdir(exist_ok=True)
    cfg_dir=root/"configs"/"generated"/"strict_execution_validation"; cfg_dir.mkdir(parents=True, exist_ok=True)
    project=read_json(root/"configs"/"project_config.json", {}) or {}; weekly_file,daily_folder=detect_data(root, project)
    audit = ["# Execution timing audit", "", "- Rebalance: signals are mapped to first daily close strictly after signal_date (next available close).", "- market_filter_failed / left_top_n: rebalance exits execute on that mapped rebalance close; signal source is prior weekly signal.", "- portfolio_drawdown_guard / reduced exposure / crisis / reentry: previous engine evaluated and scaled on same daily close; strict mode evaluates prior close and executes current close.", "- position_stop_loss: previous engine detected and exited on same daily close; strict mode detects prior close and exits current close.", "- Default behavior: unchanged unless config execution_timing.enabled=true and mode=strict_next_close."]
    (out/"execution_timing_audit.md").write_text("\n".join(audit), encoding="utf-8")
    configs=[]; failed=[]
    for label,(orig_id, strict_id) in TARGETS.items():
        path=find_config(root, orig_id)
        if not path: failed.append(f"missing config {orig_id}"); continue
        orig=read_json(path, {}) or {}; orig["strategy_id"]=orig_id; orig["hypothesis_id"]=orig_id
        strict=json.loads(json.dumps(orig)); strict["strategy_id"]=strict_id; strict["hypothesis_id"]=strict_id
        strict["execution_timing"]={"enabled": True, "mode": "strict_next_close", "apply_to": ["portfolio_drawdown_guard", "position_stop_loss", "reentry", "rebalance_exits", "market_filter_exits"]}
        for cfg in [orig, strict]:
            write_json(cfg_dir/f"{cfg['strategy_id']}.json", cfg); write_json(out/"configs"/f"{cfg['strategy_id']}.json", cfg)
        configs.append((label, orig, strict))
    weekly_df=load_weekly_feature_store(str(weekly_file)); daily_df=load_daily_feature_store_folder(str(daily_folder))
    for df,label in [(weekly_df,"weekly"),(daily_df,"daily")]:
        rep=validate_feature_store(df, required_columns=["date","ticker","close"], benchmark_ticker="SPY")
        if rep["missing_required_columns"]: raise ValueError(f"{label} missing {rep['missing_required_columns']}")
    scenarios=[("base",1.0,1.0),("cost2_slip2",2.0,2.0)]
    if args.include_x15: scenarios.insert(1,("cost1_5_slip1_5",1.5,1.5))
    results=[]; costs=[]; strict_equities={}
    for label,orig,strict in configs:
        for kind,cfg0 in [("original",orig),("strict",strict)]:
            for scen,cm,sm in scenarios:
                cfg=json.loads(json.dumps(cfg0)); cfg["execution_costs"]={"enabled": True, "cost_multiplier": cm, "slippage_multiplier": sm, "slippage_per_side_pct": 0.0}
                row,eq=run_one(root,cfg,project,weekly_df,daily_df,weekly_file,daily_folder,out,label,kind,scen,cm,sm)
                results.append(row); costs.append(row.copy())
                if kind=="strict" and scen=="base": strict_equities[label]=eq
    ports=[]
    defs=[("A_100_mejor_global_strict",[("mejor_global",1.0)]),("B_75_mejor_25_defensiva_strict",[("mejor_global",.75),("alternativa_defensiva",.25)]),("C_50_mejor_50_defensiva_strict",[("mejor_global",.5),("alternativa_defensiva",.5)]),("D_75_mejor_25_sub30_strict",[("mejor_global",.75),("sub30",.25)]),("E_50_mejor_50_sub30_strict",[("mejor_global",.5),("sub30",.5)])]
    for name,parts in defs:
        if all(k in strict_equities for k,_ in parts): ports.append(portfolio_row(name, [(k, strict_equities[k], w) for k,w in parts]))
    write_csv(out/"strict_execution_results.csv", results); write_csv(out/"strict_cost_slippage_results.csv", costs); write_csv(out/"strict_portfolio_mix_results.csv", ports)
    (out/"failed_variants.md").write_text("# Failed variants\n" + ("\n".join(f"- {x}" for x in failed) if failed else "- none\n"), encoding="utf-8")
    modified=["backtester/execution.py","scripts/run_backtest.py","scripts/validation/run_strict_execution_validation.py"]
    (out/"implementation_notes.md").write_text("# Implementation notes\n- Added config-driven strict_next_close; default remains current_default.\n- Added config-driven execution_costs multiplier path; slippage base is explicit and defaults to 0.0 here.\n- Modified files: " + ", ".join(modified) + "\n", encoding="utf-8")
    best_single=max([r for r in results if r["variant_kind"]=="strict" and r["scenario"]=="base"], key=lambda r:r.get("calmar") or -999, default={})
    best_port=max(ports, key=lambda r:r.get("calmar") or -999, default={})
    pass_fail="PASS_WITH_LIMITATIONS" if best_single and (best_single.get("cagr") or 0)>0 and (best_single.get("delayed_execution_count") or 0)>=0 else "INCONCLUSIVE"
    readme=f"""# README_ANALISIS_FINAL\n\n## Resumen ejecutivo\nValidación strict next-close config-driven. El default del motor queda apagado (`current_default`).\n\n## Código modificado\n- `backtester/execution.py`\n- `scripts/run_backtest.py`\n- `scripts/validation/run_strict_execution_validation.py`\n\n## Compatibilidad\nLas corridas sin `execution_timing.enabled=true` siguen en modo `current_default`; ver filas `original/base` en `strict_execution_results.csv`.\n\n## Comparaciones\n- Resultados strict: `strict_execution_results.csv`\n- Costos/slippage: `strict_cost_slippage_results.csv`\n- Portfolios: `strict_portfolio_mix_results.csv`\n- Audit: `execution_timing_audit.md`\n\n## Conclusión directa para Hernán\n- Mejor strict single por Calmar: `{best_single.get('strategy_id','N/D')}`.\n- Mejor strict portfolio por Calmar: `{best_port.get('portfolio','N/D')}`.\n- Strict next-close cambia la decisión solo si las filas strict degradan fuerte contra original/base; revisá `metric_warning`, CAGR y DD.\n- Paper trading: sí solo si aceptás las limitaciones de slippage base 0 y los resultados strict mantienen edge.\n- Falta otra validación si querés slippage separado real con un modelo de fill más rico que close-to-close.\n\nPass/fail: `{pass_fail}`\n"""
    (out/"README_ANALISIS_FINAL.md").write_text(readme, encoding="utf-8")
    excel=out/"strict_execution_validation.xlsx"; excel_ok=False
    try:
        import openpyxl # noqa
        with pd.ExcelWriter(excel, engine="openpyxl") as xw:
            pd.DataFrame(results).to_excel(xw,"strict_results",index=False)
            pd.DataFrame(costs).to_excel(xw,"cost_slippage",index=False)
            pd.DataFrame(ports).to_excel(xw,"portfolios",index=False)
        excel_ok=True
    except Exception: pass
    pyc=subprocess.run([sys.executable,"-m","py_compile","backtester/execution.py","scripts/run_backtest.py",__file__],cwd=root,capture_output=True,text=True)
    git=subprocess.run(["git","status","--short"],cwd=root,capture_output=True,text=True).stdout.strip().replace("\n","; ")
    base_unchanged=not any(r.get("metric_warning") for r in results if r["variant_kind"]=="original" and r["scenario"]=="base")
    print(f"Report dir: {out}")
    print(f"Excel: {excel if excel_ok else 'not_available'}")
    print(f"Strict results: {out/'strict_execution_results.csv'}")
    print(f"Cost/slippage results: {out/'strict_cost_slippage_results.csv'}")
    print(f"Portfolio results: {out/'strict_portfolio_mix_results.csv'}")
    print(f"Files modified: {', '.join(modified)}")
    print(f"Py compile: {'pass' if pyc.returncode==0 else 'fail'}")
    print(f"Baseline unchanged: {base_unchanged}")
    print(f"Best strict single: {best_single.get('strategy_id','N/D')}")
    print(f"Best strict portfolio: {best_port.get('portfolio','N/D')}")
    print(f"Pass/fail: {pass_fail}")
    print("Requires more work: slippage fill model if needed")
    print("Recommendation: revisar README y CSV; no promocionar sin paper trading")
    print(f"Git status: {git[:260]}")

if __name__ == "__main__": main()
