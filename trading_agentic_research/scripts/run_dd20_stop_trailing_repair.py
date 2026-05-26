"""DD20 stop-loss/trailing repair batch.

Tests whether per-position stop loss and gain-activated trailing exits can keep
DD20 while recovering trade count from the equity-guard near-miss.
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

from backtester.dd20_spy_beater import DD20_MIN_TRADES, row_from_dd20_audit_or_run, write_dd20_summary_csv, write_dd20_summary_markdown
from scripts.run_dd20_spy_beater_daemon import FULL_HISTORY_PARENT, assert_full_history_parent, config_path_for
from scripts.run_dd20_spy_consistency_repair import read_csv_flexible
from scripts.run_dd_first_autofix_loop import _preflight, attempt_repair, classify_error, read_json, read_jsonl, write_json, write_jsonl
from scripts.run_dd_first_autonomous_daemon import _state_snapshot, assert_parent_baseline_unchanged

BASE_STRATEGY_ID = "HYP_DD20_SPY_DYN_80_50_20_0_EQUITY_GUARD_18_10_V1"
BASE_CONFIG = "configs/generated/HYP_DD20_SPY_DYN_80_50_20_0_EQUITY_GUARD_18_10_V1.json"
DEFAULT_PARENT_CONFIG = "configs/generated/HYP_AUTO_TIME_SERIES_MOMENTUM_SEED.json"
FAMILY = "dd20_stop_trailing_repair"
SUMMARY_COLUMNS = [
    "run_id", "strategy_id", "cagr", "spy_cagr", "excess_cagr", "max_drawdown", "calmar", "trades",
    "years_beating_spy", "years_losing_to_spy", "stop_loss_pct", "trailing_stop_pct", "trailing_activation_gain_pct",
    "stop_loss_exit_count", "trailing_exit_count", "breakeven_exit_count", "profit_lock_exit_count", "partial_exit_count",
    "rank_exit_count", "decision", "rejection_reason",
]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run DD20 stop/trailing repair batch.")
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
    state.update({"status": "running", "phase": "dd20_stop_trailing_repair", "parent_run_id": args.parent_run_id, "stop_reason": "", "last_error": ""})
    try:
        weekly_file, daily_folder, parent_run_id = _preflight(args)
        if parent_run_id != args.parent_run_id:
            parent_run_id = args.parent_run_id
        assert_full_history_parent(args.runs_dir, parent_run_id)
        assert_parent_baseline_unchanged(args.state_dir, parent_snapshot)
        ensure_strategies(args)
    except Exception as exc:
        state.update({"status": "failed", "stop_reason": "preflight_failed", "last_error": str(exc)})
        save_state(args.state_dir, state)
        return 2

    attempts = int(state.get("total_attempts", 0)) if args.resume else 0
    completed = set(state.get("completed_strategy_ids", [])) if args.resume else set()
    for item in stop_trailing_specs()[: args.batch_size]:
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
        result = run_candidate(next_run_id(args.runs_dir, sid), sid, config_path_for(args.strategy_registry, sid), weekly_file, daily_folder, parent_run_id, args)
        if not result["ok"]:
            classification = classify_error(result["error"])
            repaired = attempt_repair(classification, config_path_for(args.strategy_registry, sid), set())
            state["failed_attempts"] = int(state.get("failed_attempts", 0)) + 1
            state["last_error"] = f"{classification}: {result['error'][:500]}"
            if repaired and attempts < args.max_total_attempts:
                attempts += 1
                result = run_candidate(next_run_id(args.runs_dir, sid), sid, config_path_for(args.strategy_registry, sid), weekly_file, daily_folder, parent_run_id, args)
            if not result["ok"]:
                continue
        state.setdefault("completed_strategy_ids", []).append(sid)
        state["last_run_id"] = result["row"].get("run_id")
        update_reports(args, parent_run_id, state)

    state["status"] = "completed"
    state["stop_reason"] = state.get("stop_reason") or "completed_10_stop_trailing_batch"
    update_reports(args, args.parent_run_id, state)
    print(f"DD20 stop/trailing repair completed: attempts={state.get('total_attempts')} valid={state.get('valid_strategies')} stop={state.get('stop_reason')}")
    return 0


def stop_trailing_specs() -> list[dict[str, Any]]:
    base = {
        "generation_axis": "dd20_stop_trailing_repair",
        "expected_effect": "Keep DD20 while restoring trade count/CAGR by replacing blunt equity throttling with position-level exits.",
        "falsification_rule": "Reject if DD < -20, CAGR <= SPY, trades < 3000 for valid candidates, or years W/L turns negative.",
        "empirical_basis": [{"strategy_id": BASE_STRATEGY_ID, "reason": "Near-valid DD20 candidate with CAGR > SPY and years W/L 14/14, but only 1699 trades."}],
        "risk_of_overfit": "Medium: exit thresholds are coarse and causal, but per-position stops can overfit crash paths.",
    }
    return [
        spec("HYP_DD20_STOP_DYN8050200_GUARD1810_SL10_V1", {"stop_loss_pct": 10}, "Stop loss 10% may cut losers early enough to preserve DD20 without further blocking entries.", ["risk_management.stop_loss_pct"], base),
        spec("HYP_DD20_STOP_DYN8050200_GUARD1810_SL12_V1", {"stop_loss_pct": 12}, "Stop loss 12% gives positions more room while still limiting single-name damage.", ["risk_management.stop_loss_pct"], base),
        spec("HYP_DD20_STOP_DYN8050200_GUARD1810_SL15_V1", {"stop_loss_pct": 15}, "Stop loss 15% tests whether looser loss control avoids churn and preserves CAGR.", ["risk_management.stop_loss_pct"], base),
        spec("HYP_DD20_TRAIL_DYN8050200_GUARD1810_TR15_ACT10_V1", {"trailing_stop_pct": 15, "trailing_activation_gain_pct": 10}, "Trailing after 10% gain protects winners without stopping early noise.", ["risk_management.trailing_stop_pct", "risk_management.trailing_activation_gain_pct"], base),
        spec("HYP_DD20_TRAIL_DYN8050200_GUARD1810_TR18_ACT10_V1", {"trailing_stop_pct": 18, "trailing_activation_gain_pct": 10}, "Looser trailing may preserve CAGR while still cutting winner giveback.", ["risk_management.trailing_stop_pct", "risk_management.trailing_activation_gain_pct"], base),
        spec("HYP_DD20_TRAIL_DYN8050200_GUARD1810_TR20_ACT15_V1", {"trailing_stop_pct": 20, "trailing_activation_gain_pct": 15}, "Only trail after meaningful profit to avoid churn in ordinary volatility.", ["risk_management.trailing_stop_pct", "risk_management.trailing_activation_gain_pct"], base),
        spec("HYP_DD20_STOPTRAIL_DYN8050200_GUARD1810_SL12_TR18_ACT10_V1", {"stop_loss_pct": 12, "trailing_stop_pct": 18, "trailing_activation_gain_pct": 10}, "Combine moderate loss cap with winner trailing under the proven guard.", ["risk_management.stop_loss_pct", "risk_management.trailing_stop_pct", "risk_management.trailing_activation_gain_pct"], base),
        spec("HYP_DD20_STOPTRAIL_DYN8050200_GUARD1810_SL15_TR18_ACT10_V1", {"stop_loss_pct": 15, "trailing_stop_pct": 18, "trailing_activation_gain_pct": 10}, "Looser loss cap plus trailing tests lower churn under the same DD guard.", ["risk_management.stop_loss_pct", "risk_management.trailing_stop_pct", "risk_management.trailing_activation_gain_pct"], base),
        spec("HYP_DD20_STOPTRAIL_DYN8050200_GUARD18_12_SL12_TR18_ACT10_V1", {"equity_drawdown_guard": {"enabled": True, "stop_new_entries_drawdown_pct": -18, "resume_drawdown_pct": -12}, "stop_loss_pct": 12, "trailing_stop_pct": 18, "trailing_activation_gain_pct": 10}, "Relax guard resume threshold to recover trades while stops defend drawdown.", ["risk_management.equity_drawdown_guard", "risk_management.stop_loss_pct", "risk_management.trailing_stop_pct", "risk_management.trailing_activation_gain_pct"], base),
        spec("HYP_DD20_STOPTRAIL_DYN8050200_NO_GUARD_SL12_TR18_ACT10_V1", {"equity_drawdown_guard": None, "stop_loss_pct": 12, "trailing_stop_pct": 18, "trailing_activation_gain_pct": 10}, "Remove portfolio entry guard and rely on position-level exits to recover trade count.", ["risk_management.equity_drawdown_guard", "risk_management.stop_loss_pct", "risk_management.trailing_stop_pct", "risk_management.trailing_activation_gain_pct"], base),
    ]


def spec(strategy_id: str, risk_overrides: dict[str, Any], causal: str, changed: list[str], base: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    out.update({"strategy_id": strategy_id, "risk_overrides": risk_overrides, "causal_mechanism": causal, "changed_parameters": changed, "why_not_duplicate": f"{strategy_id} tests a distinct stop/trailing repair axis around {BASE_STRATEGY_ID}."})
    return out


def ensure_strategies(args: argparse.Namespace) -> None:
    registry = read_json(args.strategy_registry)
    existing = {s.get("strategy_id") for s in registry.get("strategies", [])}
    bank = read_jsonl(args.hypothesis_bank)
    existing_hyp = {h.get("hypothesis_id") for h in bank}
    base_cfg = read_json(BASE_CONFIG)
    for item in stop_trailing_specs():
        sid = item["strategy_id"]
        cfg = deepcopy(base_cfg)
        cfg.update({
            "strategy_id": sid,
            "hypothesis_id": sid,
            "strategy_family": FAMILY,
            "evaluation_mode": "dd20_spy_beater",
            "generation_axis": "dd20_stop_trailing_repair",
            "parent_strategy_id": BASE_STRATEGY_ID,
            "parent_hypothesis_id": BASE_STRATEGY_ID,
            "claim": "Use position-level exits to preserve DD20 while recovering trade count.",
            "causal_mechanism": item["causal_mechanism"],
            "expected_effect": item["expected_effect"],
            "falsification_rule": item["falsification_rule"],
            "changed_parameters": item["changed_parameters"],
            "empirical_basis": item["empirical_basis"],
            "why_not_duplicate": item["why_not_duplicate"],
            "risk_of_overfit": item["risk_of_overfit"],
        })
        risk = deepcopy(base_cfg.get("risk_management", {}))
        for key, value in item["risk_overrides"].items():
            if value is None:
                risk.pop(key, None)
            else:
                risk[key] = value
        cfg["risk_management"] = risk
        cfg["strategy_overrides"] = {"risk_management": risk, "market_filter": cfg.get("market_filter", {}), "ranking": cfg.get("ranking", {}), "risk_filters": cfg.get("risk_filters", {})}
        out_path = Path("configs/generated") / f"{sid}.json"
        write_json(out_path, cfg)
        if sid not in existing:
            registry.setdefault("strategies", []).append({"strategy_id": sid, "strategy_family": FAMILY, "status": "candidate", "benchmark_ticker": "SPY", "config_path": str(out_path).replace("\\", "/"), "signal_frequency": "weekly", "execution_frequency": "daily", "rebalance_frequency": "monthly", "parent_strategy_id": BASE_STRATEGY_ID, "evaluation_mode": "dd20_spy_beater", "generation_axis": "dd20_stop_trailing_repair", "notes": "DD20_STOP_TRAILING_REPAIR candidate."})
        if sid not in existing_hyp:
            bank.append({"hypothesis_id": sid, "family": FAMILY, "status": "candidate", "evaluation_mode": "dd20_spy_beater", "generation_axis": "dd20_stop_trailing_repair", "parent_strategy_id": BASE_STRATEGY_ID, "parent_hypothesis_id": BASE_STRATEGY_ID, "causal_mechanism": item["causal_mechanism"], "expected_effect": item["expected_effect"], "falsification_rule": item["falsification_rule"], "changed_parameters": item["changed_parameters"], "empirical_basis": item["empirical_basis"], "why_not_duplicate": item["why_not_duplicate"], "risk_of_overfit": item["risk_of_overfit"], "strategy_overrides": cfg["strategy_overrides"]})
    write_json(args.strategy_registry, registry)
    write_jsonl(args.hypothesis_bank, bank)


def run_candidate(run_id: str, strategy_id: str, config_path: str, weekly_file: str, daily_folder: str, parent_run_id: str, args: argparse.Namespace) -> dict[str, Any]:
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


def update_reports(args: argparse.Namespace, parent_run_id: str, state: dict[str, Any]) -> None:
    all_rows = scan_rows(args.runs_dir, parent_run_id, args.min_trades)
    write_dd20_summary_csv(Path(args.reports_dir) / "dd20_spy_beater_summary.csv", all_rows)
    write_dd20_summary_markdown(Path(args.reports_dir) / "dd20_spy_beater_summary.md", all_rows)
    rows = [enrich_row(args, r) for r in all_rows if is_stop_trailing_strategy(str(r.get("strategy_id", "")))]
    write_csv(Path(args.reports_dir) / "dd20_stop_trailing_repair_summary.csv", rows, SUMMARY_COLUMNS)
    Path(args.reports_dir, "dd20_stop_trailing_repair_summary.md").write_text(build_markdown(rows), encoding="utf-8")
    Path(args.reports_dir, "dd20_best_so_far.md").write_text(build_best_so_far(all_rows, rows), encoding="utf-8")
    valid = [r for r in rows if decision(r) in {"valid_candidate", "strong_candidate"}]
    near = best_near_valid(rows)
    state["status"] = "running"
    state["phase"] = "dd20_stop_trailing_repair"
    state["valid_strategies"] = len(valid)
    state["best_valid_strategy"] = sorted(valid, key=lambda r: (-f(r.get("cagr")), -f(r.get("calmar"))))[0] if valid else None
    state["best_near_miss"] = near
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    save_state(args.state_dir, state)
    update_learning(args.state_dir, rows)


def is_stop_trailing_strategy(strategy_id: str) -> bool:
    return strategy_id in {s["strategy_id"] for s in stop_trailing_specs()}


def scan_rows(runs_dir: str, parent_run_id: str, min_trades: int) -> list[dict[str, Any]]:
    root = Path(runs_dir)
    wanted = {s["strategy_id"] for s in stop_trailing_specs()} | {
        BASE_STRATEGY_ID,
        "HYP_DD20_SPY_DYN_65_45_25_0_V1",
        "HYP_DD_FIRST_AUTO002_DYN_EXPOSURE_65_55_45_25_V1",
        "HYP_DD_FIRST_AUTO002_EXPOSURE_50_V1",
        "HYP_DD_FIRST_AUTO002_EXPOSURE_60_V1",
    }
    by_strategy: dict[str, dict[str, Any]] = {}
    run_dirs = sorted([p for p in root.iterdir()] if root.exists() else [], key=lambda p: p.stat().st_mtime)
    for run_dir in run_dirs:
        manifest = run_dir / "run_manifest.json"
        if not run_dir.is_dir() or not manifest.exists():
            continue
        try:
            sid = str(read_json(manifest).get("strategy_id") or "")
            if sid not in wanted:
                continue
            by_strategy[sid] = row_from_dd20_audit_or_run(run_dir, parent_run_dir=Path(runs_dir) / parent_run_id, min_trades=min_trades)
        except Exception:
            continue
    return list(by_strategy.values())


def enrich_row(args: argparse.Namespace, row: dict[str, Any]) -> dict[str, Any]:
    sid = str(row.get("strategy_id") or "")
    cfg = read_json(config_path_for(args.strategy_registry, sid))
    risk = cfg.get("risk_management", {}) or {}
    run_dir = Path(args.runs_dir) / str(row.get("run_id"))
    counts = exit_counts(run_dir / "trades.csv")
    out = dict(row)
    out.update({
        "stop_loss_pct": risk.get("stop_loss_pct", ""),
        "trailing_stop_pct": risk.get("trailing_stop_pct", ""),
        "trailing_activation_gain_pct": risk.get("trailing_activation_gain_pct", ""),
        "stop_loss_exit_count": counts.get("stop_loss", 0),
        "trailing_exit_count": counts.get("trailing_stop", 0),
        "breakeven_exit_count": counts.get("breakeven_stop", 0),
        "profit_lock_exit_count": counts.get("profit_lock_stop", 0),
        "partial_exit_count": counts.get("partial_take_profit", 0),
        "rank_exit_count": counts.get("rank_deterioration_exit", 0),
        "decision": decision(out),
    })
    return out


def exit_counts(path: Path) -> dict[str, int]:
    if not path.exists():
        return {}
    trades = read_csv_flexible(path)
    if "exit_reason" not in trades.columns:
        return {}
    return {str(k): int(v) for k, v in trades["exit_reason"].value_counts().to_dict().items()}


def decision(row: dict[str, Any]) -> str:
    dd, cagr, spy, trades = f(row.get("max_drawdown")), f(row.get("cagr")), f(row.get("spy_cagr")), i(row.get("trades"))
    yw, yl, calmar = i(row.get("years_beating_spy")), i(row.get("years_losing_to_spy")), f(row.get("calmar"))
    if dd >= -20 and cagr >= spy + 1 and trades >= DD20_MIN_TRADES and yw > yl and calmar >= 0.45:
        return "strong_candidate"
    if dd >= -20 and cagr > spy and trades >= DD20_MIN_TRADES and yw >= yl:
        return "valid_candidate"
    if dd >= -20 and cagr > spy and trades >= 2200 and yw >= yl:
        return "near_valid_useful"
    return "rejected"


def best_near_valid(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not rows:
        return None
    return sorted(rows, key=lambda r: (gap_score(r), -f(r.get("cagr"))))[0]


def gap_score(row: dict[str, Any]) -> float:
    return round(max(0, -20 - f(row.get("max_drawdown"))) * 10 + max(0, f(row.get("spy_cagr")) - f(row.get("cagr"))) * 4 + max(0, (DD20_MIN_TRADES - i(row.get("trades"))) / DD20_MIN_TRADES) + max(0, i(row.get("years_losing_to_spy")) - i(row.get("years_beating_spy"))), 6)


def build_markdown(rows: list[dict[str, Any]]) -> str:
    valid = [r for r in rows if decision(r) in {"valid_candidate", "strong_candidate"}]
    near = best_near_valid(rows)
    dd_ok = [r for r in rows if f(r.get("max_drawdown")) >= -20]
    base = next((r for r in rows if r.get("strategy_id") == BASE_STRATEGY_ID), None)
    lines = ["# DD20 Stop/Trailing Repair Summary", "", "## Valid candidates", ""]
    lines += ["- none"] if not valid else [fmt_row(r) for r in sorted(valid, key=lambda r: -f(r.get("cagr")))]
    lines += ["", "## Best near-valid", "", fmt_row(near) if near else "- none"]
    lines += ["", "## Best with DD < 20", ""]
    if dd_ok:
        best_cagr = max(dd_ok, key=lambda r: f(r.get("cagr")))
        best_trades = max(dd_ok, key=lambda r: i(r.get("trades")))
        lines.append(f"- Highest CAGR under DD20: {fmt_row(best_cagr)}")
        lines.append(f"- Best trade count under DD20: {fmt_row(best_trades)}")
    lines += ["", f"## Comparison vs `{BASE_STRATEGY_ID}`", ""]
    lines.append("- Base reference is the prior near-valid: CAGR 8.2043%, DD -19.9052%, years W/L 14/14, trades 1699.")
    if near:
        lines.append(f"- Best stop/trailing repair: {fmt_row(near)}")
    stop_rows = [r for r in rows if r.get("stop_loss_pct") not in {"", None}]
    trail_rows = [r for r in rows if r.get("trailing_stop_pct") not in {"", None}]
    lines += ["", "## Exit mechanism readout", ""]
    lines.append(mechanism_line("Stop loss", stop_rows))
    lines.append(mechanism_line("Trailing", trail_rows))
    lines += ["", "## All strategies", "", "| strategy_id | CAGR | DD | trades | years W/L | stop/trail/act | exits SL/TR/BE/PL/PT/RK | decision |", "|:---|---:|---:|---:|:---|:---|:---|:---|"]
    for r in sorted(rows, key=lambda r: (gap_score(r), -f(r.get("cagr")))):
        lines.append(f"| `{r.get('strategy_id')}` | {f(r.get('cagr')):.4f}% | {f(r.get('max_drawdown')):.4f}% | {i(r.get('trades'))} | {i(r.get('years_beating_spy'))}/{i(r.get('years_losing_to_spy'))} | {r.get('stop_loss_pct')}/{r.get('trailing_stop_pct')}/{r.get('trailing_activation_gain_pct')} | {i(r.get('stop_loss_exit_count'))}/{i(r.get('trailing_exit_count'))}/{i(r.get('breakeven_exit_count'))}/{i(r.get('profit_lock_exit_count'))}/{i(r.get('partial_exit_count'))}/{i(r.get('rank_exit_count'))} | {decision(r)} |")
    lines += ["", "## Next axis", "", "- Try a less destructive portfolio guard or wider stop/trailing exits only if they keep trades above 2200; current guard remains the trade-count bottleneck."]
    return "\n".join(lines) + "\n"


def fmt_row(row: dict[str, Any] | None) -> str:
    if not row:
        return "- none"
    return f"`{row.get('strategy_id')}` CAGR {f(row.get('cagr')):.4f}%, DD {f(row.get('max_drawdown')):.4f}%, trades {i(row.get('trades'))}, years {i(row.get('years_beating_spy'))}/{i(row.get('years_losing_to_spy'))}, decision {decision(row)}"


def mechanism_line(label: str, rows: list[dict[str, Any]]) -> str:
    if not rows:
        return f"- {label}: no variants."
    best = best_near_valid(rows)
    return f"- {label}: best {fmt_row(best)}."


def build_best_so_far(all_rows: list[dict[str, Any]], repair_rows: list[dict[str, Any]]) -> str:
    valid = [r for r in all_rows if f(r.get("max_drawdown")) >= -20 and f(r.get("cagr")) > f(r.get("spy_cagr")) and i(r.get("trades")) >= DD20_MIN_TRADES and i(r.get("years_beating_spy")) >= i(r.get("years_losing_to_spy"))]
    near = best_near_valid(repair_rows) or best_near_valid(all_rows)
    lines = ["# DD20 Best So Far", ""]
    lines.append(f"- Valid candidates: {len(valid)}")
    lines.append(f"- Best near-miss: {fmt_row(near)}")
    return "\n".join(lines) + "\n"


def write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore", delimiter=";")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: csv_value(row.get(k, "")) for k in columns})


def update_learning(state_dir: str, rows: list[dict[str, Any]]) -> None:
    path = Path(state_dir) / "dd20_spy_beater_learning.json"
    learning = read_json(path) if path.exists() else {"events": [], "recommendations": []}
    events = [event for event in learning.get("events", []) if event.get("phase") != "dd20_stop_trailing_repair"]
    events.append({"phase": "dd20_stop_trailing_repair", "best_near_miss": best_near_valid(rows), "lesson": "Stop/trailing exits are useful only if they recover trades without breaking DD20; compare exit counts before expanding."})
    learning["events"] = events[-20:]
    learning["recommendations"] = ["Prioritize variants that pass DD20 and exceed 2200 trades before chasing CAGR.", "If no stop/trailing variant improves trade count, the equity guard is the bottleneck."]
    write_json(path, learning)


def load_state(state_dir: str) -> dict[str, Any]:
    path = Path(state_dir) / "dd20_spy_beater_state.json"
    return read_json(path) if path.exists() else {}


def save_state(state_dir: str, state: dict[str, Any]) -> None:
    write_json(Path(state_dir) / "dd20_spy_beater_state.json", state)


def next_run_id(runs_dir: str, strategy_id: str) -> str:
    stem = f"DD20STOPTRAIL_{strategy_id}"[:120]
    candidate = stem
    n = 1
    while (Path(runs_dir) / candidate).exists():
        n += 1
        candidate = f"{stem}_{n}"
    return candidate


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
