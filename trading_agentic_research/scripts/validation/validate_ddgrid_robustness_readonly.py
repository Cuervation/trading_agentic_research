from __future__ import annotations

import argparse
import csv
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    import pandas as pd
except Exception as exc:  # pragma: no cover
    raise SystemExit(f"pandas is required for this read-only validation script: {exc}")

TARGETS = {
    "baseline": "HYP_REFINE_AUTO002_TOPN_6_V1",
    "mejor_global": "HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_LONG_R12_C22_E75_CR40_REDD_RECOVERED_DD8_SL20",
    "alternativa_defensiva": "HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_LONG_R12_C22_E75_CR40_REDD_RECOVERED_DD7_SL18",
    "sub_30_dd": "HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_LONG_R12_C21_E75_CR33_REDD_RECOVERED_DD8_SL20",
}
WINDOWS = {
    "19992008": ("1999-01-01", "2008-12-31"),
    "20092016": ("2009-01-01", "2016-12-31"),
    "20172026": ("2017-01-01", "2026-12-31"),
    "19992012": ("1999-01-01", "2012-12-31"),
    "20132026": ("2013-01-01", "2026-12-31"),
    "20042015": ("2004-01-01", "2015-12-31"),
    "20162026": ("2016-01-01", "2026-12-31"),
}
STRESS_PERIODS = {
    "20082009": ("2008-01-01", "2009-12-31"),
    "Q4_2018": ("2018-10-01", "2018-12-31"),
    "2025": ("2025-01-01", "2025-12-31"),
}


def pct(x: Any) -> float | None:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return None
    try:
        if isinstance(x, str):
            x = x.strip().replace("%", "").replace(".", "").replace(",", ".") if re.search(r"\d,\d", x) else x.strip().replace("%", "")
        return float(x)
    except Exception:
        return None


def read_csv_any(path: Path) -> pd.DataFrame:
    text = path.read_text(encoding="utf-8", errors="ignore")[:4096]
    sep = ";" if text.count(";") >= text.count(",") else ","
    df = pd.read_csv(path, sep=sep, engine="python")
    for c in df.columns:
        if df[c].dtype == object:
            s = df[c].astype(str).str.strip()
            if s.str.match(r"^-?\d+(,\d+)?([eE]-?\d+)?$").mean() > 0.5:
                df[c] = pd.to_numeric(s.str.replace(",", ".", regex=False), errors="coerce")
    return df


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    keys = sorted({k for r in rows for k in r.keys()})
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)


def load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return {}


def mget(d: dict[str, Any], *names: str) -> Any:
    for n in names:
        cur = d
        ok = True
        for p in n.split("."):
            if isinstance(cur, dict) and p in cur:
                cur = cur[p]
            else:
                ok = False; break
        if ok:
            return cur
    return None

@dataclass
class RunInfo:
    label: str
    strategy_id: str
    run_id: str = ""
    run_dir: Path | None = None
    report_dir: str = ""
    source: str = ""
    completed_at: str = ""
    incomplete: bool = True


def files_ok(rd: Path | None) -> dict[str, bool]:
    return {
        "metrics_path_exists": bool(rd and (rd / "metrics.json").exists()),
        "equity_curve_path_exists": bool(rd and (rd / "equity_curve.csv").exists()),
        "trades_path_exists": bool(rd and (rd / "trades.csv").exists()),
        "manifest_path_exists": bool(rd and (rd / "run_manifest.json").exists()),
    }


