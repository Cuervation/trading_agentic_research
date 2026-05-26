"""DD20 yearly consistency repair phase.

Builds a diagnosis for the best DD20 near-miss and runs a causal batch whose
objective is to repair yearly SPY consistency without breaking DD20.
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtester.dd20_spy_beater import (
    DD20_MIN_TRADES,
    REFERENCE_STRATEGY_IDS,
    build_dd20_summary_markdown,
    row_from_dd20_audit_or_run,
    valid_dd20_rows,
    write_dd20_summary_csv,
    write_dd20_summary_markdown,
)
from scripts.run_dd20_spy_beater_daemon import (
    FULL_HISTORY_PARENT,
    assert_full_history_parent,
    config_path_for,
    set_dotted,
)
from scripts.run_dd_first_autofix_loop import _preflight, attempt_repair, classify_error, read_json, read_jsonl, write_json, write_jsonl
from scripts.run_dd_first_autonomous_daemon import _state_snapshot, assert_parent_baseline_unchanged

BASE_STRATEGY_ID = "HYP_DD20_SPY_DYN_65_45_25_0_V1"
BASE_CONFIG = "configs/generated/HYP_DD20_SPY_DYN_65_45_25_0_V1.json"
DEFAULT_PARENT_CONFIG = "configs/generated/HYP_AUTO_TIME_SERIES_MOMENTUM_SEED.json"
FAMILY = "dd20_spy_consistency_repair"
SUMMARY_COLUMNS = [
    "run_id",
    "strategy_id",
    "cagr",
    "spy_cagr",
    "excess_cagr",
    "max_drawdown",
    "calmar",
    "trades",
    "years_beating_spy",
    "years_losing_to_spy",
    "decision",
    "consistency_decision",
    "constraint_gap_score",
    "rejection_reason",
    "rank_under_constraint",
]
DIAG_COLUMNS = [
    "year",
    "strategy_return",
    "spy_return",
    "excess_return",
    "won_vs_spy",
    "avg_target_exposure",
    "months_in_strong",
    "months_in_neutral",
    "months_in_weak",
    "months_in_crisis",
    "trades_opened",
    "trades_closed",
    "max_dd_year",
]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run DD20 SPY consistency repair phase.")
    p.add_argument("--weekly-file", default="data/sp500_feature_store_weekly_master_260523155332.csv")
    p.add_argument("--daily-folder", default="data")
    p.add_argument("--parent-strategy-config", default=DEFAULT_PARENT_CONFIG)
    p.add_argument("--parent-run-id", default=FULL_HISTORY_PARENT)
    p.add_argument("--project-config", default="configs/project_config.json")
    p.add_argument("--strategy-registry", default="configs/strategy_registry.json")
    p.add_argument("--hypothesis-bank", default="bibliography/hypothesis_bank.jsonl")
    p.add_argument("--runs-dir", default="runs")
    p.add_argument("--reports-dir", default="reports")
    p.add_argument("--state-dir", default="state")
    p.add_argument("--batch-size", type=int, default=10)
    p.add_argument("--max-total-attempts", type=int, default=30)
    p.add_argument("--per-run-timeout-minutes", type=float, default=45.0)
    p.add_argument("--min-trades", type=int, default=DD20_MIN_TRADES)
    p.add_argument("--resume", action="store_true")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    parent_snapshot = _state_snapshot(args.state_dir)
    state = load_state(args.state_dir) if args.resume else {}
    state.update({"status": "running", "phase": "dd20_spy_consistency_repair", "parent_run_id": args.parent_run_id, "stop_reason": "", "last_error": ""})
    try:
        weekly_file, daily_folder, parent_run_id = _preflight(args)
        if parent_run_id != args.parent_run_id:
            parent_run_id = args.parent_run_id
        assert_full_history_parent(args.runs_dir, parent_run_id)
        assert_parent_baseline_unchanged(args.state_dir, parent_snapshot)
        base_run = find_latest_run_for_strategy(args.runs_dir, BASE_STRATEGY_ID)
        if base_run is None:
            raise FileNotFoundError(f"Base near-miss run not found for {BASE_STRATEGY_ID}")
        diagnosis_rows = write_diagnosis(base_run, weekly_file, args.reports_dir)
        ensure_repair_strategies(args)
    except Exception as exc:
        state.update({"status": "failed", "stop_reason": "preflight_or_diagnosis_failed", "last_error": str(exc)})
        save_state(args.state_dir, state)
        return 2

    specs = consistency_specs()[: args.batch_size]
    completed = set(state.get("completed_strategy_ids", [])) if args.resume else set()
    attempts = int(state.get("total_attempts", 0)) if args.resume else 0
    for item in specs:
        sid = item["strategy_id"]
        if sid in completed:
            continue
        if attempts >= args.max_total_attempts:
            state["stop_reason"] = "max_total_attempts_reached"
            break
        assert_parent_baseline_unchanged(args.state_dir, parent_snapshot)
        attempts += 1
        state["total_attempts"] = attempts
        state.setdefault("attempted_strategy_ids", []).append(sid)
        result = run_candidate(
            run_id=next_run_id(args.runs_dir, sid),
            strategy_id=sid,
            config_path=config_path_for(args.strategy_registry, sid),
            weekly_file=weekly_file,
            daily_folder=daily_folder,
            parent_run_id=parent_run_id,
            args=args,
        )
        if not result["ok"]:
            classification = classify_error(result["error"])
            repaired = attempt_repair(classification, config_path_for(args.strategy_registry, sid), set())
            state["last_error"] = f"{classification}: {result['error'][:500]}"
            state["failed_attempts"] = int(state.get("failed_attempts", 0)) + 1
            if repaired and attempts < args.max_total_attempts:
                attempts += 1
                result = run_candidate(
                    run_id=next_run_id(args.runs_dir, sid),
                    strategy_id=sid,
                    config_path=config_path_for(args.strategy_registry, sid),
                    weekly_file=weekly_file,
                    daily_folder=daily_folder,
                    parent_run_id=parent_run_id,
                    args=args,
                )
            if not result["ok"]:
                continue
        state.setdefault("completed_strategy_ids", []).append(sid)
        completed.add(sid)
        state["last_run_id"] = result["row"].get("run_id")
        update_reports(args, parent_run_id, diagnosis_rows, state)

    state["status"] = "completed"
    state["stop_reason"] = state.get("stop_reason") or "completed_10_strategy_consistency_batch"
    update_reports(args, parent_run_id, diagnosis_rows, state)
    print(f"DD20 consistency repair completed: attempts={state.get('total_attempts')} valid={state.get('valid_strategies')} stop={state.get('stop_reason')}")
    return 0


def consistency_specs() -> list[dict[str, Any]]:
    base = {
        "generation_axis": "dd20_spy_consistency_repair",
        "expected_effect": "Improve yearly SPY win/loss consistency while keeping DD20 and CAGR > SPY.",
        "falsification_rule": "Reject if max DD < -20, CAGR <= SPY, trades < 3000, or years W/L remains negative.",
        "empirical_basis": [{"strategy_id": BASE_STRATEGY_ID, "reason": "Best near-miss: DD20 passed and CAGR beat SPY, but years W/L was 13/15."}],
        "risk_of_overfit": "Medium: intentionally coarse regime exposure variants around one empirical near-miss.",
    }
    return [
        spec("HYP_DD20_SPY_DYN_70_45_25_0_V1", 70, 45, 25, 0, {}, ["risk_management.dynamic_regime_exposure_pct"], "Add upside only in strong regimes to win more bull-market years without increasing weak/crisis risk.", base),
        spec("HYP_DD20_SPY_DYN_75_45_25_0_V1", 75, 45, 25, 0, {}, ["risk_management.dynamic_regime_exposure_pct"], "Test a stronger bull-market exposure bump while preserving crisis zero.", base),
        spec("HYP_DD20_SPY_DYN_80_45_25_0_V1", 80, 45, 25, 0, {}, ["risk_management.dynamic_regime_exposure_pct"], "Push strong-regime upside to determine if consistency improves before DD breaks.", base),
        spec("HYP_DD20_SPY_DYN_65_50_25_0_V1", 65, 50, 25, 0, {}, ["risk_management.dynamic_regime_exposure_pct"], "Raise neutral exposure because lost years may occur when the regime is not classified strong yet.", base),
        spec("HYP_DD20_SPY_DYN_70_50_25_0_V1", 70, 50, 25, 0, {}, ["risk_management.dynamic_regime_exposure_pct"], "Combine selective strong upside with modest neutral repair.", base),
        spec("HYP_DD20_SPY_DYN_70_50_20_0_V1", 70, 50, 20, 0, {}, ["risk_management.dynamic_regime_exposure_pct"], "Offset neutral/strong exposure increase by lowering weak exposure.", base),
        spec("HYP_DD20_SPY_DYN_70_45_25_0_PARTIAL_25_33_V1", 70, 45, 25, 0, {"partial_take_profit": {"enabled": True, "gain_pct": 25, "sell_fraction": 0.33}}, ["risk_management.dynamic_regime_exposure_pct", "risk_management.partial_take_profit"], "Add strong-regime upside but harvest part of large winners to protect DD20.", base),
        spec("HYP_DD20_SPY_DYN_75_45_25_0_PARTIAL_25_33_V1", 75, 45, 25, 0, {"partial_take_profit": {"enabled": True, "gain_pct": 25, "sell_fraction": 0.33}}, ["risk_management.dynamic_regime_exposure_pct", "risk_management.partial_take_profit"], "Use more strong exposure with partial exits as the DD safety valve.", base),
        spec("HYP_DD20_SPY_DYN_75_50_25_0_EQUITY_GUARD_18_10_V1", 75, 50, 25, 0, {"equity_drawdown_guard": {"enabled": True, "stop_new_entries_drawdown_pct": -18, "resume_drawdown_pct": -10}}, ["risk_management.dynamic_regime_exposure_pct", "risk_management.equity_drawdown_guard"], "Repair bull/neutral participation with a soft portfolio-DD entry throttle.", base),
        spec("HYP_DD20_SPY_DYN_80_50_20_0_EQUITY_GUARD_18_10_V1", 80, 50, 20, 0, {"equity_drawdown_guard": {"enabled": True, "stop_new_entries_drawdown_pct": -18, "resume_drawdown_pct": -10}}, ["risk_management.dynamic_regime_exposure_pct", "risk_management.equity_drawdown_guard"], "Maximize strong/neutral upside while weak/crisis and equity guard defend the DD constraint.", base),
    ]


def spec(strategy_id: str, strong: int, neutral: int, weak: int, crisis: int, extras: dict[str, Any], changed: list[str], causal: str, base: dict[str, Any]) -> dict[str, Any]:
    risk_patch: dict[str, Any] = {
        "dynamic_regime_exposure_pct": {"strong": strong, "neutral": neutral, "weak": weak, "crisis": crisis},
        "max_gross_exposure_pct": neutral,
    }
    risk_patch.update(extras)
    out = dict(base)
    out.update({
        "strategy_id": strategy_id,
        "risk_patch": risk_patch,
        "changed_parameters": changed,
        "causal_mechanism": causal,
        "why_not_duplicate": f"{strategy_id} isolates a consistency-repair exposure/guard variant around {BASE_STRATEGY_ID}.",
    })
    return out


def ensure_repair_strategies(args: argparse.Namespace) -> None:
    registry = read_json(args.strategy_registry)
    existing = {s.get("strategy_id") for s in registry.get("strategies", [])}
    bank = read_jsonl(args.hypothesis_bank)
    existing_hyp = {h.get("hypothesis_id") for h in bank}
    base_cfg = read_json(BASE_CONFIG)
    for item in consistency_specs():
        sid = item["strategy_id"]
        cfg = deepcopy(base_cfg)
        cfg.update({
            "strategy_id": sid,
            "hypothesis_id": sid,
            "strategy_family": FAMILY,
            "evaluation_mode": "dd20_spy_beater",
            "generation_axis": "dd20_spy_consistency_repair",
            "parent_strategy_id": BASE_STRATEGY_ID,
            "parent_hypothesis_id": BASE_STRATEGY_ID,
            "claim": "Repair yearly SPY consistency after DD20 became reachable.",
            "causal_mechanism": item["causal_mechanism"],
            "expected_effect": item["expected_effect"],
            "falsification_rule": item["falsification_rule"],
            "changed_parameters": item["changed_parameters"],
            "empirical_basis": item["empirical_basis"],
            "why_not_duplicate": item["why_not_duplicate"],
            "risk_of_overfit": item["risk_of_overfit"],
        })
        cfg["risk_management"] = item["risk_patch"]
        cfg["strategy_overrides"] = {
            "risk_management": cfg.get("risk_management", {}),
            "market_filter": cfg.get("market_filter", {}),
            "ranking": cfg.get("ranking", {}),
            "risk_filters": cfg.get("risk_filters", {}),
        }
        out_path = Path("configs/generated") / f"{sid}.json"
        write_json(out_path, cfg)
        if sid not in existing:
            registry.setdefault("strategies", []).append({
                "strategy_id": sid,
                "strategy_family": FAMILY,
                "status": "candidate",
                "benchmark_ticker": "SPY",
                "config_path": str(out_path).replace("\\", "/"),
                "signal_frequency": "weekly",
                "execution_frequency": "daily",
                "rebalance_frequency": "monthly",
                "parent_strategy_id": BASE_STRATEGY_ID,
                "evaluation_mode": "dd20_spy_beater",
                "generation_axis": "dd20_spy_consistency_repair",
                "notes": "DD20_SPY_CONSISTENCY_REPAIR candidate.",
            })
        if sid not in existing_hyp:
            bank.append({
                "hypothesis_id": sid,
                "family": FAMILY,
                "status": "candidate",
                "evaluation_mode": "dd20_spy_beater",
                "generation_axis": "dd20_spy_consistency_repair",
                "parent_strategy_id": BASE_STRATEGY_ID,
                "parent_hypothesis_id": BASE_STRATEGY_ID,
                "causal_mechanism": item["causal_mechanism"],
                "expected_effect": item["expected_effect"],
                "falsification_rule": item["falsification_rule"],
                "changed_parameters": item["changed_parameters"],
                "empirical_basis": item["empirical_basis"],
                "why_not_duplicate": item["why_not_duplicate"],
                "risk_of_overfit": item["risk_of_overfit"],
                "strategy_overrides": cfg["strategy_overrides"],
            })
    write_json(args.strategy_registry, registry)
    write_jsonl(args.hypothesis_bank, bank)


def write_diagnosis(base_run: Path, weekly_file: str, reports_dir: str) -> list[dict[str, Any]]:
    yearly = read_csv_flexible(base_run / "spy_comparison_yearly.csv")
    monthly = read_csv_flexible(base_run / "spy_comparison_monthly.csv")
    equity = read_csv_flexible(base_run / "equity_curve.csv")
    trades = read_csv_flexible(base_run / "trades.csv")
    cfg = read_json(BASE_CONFIG)
    exposure = yearly_exposure_profile(weekly_file, cfg)

    equity["date"] = pd.to_datetime(equity["date"], errors="coerce")
    equity["year"] = equity["date"].dt.year
    equity["year_peak"] = equity.groupby("year")["equity"].cummax()
    equity["dd"] = ((equity["equity"] / equity["year_peak"]) - 1.0) * 100.0
    year_dd = equity.groupby("year")["dd"].min().to_dict()

    trades["entry_date"] = pd.to_datetime(trades.get("entry_date"), errors="coerce")
    trades["exit_date"] = pd.to_datetime(trades.get("exit_date"), errors="coerce")
    opened = trades.dropna(subset=["entry_date"]).groupby(trades["entry_date"].dt.year).size().to_dict()
    closed = trades.dropna(subset=["exit_date"]).groupby(trades["exit_date"].dt.year).size().to_dict()

    rows: list[dict[str, Any]] = []
    for _, row in yearly.sort_values("year").iterrows():
        year = int(row["year"])
        strat = float(row.get("strategy_return_pct", 0.0))
        spy = float(row.get("spy_return_pct", 0.0))
        excess = float(row.get("excess_return_pct", strat - spy))
        exp = exposure.get(year, {})
        rows.append({
            "year": year,
            "strategy_return": strat,
            "spy_return": spy,
            "excess_return": excess,
            "won_vs_spy": bool(excess > 0),
            "avg_target_exposure": exp.get("avg_target_exposure", ""),
            "months_in_strong": exp.get("months_in_strong", 0),
            "months_in_neutral": exp.get("months_in_neutral", 0),
            "months_in_weak": exp.get("months_in_weak", 0),
            "months_in_crisis": exp.get("months_in_crisis", 0),
            "trades_opened": int(opened.get(year, 0)),
            "trades_closed": int(closed.get(year, 0)),
            "max_dd_year": year_dd.get(year, ""),
        })

    csv_path = Path(reports_dir) / "dd20_spy_consistency_diagnosis.csv"
    write_csv(csv_path, rows, DIAG_COLUMNS)
    md_path = Path(reports_dir) / "dd20_spy_consistency_diagnosis.md"
    md_path.write_text(build_diagnosis_md(rows, monthly), encoding="utf-8")
    return rows


def yearly_exposure_profile(weekly_file: str, cfg: dict[str, Any]) -> dict[int, dict[str, Any]]:
    weekly = read_csv_flexible(Path(weekly_file))
    if "date" not in weekly.columns and "signal_date" in weekly.columns:
        weekly["date"] = weekly["signal_date"]
    weekly["date"] = pd.to_datetime(weekly["date"], errors="coerce")
    spy = weekly[weekly["ticker"] == "SPY"].copy()
    if spy.empty:
        spy = weekly.copy()
    month_key = spy["date"].dt.to_period("M")
    decision_dates = spy.groupby(month_key)["date"].max().sort_values().tolist()
    risk = cfg.get("risk_management", {})
    dyn = risk.get("dynamic_regime_exposure_pct", {})
    rows = []
    for date in decision_dates:
        row = spy[spy["date"] == date].iloc[0]
        regime = classify_regime(row)
        rows.append({"year": int(date.year), "regime": regime, "target_exposure": float(dyn.get(regime, dyn.get("neutral", 45)) or 45)})
    df = pd.DataFrame(rows)
    out: dict[int, dict[str, Any]] = {}
    for year, group in df.groupby("year"):
        payload = {"avg_target_exposure": float(group["target_exposure"].mean())}
        counts = group["regime"].value_counts().to_dict()
        for regime in ["strong", "neutral", "weak", "crisis"]:
            payload[f"months_in_{regime}"] = int(counts.get(regime, 0))
        out[int(year)] = payload
    return out


def classify_regime(row: pd.Series) -> str:
    close_vs_52 = f(row.get("spy_close_vs_sma52w_pct", row.get("close_vs_sma52w_pct")))
    close_vs_20 = f(row.get("spy_close_vs_sma20w_pct", row.get("close_vs_sma20w_pct")))
    dd_26 = f(row.get("spy_drawdown_from_high_26w_pct", row.get("drawdown_from_high_26w_pct")))
    if dd_26 <= -20 or close_vs_52 <= -20:
        return "crisis"
    if close_vs_52 > 0 and close_vs_20 > 0:
        return "strong"
    if close_vs_52 > 0 or close_vs_20 > 0:
        return "neutral"
    return "weak"


def build_diagnosis_md(rows: list[dict[str, Any]], monthly: pd.DataFrame) -> str:
    lost = [r for r in rows if not r["won_vs_spy"]]
    bull_lost = [r for r in lost if f(r["spy_return"]) >= 10]
    low_exp_lost = [r for r in lost if f(r["avg_target_exposure"]) <= 45]
    lines = [
        "# DD20 SPY Consistency Diagnosis",
        "",
        f"Base near-miss: `{BASE_STRATEGY_ID}`.",
        "",
        "## Lost years vs SPY",
        "",
        "| year | strategy | SPY | excess | avg exposure | regimes S/N/W/C | opened/closed | max DD year |",
        "|---:|---:|---:|---:|---:|:---|:---|---:|",
    ]
    for r in lost:
        lines.append(
            f"| {r['year']} | {f(r['strategy_return']):.2f}% | {f(r['spy_return']):.2f}% | {f(r['excess_return']):.2f}% | {f(r['avg_target_exposure']):.2f}% | {r['months_in_strong']}/{r['months_in_neutral']}/{r['months_in_weak']}/{r['months_in_crisis']} | {r['trades_opened']}/{r['trades_closed']} | {f(r['max_dd_year']):.2f}% |"
        )
    lines += [
        "",
        "## Interpretation",
        f"- Lost years: {len(lost)}. Bull-market lost years (SPY >= 10%): {len(bull_lost)}.",
        f"- Lost years with average target exposure <= 45%: {len(low_exp_lost)}.",
        "- If lost years cluster in strong/neutral regimes, the likely problem is lack of exposure, not bad exits.",
        "- If lost years have many closed trades and high drawdown, exits/risk control are implicated.",
        "- Technical note: this phase now reads embedded `spy_*` regime fields when no literal `SPY` row exists in the feature store; otherwise strong/neutral exposure variants become no-ops.",
    ]
    if lost:
        avg_exp = sum(f(r["avg_target_exposure"]) for r in lost) / len(lost)
        avg_spy = sum(f(r["spy_return"]) for r in lost) / len(lost)
        lines.append(f"- Average lost-year target exposure: {avg_exp:.2f}%; average SPY return in lost years: {avg_spy:.2f}%.")
    return "\n".join(lines) + "\n"


def run_candidate(*, run_id: str, strategy_id: str, config_path: str, weekly_file: str, daily_folder: str, parent_run_id: str, args: argparse.Namespace) -> dict[str, Any]:
    commands = [
        [sys.executable, "scripts/run_backtest.py", "--weekly-file", weekly_file, "--daily-folder", daily_folder, "--strategy-config", config_path, "--project-config", args.project_config, "--run-id", run_id, "--runs-dir", args.runs_dir, "--parent-run-id", parent_run_id, "--parent-strategy-config", args.parent_strategy_config],
        [sys.executable, "scripts/evaluate_candidate.py", "--run-id", run_id, "--runs-dir", args.runs_dir, "--reports-dir", args.reports_dir, "--evaluation-mode", "dd20_spy_beater", "--hypothesis-id", strategy_id, "--family", FAMILY, "--state-dir", args.state_dir, "--parent-run-id", parent_run_id, "--min-trades", str(args.min_trades)],
    ]
    timeout_seconds = float(args.per_run_timeout_minutes or 0) * 60 or None
    for command in commands:
        try:
            result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False, timeout=timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            return {"ok": False, "error": f"command_timeout: {' '.join(command)}\n{exc.stderr or exc.stdout or ''}".strip()}
        if result.returncode != 0:
            return {"ok": False, "error": (result.stderr or result.stdout or "").strip()}
    row = row_from_dd20_audit_or_run(Path(args.runs_dir) / run_id, parent_run_dir=Path(args.runs_dir) / parent_run_id, min_trades=args.min_trades)
    return {"ok": True, "row": row}


def update_reports(args: argparse.Namespace, parent_run_id: str, diagnosis_rows: list[dict[str, Any]], state: dict[str, Any]) -> None:
    all_rows = scan_dd20_rows(args.runs_dir, parent_run_id, args.min_trades)
    write_dd20_summary_csv(Path(args.reports_dir) / "dd20_spy_beater_summary.csv", all_rows)
    write_dd20_summary_markdown(Path(args.reports_dir) / "dd20_spy_beater_summary.md", all_rows)
    repair_rows = [r for r in all_rows if str(r.get("strategy_id", "")).startswith("HYP_DD20_SPY_DYN_") and is_repair_strategy(str(r.get("strategy_id", "")))]
    write_consistency_summary(args.reports_dir, repair_rows)
    valid = consistency_valid_rows(repair_rows)
    state["valid_strategies"] = len(valid)
    state["best_valid_strategy"] = valid[0] if valid else None
    state["best_near_miss"] = best_near_miss(repair_rows)
    state["diagnosis_lost_years"] = len([r for r in diagnosis_rows if not r["won_vs_spy"]])
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    save_state(args.state_dir, state)
    update_learning(args.state_dir, repair_rows)


def is_repair_strategy(strategy_id: str) -> bool:
    return strategy_id in {s["strategy_id"] for s in consistency_specs()}


def scan_dd20_rows(runs_dir: str, parent_run_id: str, min_trades: int) -> list[dict[str, Any]]:
    root = Path(runs_dir)
    by_strategy: dict[str, dict[str, Any]] = {}
    run_dirs = sorted([p for p in root.iterdir()] if root.exists() else [], key=lambda p: p.stat().st_mtime)
    for run_dir in run_dirs:
        if not run_dir.is_dir() or not (run_dir / "run_manifest.json").exists():
            continue
        try:
            manifest = read_json(run_dir / "run_manifest.json")
            sid = str(manifest.get("strategy_id") or "")
            if "DD20_SPY" not in sid and sid not in set(REFERENCE_STRATEGY_IDS):
                continue
            by_strategy[sid] = row_from_dd20_audit_or_run(run_dir, parent_run_dir=Path(runs_dir) / parent_run_id, min_trades=min_trades)
        except Exception:
            continue
    return list(by_strategy.values())


def consistency_decision(row: dict[str, Any]) -> str:
    dd = f(row.get("max_drawdown"))
    cagr = f(row.get("cagr"))
    spy = f(row.get("spy_cagr"))
    calmar = f(row.get("calmar"))
    trades = i(row.get("trades"))
    yw = i(row.get("years_beating_spy"))
    yl = i(row.get("years_losing_to_spy"))
    if not (dd >= -20 and cagr > spy and trades >= DD20_MIN_TRADES and yw >= yl):
        return "rejected"
    if cagr >= 9 and yw >= 16 and yl <= 12 and calmar >= 0.45:
        return "excellent_candidate"
    if cagr >= spy + 1 and yw > yl and calmar >= 0.40:
        return "strong_candidate"
    return "valid_candidate"


def consistency_valid_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = [dict(r, consistency_decision=consistency_decision(r), constraint_gap_score=constraint_gap_score(r)) for r in rows]
    return sorted([r for r in out if r["consistency_decision"] != "rejected"], key=lambda r: (-f(r.get("cagr")), -f(r.get("calmar")), -f(r.get("max_drawdown"))))


def write_consistency_summary(reports_dir: str, rows: list[dict[str, Any]]) -> None:
    rows = [dict(r, consistency_decision=consistency_decision(r), constraint_gap_score=constraint_gap_score(r)) for r in rows]
    valid = consistency_valid_rows(rows)
    rank_by_run = {r.get("run_id"): n for n, r in enumerate(valid, start=1)}
    for row in rows:
        row["rank_under_constraint"] = rank_by_run.get(row.get("run_id"), "")
    write_csv(Path(reports_dir) / "dd20_spy_consistency_repair_summary.csv", rows, SUMMARY_COLUMNS)
    Path(reports_dir, "dd20_spy_consistency_repair_summary.md").write_text(build_consistency_md(rows, valid), encoding="utf-8")


def build_consistency_md(rows: list[dict[str, Any]], valid: list[dict[str, Any]]) -> str:
    near = best_near_miss(rows)
    base = next((r for r in rows if r.get("strategy_id") == BASE_STRATEGY_ID), None)
    lines = ["# DD20 SPY Consistency Repair Summary", "", "## Valid candidates", ""]
    if valid:
        lines += ["| rank | strategy_id | CAGR | SPY CAGR | DD | years W/L | Calmar | trades |", "|---:|:---|---:|---:|---:|:---|---:|---:|"]
        for r in valid:
            lines.append(f"| {r.get('rank_under_constraint','')} | `{r.get('strategy_id')}` | {f(r.get('cagr')):.4f}% | {f(r.get('spy_cagr')):.4f}% | {f(r.get('max_drawdown')):.4f}% | {i(r.get('years_beating_spy'))}/{i(r.get('years_losing_to_spy'))} | {f(r.get('calmar')):.4f} | {i(r.get('trades'))} |")
    else:
        lines.append("- none")
    lines += ["", "## Best near-candidate", ""]
    if near:
        lines.append(f"- `{near.get('strategy_id')}`: CAGR {f(near.get('cagr')):.4f}%, DD {f(near.get('max_drawdown')):.4f}%, years W/L {i(near.get('years_beating_spy'))}/{i(near.get('years_losing_to_spy'))}, gap {f(near.get('constraint_gap_score')):.4f}.")
    lines += ["", f"## Comparison against `{BASE_STRATEGY_ID}`", ""]
    if base:
        lines.append(f"- Base: CAGR {f(base.get('cagr')):.4f}%, DD {f(base.get('max_drawdown')):.4f}%, years W/L {i(base.get('years_beating_spy'))}/{i(base.get('years_losing_to_spy'))}.")
    if near:
        lines.append(f"- Best repair: CAGR {f(near.get('cagr')):.4f}%, DD {f(near.get('max_drawdown')):.4f}%, years W/L {i(near.get('years_beating_spy'))}/{i(near.get('years_losing_to_spy'))}.")
    lines += ["", "## All repair strategies", "", "| strategy_id | CAGR | SPY CAGR | DD | years W/L | decision | gap | reason |", "|:---|---:|---:|---:|:---|:---|---:|:---|"]
    for r in sorted(rows, key=lambda x: (f(x.get("constraint_gap_score")), -f(x.get("cagr")))):
        lines.append(f"| `{r.get('strategy_id')}` | {f(r.get('cagr')):.4f}% | {f(r.get('spy_cagr')):.4f}% | {f(r.get('max_drawdown')):.4f}% | {i(r.get('years_beating_spy'))}/{i(r.get('years_losing_to_spy'))} | {r.get('consistency_decision')} | {f(r.get('constraint_gap_score')):.4f} | {r.get('rejection_reason','')} |")
    return "\n".join(lines) + "\n"


def best_near_miss(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not rows:
        return None
    enriched = [dict(r, consistency_decision=consistency_decision(r), constraint_gap_score=constraint_gap_score(r)) for r in rows]
    return sorted(enriched, key=lambda r: (f(r.get("constraint_gap_score")), -f(r.get("cagr"))))[0]


def constraint_gap_score(row: dict[str, Any]) -> float:
    dd_gap = max(0.0, -20.0 - f(row.get("max_drawdown"))) * 10.0
    cagr_gap = max(0.0, f(row.get("spy_cagr")) - f(row.get("cagr"))) * 4.0
    trade_gap = max(0.0, float(DD20_MIN_TRADES - i(row.get("trades"))) / DD20_MIN_TRADES)
    year_gap = max(0.0, float(i(row.get("years_losing_to_spy")) - i(row.get("years_beating_spy"))))
    return round(dd_gap + cagr_gap + trade_gap + year_gap, 6)


def update_learning(state_dir: str, rows: list[dict[str, Any]]) -> None:
    path = Path(state_dir) / "dd20_spy_beater_learning.json"
    learning = read_json(path) if path.exists() else {"events": [], "recommendations": []}
    near = best_near_miss(rows)
    events = [event for event in learning.get("events", []) if event.get("phase") != "dd20_spy_consistency_repair"]
    events.append({
        "phase": "dd20_spy_consistency_repair",
        "best_near_miss": near,
        "lesson": "Yearly consistency repair should prefer strong/neutral exposure increases only if DD remains >= -20.",
    })
    learning["events"] = events[-20:]
    learning["recommendations"] = [
        "If DD remains under -20 with improved years W/L, expand around that strong/neutral exposure.",
        "If DD breaks near -22, lower weak exposure before adding exits.",
        "Do not continue variants worse than -22 except as causal evidence.",
    ]
    write_json(path, learning)


def find_latest_run_for_strategy(runs_dir: str, strategy_id: str) -> Path | None:
    root = Path(runs_dir)
    candidates = []
    for run_dir in root.iterdir() if root.exists() else []:
        manifest = run_dir / "run_manifest.json"
        if not manifest.exists():
            continue
        try:
            if read_json(manifest).get("strategy_id") == strategy_id:
                candidates.append(run_dir)
        except Exception:
            pass
    return sorted(candidates, key=lambda p: p.stat().st_mtime, reverse=True)[0] if candidates else None


def next_run_id(runs_dir: str, strategy_id: str) -> str:
    stem = f"DD20CONSIST_{strategy_id}"[:120]
    candidate = stem
    n = 1
    while (Path(runs_dir) / candidate).exists():
        n += 1
        candidate = f"{stem}_{n}"
    return candidate


def read_csv_flexible(path: Path) -> pd.DataFrame:
    with path.open("r", encoding="utf-8-sig") as fh:
        first = next((line for line in fh if line.strip()), "")
    return pd.read_csv(path, sep=";", decimal=",") if ";" in first else pd.read_csv(path)


def write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore", delimiter=";")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: csv_value(row.get(k, "")) for k in columns})


def load_state(state_dir: str) -> dict[str, Any]:
    path = Path(state_dir) / "dd20_spy_beater_state.json"
    return read_json(path) if path.exists() else {}


def save_state(state_dir: str, state: dict[str, Any]) -> None:
    write_json(Path(state_dir) / "dd20_spy_beater_state.json", state)


def f(value: Any) -> float:
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return 0.0


def i(value: Any) -> int:
    try:
        return int(float(str(value).replace(",", ".")))
    except (TypeError, ValueError):
        return 0


def csv_value(value: Any) -> Any:
    if isinstance(value, float):
        return str(value).replace(".", ",")
    return value


if __name__ == "__main__":
    raise SystemExit(main())