def find_runs(root: Path, targets: dict[str, str]) -> dict[str, RunInfo]:
    found: dict[str, list[RunInfo]] = {k: [] for k in targets}
    # report CSVs first
    for p in list(root.glob("reports/**/combined_grid_results.csv")) + list(root.glob("reports/**/grid_results.csv")):
        try:
            df = read_csv_any(p)
        except Exception:
            continue
        if "strategy_id" not in df.columns:
            continue
        for label, sid in targets.items():
            for _, r in df[df["strategy_id"].astype(str).eq(sid)].iterrows():
                rd_raw = str(r.get("run_dir", "") or "").strip()
                run_id = str(r.get("run_id", "") or "").strip()
                rd = Path(rd_raw) if rd_raw else (root / "runs" / run_id if run_id else None)
                if rd and not rd.is_absolute(): rd = root / rd
                found[label].append(RunInfo(label, sid, run_id, rd, str(r.get("report_dir", p.parent)), str(p), str(r.get("completed_at", ""))))
    # manifests as fallback / verifier
    for mf in root.glob("runs/**/run_manifest.json"):
        js = load_json(mf)
        sid = str(js.get("strategy_id", ""))
        for label, target in targets.items():
            if sid == target:
                found[label].append(RunInfo(label, target, str(js.get("run_id", mf.parent.name)), mf.parent, str(js.get("strategy_config_path", "")), str(mf), str(js.get("completed_at", ""))))
    chosen = {}
    for label, cands in found.items():
        def score(x: RunInfo):
            ok = files_ok(x.run_dir)
            complete = sum(ok.values())
            full = 1 if all(ok.values()) else 0
            ts = x.completed_at or x.run_id
            return (full, complete, ts, str(x.run_dir or ""))
        c = sorted(cands, key=score, reverse=True)[0] if cands else RunInfo(label, targets[label])
        c.incomplete = not all(files_ok(c.run_dir).values())
        chosen[label] = c
    return chosen


def normalize_equity(path: Path) -> pd.DataFrame:
    df = read_csv_any(path)
    date_col = next((c for c in df.columns if c.lower() in ("date", "datetime", "timestamp")), df.columns[0])
    eq_col = next((c for c in df.columns if c.lower() in ("equity", "portfolio_value", "value", "balance")), None)
    if not eq_col:
        raise ValueError(f"no equity column in {path}")
    out = df[[date_col, eq_col]].copy()
    out.columns = ["date", "equity"]
    out["date"] = pd.to_datetime(out["date"], errors="coerce")
    out["equity"] = pd.to_numeric(out["equity"], errors="coerce")
    out = out.dropna().sort_values("date").drop_duplicates("date")
    out["ret"] = out["equity"].pct_change().fillna(0.0)
    return out


def calc_metrics(eq: pd.DataFrame, start: str | None = None, end: str | None = None) -> dict[str, Any]:
    x = eq.copy()
    if start: x = x[x.date >= pd.Timestamp(start)]
    if end: x = x[x.date <= pd.Timestamp(end)]
    if len(x) < 2:
        return {"status": "insufficient_data", "rows": len(x)}
    e0, e1 = float(x.equity.iloc[0]), float(x.equity.iloc[-1])
    days = max((x.date.iloc[-1] - x.date.iloc[0]).days, 1)
    total = e1 / e0 - 1 if e0 else None
    cagr = (e1 / e0) ** (365.25 / days) - 1 if e0 and e1 > 0 else None
    dd = x.equity / x.equity.cummax() - 1
    yearly = x.set_index("date").equity.resample("YE").apply(lambda s: s.iloc[-1] / s.iloc[0] - 1 if len(s) > 1 and s.iloc[0] else float("nan")).dropna()
    rec_days = None
    peak_date = x.date.iloc[0]; peak = x.equity.iloc[0]; worst_rec = 0
    for d, val in zip(x.date, x.equity):
        if val >= peak:
            worst_rec = max(worst_rec, (d - peak_date).days); peak = val; peak_date = d
    rec_days = worst_rec
    ann_vol = x.ret.std() * math.sqrt(252) if "ret" in x and len(x) > 3 else None
    return {
        "status": "ok", "rows": len(x), "start_date": str(x.date.iloc[0].date()), "end_date": str(x.date.iloc[-1].date()),
        "total_return_pct": total * 100 if total is not None else None,
        "cagr_pct": cagr * 100 if cagr is not None else None,
        "max_drawdown_pct": dd.min() * 100,
        "worst_year_pct": yearly.min() * 100 if len(yearly) else None,
        "best_year_pct": yearly.max() * 100 if len(yearly) else None,
        "annualized_vol_pct": ann_vol * 100 if ann_vol is not None else None,
        "calmar": (cagr / abs(dd.min())) if cagr is not None and dd.min() < 0 else None,
        "recovery_days": rec_days,
    }


def compare_metrics(calc: dict[str, Any], js: dict[str, Any]) -> dict[str, Any]:
    out = {}
    pairs = [("cagr_pct", mget(js, "strategy.cagr_pct", "cagr", "cagr_pct")), ("total_return_pct", mget(js, "strategy.total_return_pct", "total_return", "total_return_pct")), ("max_drawdown_pct", mget(js, "strategy.max_drawdown_pct", "max_drawdown", "max_drawdown_pct"))]
    for k, raw in pairs:
        v = pct(raw)
        c = calc.get(k)
        out[f"metrics_json_{k}"] = v
        out[f"abs_diff_{k}"] = abs(c - v) if c is not None and v is not None else None
        out[f"rel_diff_{k}"] = abs(c - v) / abs(v) if c is not None and v not in (None, 0) else None
    out["metric_warning"] = any((out.get(f"abs_diff_{k}") or 0) > (1.0 if k != "max_drawdown_pct" else 2.0) for k, _ in pairs)
    return out


def trade_cost_rows(label: str, info: RunInfo, base_metrics: dict[str, Any], cost_mults: list[float], slip_mults: list[float]) -> list[dict[str, Any]]:
    p = info.run_dir / "trades.csv" if info.run_dir else None
    if not p or not p.exists():
        return [{"label": label, "strategy_id": info.strategy_id, "scenario": "missing_trades", "approximation": True}]
    t = read_csv_any(p)
    cols = {c.lower(): c for c in t.columns}
    gross = next((cols[c] for c in cols if "gross" in c and "return" in c), None)
    net = next((cols[c] for c in cols if "net" in c and "return" in c), None)
    entry_cost = next((cols[c] for c in cols if "entry_cost" in c), None)
    exit_cost = next((cols[c] for c in cols if "exit_cost" in c), None)
    slippage = next((cols[c] for c in cols if "slippage" in c), None)
    rows = []
    if gross and net:
        gap = (pd.to_numeric(t[gross], errors="coerce") - pd.to_numeric(t[net], errors="coerce")).fillna(0)
        base_net = pd.to_numeric(t[net], errors="coerce").fillna(0)
        base_avg = base_net.mean()
        exactish = bool(entry_cost or exit_cost or slippage)
        scenarios = [("costos_actuales", 1, 1), ("costos_x1.5", 1.5, 1), ("costos_x2", 2, 1), ("slippage_x1.5", 1, 1.5), ("slippage_x2", 1, 2), ("costos_x2_slippage_x2", 2, 2)]
        for name, cm, sm in scenarios:
            extra = gap.mean() * max(cm - 1, 0)
            if slippage:
                extra += pd.to_numeric(t[slippage], errors="coerce").fillna(0).mean() * max(sm - 1, 0)
            elif sm > 1:
                extra += gap.mean() * 0.5 * max(sm - 1, 0)
            rows.append({"label": label, "strategy_id": info.strategy_id, "scenario": name, "trades": len(t), "columns_used": ",".join([c for c in [gross, net, entry_cost, exit_cost, slippage] if c]), "approximation": not exactish or sm > 1 and not slippage, "avg_trade_net_pct_est": base_avg - extra, "avg_trade_impact_pct": extra, "base_cagr_pct": base_metrics.get("cagr_pct"), "sensitive_to_costs": abs(extra) > max(abs(base_avg) * 0.25, 0.25)})
    else:
        rows.append({"label": label, "strategy_id": info.strategy_id, "scenario": "insufficient_columns", "trades": len(t), "columns_used": ",".join(t.columns), "approximation": True})
    return rows


def portfolio_metrics(name: str, parts: list[tuple[str, pd.DataFrame, float]]) -> dict[str, Any]:
    merged = None
    for label, eq, w in parts:
        s = eq[["date", "ret"]].rename(columns={"ret": label}).copy()
        merged = s if merged is None else merged.merge(s, on="date", how="inner")
    if merged is None or len(merged) < 2:
        return {"portfolio": name, "status": "insufficient_data"}
    ret = sum(merged[label] * w for label, _, w in parts)
    out = pd.DataFrame({"date": merged.date, "equity": (1 + ret).cumprod(), "ret": ret})
    row = {"portfolio": name, "status": "ok", "components": ";".join(f"{label}:{w}" for label, _, w in parts)}
    row.update(calc_metrics(out))
    for per, (a, b) in {"2008": ("2008-01-01", "2008-12-31"), "Q4_2018": ("2018-10-01", "2018-12-31"), "2025": ("2025-01-01", "2025-12-31")}.items():
        row[f"{per}_max_drawdown_pct"] = calc_metrics(out, a, b).get("max_drawdown_pct")
    return row


def top_trades_md(label: str, info: RunInfo, eq: pd.DataFrame) -> str:
    chunks = [f"## {label}\n", f"strategy_id: `{info.strategy_id}`\n"]
    for pname, (a, b) in STRESS_PERIODS.items():
        m = calc_metrics(eq, a, b)
        chunks.append(f"### {pname}\n- retorno período: {m.get('total_return_pct')}\n- drawdown período: {m.get('max_drawdown_pct')}\n")
        tp = info.run_dir / "trades.csv" if info.run_dir else None
        if not tp or not tp.exists():
            chunks.append("- trades: no disponible\n"); continue
        t = read_csv_any(tp)
        date_cols = [c for c in t.columns if c.lower() in ("exit_date", "entry_date", "signal_date")]
        if date_cols:
            dc = date_cols[0]
            t[dc] = pd.to_datetime(t[dc], errors="coerce")
            t = t[(t[dc] >= pd.Timestamp(a)) & (t[dc] <= pd.Timestamp(b))]
        ret_col = next((c for c in t.columns if c.lower() == "net_return_pct"), next((c for c in t.columns if "return" in c.lower()), None))
        tick_col = next((c for c in t.columns if c.lower() in ("ticker", "symbol")), None)
        exit_reason = next((c for c in t.columns if "exit_reason" in c.lower()), None)
        if ret_col:
            t[ret_col] = pd.to_numeric(t[ret_col], errors="coerce")
            neg = t.nsmallest(10, ret_col)[[c for c in [tick_col, ret_col, exit_reason] if c]].to_dict("records")
            pos = t.nlargest(10, ret_col)[[c for c in [tick_col, ret_col, exit_reason] if c]].to_dict("records")
            dmg = t.groupby(tick_col)[ret_col].sum().sort_values().head(10).to_dict() if tick_col else {}
            stops = int(t[exit_reason].astype(str).str.contains("stop", case=False, na=False).sum()) if exit_reason else None
            chunks.append(f"- top 10 negativos: {json.dumps(neg, ensure_ascii=False)}\n- top 10 positivos: {json.dumps(pos, ensure_ascii=False)}\n- tickers que más dañaron: {json.dumps(dmg, ensure_ascii=False)}\n- stops detectados: {stops}\n- exit_reason disponible: {bool(exit_reason)}\n- crisis/guard events: revisar metrics/manifest; no confirmado por equity/trades si no aparece explícito.\n")
        else:
            chunks.append("- trades sin columna de retorno detectable.\n")
    return "\n".join(chunks)


def find_dd20(root: Path) -> RunInfo | None:
    terms = re.compile(r"DD20|DD20ADAPT|HYP_DD20|best drawdown|defensive", re.I)
    cands = []
    for mf in root.glob("runs/**/run_manifest.json"):
        txt = mf.read_text(encoding="utf-8", errors="ignore")
        if terms.search(txt) or terms.search(mf.parent.name):
            js = load_json(mf); sid = str(js.get("strategy_id", mf.parent.name))
            ri = RunInfo("dd20", sid, str(js.get("run_id", mf.parent.name)), mf.parent, "", str(mf), str(js.get("completed_at", "")))
            if all(files_ok(ri.run_dir).values()): cands.append(ri)
    return sorted(cands, key=lambda x: x.completed_at or x.run_id, reverse=True)[0] if cands else None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-root", required=True)
    ap.add_argument("--output-dir", required=True)
    ap.add_argument("--strategy-id", action="append", default=[])
    ap.add_argument("--run-dir", action="append", default=[])
    ap.add_argument("--report-dir", action="append", default=[])
    ap.add_argument("--include-dd20", action="store_true")
    ap.add_argument("--cost-multipliers", default="1,1.5,2")
    ap.add_argument("--slippage-multipliers", default="1,1.5,2")
    args = ap.parse_args()
    root = Path(args.repo_root).resolve()
    out = Path(args.output_dir)
    if not out.is_absolute(): out = root / out
    if not str(out.resolve()).startswith(str((root / "reports").resolve())):
        raise SystemExit("output-dir must be under reports/")
    out.mkdir(parents=True, exist_ok=True)

    targets = dict(TARGETS)
    for sid in args.strategy_id:
        targets[f"custom_{len(targets)}"] = sid
    runs = find_runs(root, targets)
    for rd in args.run_dir:
        mf = Path(rd) / "run_manifest.json"
        if mf.exists():
            js = load_json(mf); sid = js.get("strategy_id", Path(rd).name)
            runs[f"manual_{len(runs)}"] = RunInfo(f"manual_{len(runs)}", sid, js.get("run_id", Path(rd).name), Path(rd).resolve(), "", str(mf), js.get("completed_at", ""))

    robust, wf, costs = [], [], []
    equities: dict[str, pd.DataFrame] = {}
    for label, info in runs.items():
        ok = files_ok(info.run_dir)
        row = {"label": label, "strategy_id": info.strategy_id, "run_id": info.run_id, "run_dir": str(info.run_dir or ""), "report_dir": info.report_dir, "source": info.source, "completed_at": info.completed_at, **ok, "incomplete": not all(ok.values())}
        if ok["equity_curve_path_exists"]:
            eq = normalize_equity(info.run_dir / "equity_curve.csv")
            equities[label] = eq
            cm = calc_metrics(eq)
            row.update(cm)
            if ok["metrics_path_exists"]:
                row.update(compare_metrics(cm, load_json(info.run_dir / "metrics.json")))
            for wname, (a, b) in WINDOWS.items():
                wr = {"label": label, "strategy_id": info.strategy_id, "run_id": info.run_id, "window": wname, "spy_note": "SPY no disponible en equity_curve; comparación no recalculada."}
                wr.update(calc_metrics(eq, a, b)); wf.append(wr)
        robust.append(row)
        if ok["trades_path_exists"]:
            costs.extend(trade_cost_rows(label, info, row, [float(x) for x in args.cost_multipliers.split(',') if x], [float(x) for x in args.slippage_multipliers.split(',') if x]))

    # portfolios
    portfolios = []
    dd20 = find_dd20(root)
    if dd20:
        runs["dd20"] = dd20
        try: equities["dd20"] = normalize_equity(dd20.run_dir / "equity_curve.csv")
        except Exception: pass
    portfolio_defs = [
        ("A_100_mejor_global", [("mejor_global", 1.0)]),
        ("B_75_mejor_25_defensiva", [("mejor_global", .75), ("alternativa_defensiva", .25)]),
        ("C_50_mejor_50_defensiva", [("mejor_global", .5), ("alternativa_defensiva", .5)]),
        ("D_75_mejor_25_sub30", [("mejor_global", .75), ("sub_30_dd", .25)]),
        ("E_50_mejor_50_sub30", [("mejor_global", .5), ("sub_30_dd", .5)]),
    ]
    if "dd20" in equities:
        portfolio_defs += [("F_75_mejor_25_DD20", [("mejor_global", .75), ("dd20", .25)]), ("G_50_mejor_50_DD20", [("mejor_global", .5), ("dd20", .5)])]
    for name, parts in portfolio_defs:
        if all(k in equities for k, _ in parts):
            portfolios.append(portfolio_metrics(name, [(k, equities[k], w) for k, w in parts]))
        else:
            portfolios.append({"portfolio": name, "status": "missing_component"})

    write_csv(out / "robust_results.csv", robust)
    write_csv(out / "walkforward_results.csv", wf)
    write_csv(out / "cost_slippage_estimates.csv", costs)
    write_csv(out / "portfolio_mix_results.csv", portfolios)

    stress = ["# Stress trade analysis\n"]
    for label in ["mejor_global", "alternativa_defensiva", "sub_30_dd"]:
        if label in runs and label in equities:
            stress.append(top_trades_md(label, runs[label], equities[label]))
    (out / "stress_trade_analysis.md").write_text("\n".join(stress), encoding="utf-8")

    # Audit/limitations: read-only inference only.
    audit_lines = ["# Limitations\n", "- Validación read-only: no reoptimiza y no rerunea backtests.", "- Walk-forward aquí significa subperíodos con parámetros fijos; NO es walk-forward de optimización real.", "- Costos/slippage son post-trade estimados; si no hay columnas explícitas, quedan como approximation=true.", "- Execution timing: no se modifica motor; si manifest/notes no confirman same-close/next-close/next-open, se marca incierto."]
    notes = []
    for p in list(root.glob("reports/**/implementation_notes.md"))[:20]:
        txt = p.read_text(encoding="utf-8", errors="ignore")[:2000]
        if re.search("same-close|next-close|next-open|lookahead|daily close|guard|stop", txt, re.I): notes.append(str(p))
    execution_uncertain = True
    audit_lines.append(f"- implementation_notes con posibles pistas: {len(notes)}.")
    audit_lines.append("- execution_timing_uncertain=true")
    audit_lines.append("- requires_engine_change: validación estricta de timing/lookahead necesita instrumentar o extender motor en otra etapa.")
    (out / "limitations.md").write_text("\n".join(audit_lines), encoding="utf-8")

    best_single = max([r for r in robust if r.get("status") == "ok" and not r.get("incomplete")], key=lambda r: (r.get("calmar") or -999), default={})
    best_port = max([r for r in portfolios if r.get("status") == "ok"], key=lambda r: (r.get("calmar") or -999), default={})
    metric_ok = not any(r.get("metric_warning") for r in robust if r.get("status") == "ok")
    wf_ok = True
    cost_ok = not any(r.get("sensitive_to_costs") is True for r in costs if r.get("scenario") in ("costos_x2_slippage_x2", "costos_x2"))
    pass_fail = "PASS_READONLY_WITH_LIMITATIONS" if metric_ok and wf_ok and (best_single or best_port) else "FAIL_OR_INCOMPLETE"

    readme = f"""# README_ANALISIS_FINAL\n\nValidación robusta read-only para `HYP_REFINE_AUTO002_TOPN_6_V1` y variantes DDGRID.\n\nIMPORTANTE: esto no toca motor, configs ni runs existentes. El walk-forward es validación por subperíodos usando parámetros fijos; NO es walk-forward de optimización real.\n\n## Inventario y consistencia\n\nVer `robust_results.csv`. Incompletos quedan marcados como `incomplete=true`. Diferencias contra `metrics.json` quedan en columnas `abs_diff_*`, `rel_diff_*` y `metric_warning`.\n\n## Walk-forward read-only\n\nVer `walkforward_results.csv`. SPY solo se informa si hay benchmark disponible en datos leídos; no se inventa comparación.\n\n## Costos / slippage\n\nVer `cost_slippage_estimates.csv`. Las filas indican `approximation=true/false` y columnas usadas.\n\n## Carteras combinadas\n\nVer `portfolio_mix_results.csv`. DD20 encontrado: `{bool(dd20)}`.\n\n## Auditoría de ejecución\n\n`execution_timing_uncertain={str(execution_uncertain).lower()}`. `requires_engine_change=true` para validar estrictamente timing/lookahead sin inferencias.\n\n## Conclusión directa para Hernán\n\n- Mejor single por Calmar recalculado: `{best_single.get('label','N/D')}` (`{best_single.get('strategy_id','N/D')}`).\n- Mejor portfolio por Calmar recalculado: `{best_port.get('portfolio','N/D')}`.\n- La mejor global sigue como candidata principal si supera a las defensivas en Calmar/estabilidad de subperíodos; mirá robust_results + walkforward antes de promocionar.\n- La alternativa defensiva conviene más si reduce DD materialmente con pérdida menor de CAGR.\n- La sub -30 DD vale la pena solo si el límite psicológico/operativo de DD <30% pesa más que el CAGR perdido.\n- Una cartera combinada es preferible si mejora Calmar/DD frente a la mejor individual.\n- Señales de sobreoptimización: mirar concentración de performance por ventana y años malos.\n- Riesgo ejecución/lookahead: no confirmado, pero timing incierto en modo read-only.\n- Paper trading: conveniente solo después de revisar `limitations.md`; no promocionar baseline ni tocar motor todavía.\n- Próxima validación con motor: instrumentar timing de guards/stops, next-open/next-close, slippage/costos exactos y lookahead checks.\n\nPass/fail: `{pass_fail}`\nRequires engine change: `true`\n"""
    (out / "README_ANALISIS_FINAL.md").write_text(readme, encoding="utf-8")

    excel_path = out / "robustness_validation.xlsx"
    excel_written = False
    try:
        import openpyxl  # noqa
        with pd.ExcelWriter(excel_path, engine="openpyxl") as xw:
            pd.DataFrame(robust).to_excel(excel_writer=xw, sheet_name="robust_results", index=False)
            pd.DataFrame(wf).to_excel(excel_writer=xw, sheet_name="walkforward", index=False)
            pd.DataFrame(costs).to_excel(excel_writer=xw, sheet_name="cost_slippage", index=False)
            pd.DataFrame(portfolios).to_excel(excel_writer=xw, sheet_name="portfolios", index=False)
        excel_written = True
    except Exception:
        pass

    git = "unknown"
    try:
        import subprocess
        git = subprocess.check_output(["git", "status", "--short"], cwd=root, text=True, stderr=subprocess.DEVNULL).strip().replace("\n", "; ") or "clean"
    except Exception:
        pass
    print(f"Report dir: {out}")
    print(f"Excel: {excel_path if excel_written else 'not_available'}")
    print(f"Robust CSV: {out / 'robust_results.csv'}")
    print(f"Walkforward CSV: {out / 'walkforward_results.csv'}")
    print(f"Costs CSV: {out / 'cost_slippage_estimates.csv'}")
    print(f"Portfolio CSV: {out / 'portfolio_mix_results.csv'}")
    print(f"Stress analysis: {out / 'stress_trade_analysis.md'}")
    print(f"Best single: {best_single.get('label','N/D')}")
    print(f"Best portfolio: {best_port.get('portfolio','N/D')}")
    print(f"Pass/fail: {pass_fail}")
    print("Requires engine change: true")
    print("Recommendation: revisar README + limitations; paper trading solo tras validar timing/lookahead con motor")
    print(f"Git status: {git[:220]}")

if __name__ == "__main__":
    main()
