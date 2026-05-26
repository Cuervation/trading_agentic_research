"""Autonomous DD20 + SPY-beater daemon.

Search objective: maximize CAGR only among strategies that keep max DD >= -20,
beat SPY CAGR, keep at least 3000 trades, and beat/lose yearly SPY at least 1:1.
The daemon never moves parent/baseline and never calls --allow-parent-update.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtester.dd20_spy_beater import (
    DD20_MIN_TRADES,
    evaluate_dd20_spy_beater_run,
    row_from_dd20_audit_or_run,
    valid_dd20_rows,
    write_dd20_summary_csv,
    write_dd20_summary_markdown,
)
from scripts.run_dd_first_autofix_loop import _csv_columns, _preflight, attempt_repair, classify_error, read_json, read_jsonl, write_json, write_jsonl
from scripts.run_dd_first_autonomous_daemon import _state_snapshot, assert_parent_baseline_unchanged

BASE_DEFENSIVE_CONFIG = "configs/generated/HYP_DD_FIRST_AUTO002_DYN_EXPOSURE_65_55_45_25_V1.json"
DEFAULT_PARENT_CONFIG = "configs/generated/HYP_AUTO_TIME_SERIES_MOMENTUM_SEED.json"
FULL_HISTORY_PARENT = "RETEST_HYP_AUTO_TIME_SERIES_MOMENTUM_SEED_1999_2026_20260524_174409"
FAMILY = "dd20_spy_beater"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run autonomous DD20 + SPY-beater research batches.")
    p.add_argument("--batch-size", type=int, default=5)
    p.add_argument("--max-batches", type=int, default=2)
    p.add_argument("--max-total-attempts", type=int, default=30)
    p.add_argument("--max-wall-clock-hours", type=float, default=12.0)
    p.add_argument("--target-valid-strategies", type=int, default=3)
    p.add_argument("--resume", action="store_true")
    p.add_argument("--weekly-file", default=None)
    p.add_argument("--daily-folder", default=None)
    p.add_argument("--parent-strategy-config", default=DEFAULT_PARENT_CONFIG)
    p.add_argument("--parent-run-id", default=FULL_HISTORY_PARENT)
    p.add_argument("--project-config", default="configs/project_config.json")
    p.add_argument("--strategy-registry", default="configs/strategy_registry.json")
    p.add_argument("--hypothesis-bank", default="bibliography/hypothesis_bank.jsonl")
    p.add_argument("--runs-dir", default="runs")
    p.add_argument("--reports-dir", default="reports")
    p.add_argument("--state-dir", default="state")
    p.add_argument("--per-run-timeout-minutes", type=float, default=45.0)
    p.add_argument("--min-trades", type=int, default=DD20_MIN_TRADES)
    return p.parse_args()


def main() -> int:
    args = parse_args()
    started = time.monotonic()
    parent_snapshot = _state_snapshot(args.state_dir)
    state = load_state(args.state_dir, args.resume)
    learning = load_learning(args.state_dir)

    try:
        weekly_file, daily_folder, parent_run_id = _preflight(args)
        if args.parent_run_id != parent_run_id:
            parent_run_id = args.parent_run_id
        weekly_columns = _csv_columns(weekly_file)
        assert_full_history_parent(args.runs_dir, parent_run_id)
        assert_parent_baseline_unchanged(args.state_dir, parent_snapshot)
        ensure_initial_strategies(args, weekly_columns)
    except Exception as exc:
        state.update({"status": "failed", "stop_reason": "preflight_failed", "last_error": str(exc)})
        save_state(args.state_dir, state)
        return 2

    state.setdefault("started_at", datetime.now(timezone.utc).isoformat())
    state.update({"status": "running", "parent_run_id": parent_run_id})
    save_state(args.state_dir, state)

    all_specs = candidate_specs()
    while not should_stop(args, state, started):
        state["current_batch"] = int(state.get("current_batch", 0)) + 1
        batch_id = f"DD20BATCH_{state['current_batch']:03d}"
        batch_specs = next_batch_specs(all_specs, state, args.batch_size)
        if not batch_specs:
            state["stop_reason"] = "no_remaining_specs"
            break
        state["next_batch_plan"] = [s["strategy_id"] for s in batch_specs]
        save_state(args.state_dir, state)

        completed_this_batch = 0
        for spec in batch_specs:
            if int(state.get("total_attempts", 0)) >= args.max_total_attempts:
                state["stop_reason"] = "max_total_attempts_reached"
                break
            assert_parent_baseline_unchanged(args.state_dir, parent_snapshot)
            strategy_id = spec["strategy_id"]
            config_path = config_path_for(args.strategy_registry, strategy_id)
            run_id = next_run_id(args.runs_dir, state["current_batch"], strategy_id)
            state["total_attempts"] = int(state.get("total_attempts", 0)) + 1
            state.setdefault("attempted_strategy_ids", []).append(strategy_id)
            result = run_one_dd20_candidate(
                run_id=run_id,
                strategy_id=strategy_id,
                config_path=config_path,
                weekly_file=weekly_file,
                daily_folder=daily_folder,
                parent_run_id=parent_run_id,
                args=args,
            )
            if not result["ok"]:
                classification = classify_error(result["error"])
                repaired = attempt_repair(classification, config_path, weekly_columns)
                state["failed_attempts"] = int(state.get("failed_attempts", 0)) + 1
                state["last_error"] = f"{classification}: {result['error'][:800]}"
                if repaired and int(state.get("total_attempts", 0)) < args.max_total_attempts:
                    state["repaired_errors"] = int(state.get("repaired_errors", 0)) + 1
                    retry_id = next_run_id(args.runs_dir, state["current_batch"], strategy_id)
                    state["total_attempts"] = int(state.get("total_attempts", 0)) + 1
                    result = run_one_dd20_candidate(
                        run_id=retry_id,
                        strategy_id=strategy_id,
                        config_path=config_path,
                        weekly_file=weekly_file,
                        daily_folder=daily_folder,
                        parent_run_id=parent_run_id,
                        args=args,
                    )
                if not result["ok"]:
                    append_learning(learning, spec, None, f"failed:{classification}")
                    continue

            row = result["row"]
            completed_this_batch += 1
            state.setdefault("completed_strategy_ids", []).append(strategy_id)
            state["last_run_id"] = row.get("run_id")
            append_learning(learning, spec, row, lesson_from_row(row))
            refresh_reports_and_state(args, state, learning, parent_run_id)
            if len(valid_dd20_rows(load_all_rows(args.runs_dir, parent_run_id, args.min_trades))) >= args.target_valid_strategies:
                state["stop_reason"] = "target_valid_strategies_reached"
                break

        state["completed_batches"] = int(state.get("completed_batches", 0)) + 1
        state["last_batch_completed_runs"] = completed_this_batch
        refresh_reports_and_state(args, state, learning, parent_run_id)

    state["status"] = "completed"
    state["stop_reason"] = state.get("stop_reason") or "target_or_limit_reached"
    refresh_reports_and_state(args, state, learning, args.parent_run_id)
    print(
        "DD20_SPY_BEATER daemon completed: "
        f"batches={state.get('completed_batches')} attempts={state.get('total_attempts')} "
        f"valid={state.get('valid_strategies')} stop={state.get('stop_reason')}"
    )
    return 0


def candidate_specs() -> list[dict[str, Any]]:
    base = {
        "generation_axis": "dd20_spy_beater",
        "expected_effect": "Reduce max drawdown below 20% while preserving enough upside to beat SPY.",
        "falsification_rule": "Reject automatically if DD is below -20%, CAGR does not beat SPY, trades < 3000, or yearly SPY win/loss is negative.",
        "empirical_basis": [{"run_id": "DDDAEMON_001_HYP_DD_FIRST_AUTO002_DYN_EXPOSURE_65_55_45_25_V1", "reason": "Best useful defensive DD_FIRST candidate so far."}],
        "risk_of_overfit": "Medium: thresholds are coarse causal risk controls, not micro-optimized curve fitting.",
    }
    return [
        spec("HYP_DD20_SPY_DYN_55_45_35_15_V1", {"risk_management.dynamic_regime_exposure_pct": {"strong": 55, "neutral": 45, "weak": 35, "crisis": 15}, "risk_management.max_gross_exposure_pct": 45}, ["risk_management.dynamic_regime_exposure_pct", "risk_management.max_gross_exposure_pct"], "Lower all regimes to test if DD20 is reachable without eliminating upside.", base),
        spec("HYP_DD20_SPY_DYN_60_45_30_10_V1", {"risk_management.dynamic_regime_exposure_pct": {"strong": 60, "neutral": 45, "weak": 30, "crisis": 10}, "risk_management.max_gross_exposure_pct": 45}, ["risk_management.dynamic_regime_exposure_pct", "risk_management.max_gross_exposure_pct"], "Keep moderate strong exposure but sharply reduce weak/crisis regimes.", base),
        spec("HYP_DD20_SPY_DYN_65_45_25_0_V1", {"risk_management.dynamic_regime_exposure_pct": {"strong": 65, "neutral": 45, "weak": 25, "crisis": 0}, "risk_management.max_gross_exposure_pct": 45}, ["risk_management.dynamic_regime_exposure_pct", "risk_management.max_gross_exposure_pct"], "Preserve strong-regime upside and remove crisis exposure.", base),
        spec("HYP_DD20_SPY_DYN_70_50_30_0_V1", {"risk_management.dynamic_regime_exposure_pct": {"strong": 70, "neutral": 50, "weak": 30, "crisis": 0}, "risk_management.max_gross_exposure_pct": 50}, ["risk_management.dynamic_regime_exposure_pct", "risk_management.max_gross_exposure_pct"], "Use higher strong exposure to recover CAGR while keeping crisis exposure at zero.", base),
        spec("HYP_DD20_SPY_DYN_65_55_45_25_NO_NEW_CRISIS_V1", {"risk_management.dynamic_regime_exposure_pct": {"strong": 65, "neutral": 55, "weak": 45, "crisis": 25}, "risk_management.max_gross_exposure_pct": 55, "risk_management.no_new_entries_in_crisis": crisis_guard()}, ["risk_management.no_new_entries_in_crisis"], "Block new entries only in crisis, while allowing existing winners to exit naturally.", base),
        spec("HYP_DD20_SPY_DYN_70_55_40_15_NO_NEW_CRISIS_V1", {"risk_management.dynamic_regime_exposure_pct": {"strong": 70, "neutral": 55, "weak": 40, "crisis": 15}, "risk_management.max_gross_exposure_pct": 55, "risk_management.no_new_entries_in_crisis": crisis_guard()}, ["risk_management.dynamic_regime_exposure_pct", "risk_management.no_new_entries_in_crisis"], "Combine higher strong-regime upside with no fresh crisis entries.", base),
        spec("HYP_DD20_SPY_DYN_65_55_45_25_EQUITY_GUARD_15_8_V1", {"risk_management.dynamic_regime_exposure_pct": {"strong": 65, "neutral": 55, "weak": 45, "crisis": 25}, "risk_management.max_gross_exposure_pct": 55, "risk_management.equity_drawdown_guard": {"enabled": True, "stop_new_entries_drawdown_pct": -15, "resume_drawdown_pct": -8}}, ["risk_management.equity_drawdown_guard"], "Stop adding risk after portfolio DD reaches -15%, resume only after recovery to -8%.", base),
        spec("HYP_DD20_SPY_DYN_70_55_40_15_EQUITY_GUARD_18_10_V1", {"risk_management.dynamic_regime_exposure_pct": {"strong": 70, "neutral": 55, "weak": 40, "crisis": 15}, "risk_management.max_gross_exposure_pct": 55, "risk_management.equity_drawdown_guard": {"enabled": True, "stop_new_entries_drawdown_pct": -18, "resume_drawdown_pct": -10}}, ["risk_management.dynamic_regime_exposure_pct", "risk_management.equity_drawdown_guard"], "Slightly looser equity guard to preserve CAGR while enforcing a DD20-oriented throttle.", base),
        spec("HYP_DD20_SPY_DYN_60_45_30_10_PARTIAL_20_33_V1", {"risk_management.dynamic_regime_exposure_pct": {"strong": 60, "neutral": 45, "weak": 30, "crisis": 10}, "risk_management.max_gross_exposure_pct": 45, "risk_management.partial_take_profit": {"enabled": True, "gain_pct": 20, "sell_fraction": 0.33}}, ["risk_management.dynamic_regime_exposure_pct", "risk_management.partial_take_profit"], "Harvest one third after 20% gains to reduce crash exposure without fully exiting winners.", base),
        spec("HYP_DD20_SPY_DYN_65_45_25_0_PARTIAL_25_33_V1", {"risk_management.dynamic_regime_exposure_pct": {"strong": 65, "neutral": 45, "weak": 25, "crisis": 0}, "risk_management.max_gross_exposure_pct": 45, "risk_management.partial_take_profit": {"enabled": True, "gain_pct": 25, "sell_fraction": 0.33}}, ["risk_management.dynamic_regime_exposure_pct", "risk_management.partial_take_profit"], "Pair zero crisis exposure with soft partial profits to defend DD while keeping strong-regime upside.", base),
    ]


def spec(strategy_id: str, patch: dict[str, Any], changed: list[str], causal: str, base: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    out.update({
        "strategy_id": strategy_id,
        "patch": patch,
        "changed_parameters": changed,
        "causal_mechanism": causal,
        "why_not_duplicate": f"{strategy_id} changes a named DD20 causal axis and has a distinct config hash.",
    })
    return out


def crisis_guard() -> dict[str, Any]:
    return {
        "enabled": True,
        "crisis_threshold_pct": -10,
        "regime_field_priority": ["spy_close_vs_sma50_pct", "close_vs_sma20w_pct", "close_vs_sma52w_pct"],
    }


def ensure_initial_strategies(args: argparse.Namespace, weekly_columns: set[str]) -> None:
    del weekly_columns
    registry = read_json(args.strategy_registry)
    existing = {s.get("strategy_id") for s in registry.get("strategies", [])}
    bank = read_jsonl(args.hypothesis_bank)
    existing_hyp = {h.get("hypothesis_id") for h in bank}
    base_path = Path(BASE_DEFENSIVE_CONFIG)
    parent_path = Path(args.parent_strategy_config)
    source_cfg = read_json(base_path if base_path.exists() else parent_path)

    for item in candidate_specs():
        sid = item["strategy_id"]
        cfg = deepcopy(source_cfg)
        cfg.update({
            "strategy_id": sid,
            "hypothesis_id": sid,
            "strategy_family": FAMILY,
            "evaluation_mode": "dd20_spy_beater",
            "generation_axis": "dd20_spy_beater",
            "parent_strategy_id": "HYP_AUTO_TIME_SERIES_MOMENTUM_SEED",
            "parent_hypothesis_id": "HYP_AUTO_TIME_SERIES_MOMENTUM_SEED",
            "claim": "Maximize CAGR only after satisfying DD20 and SPY-beater constraints.",
            "causal_mechanism": item["causal_mechanism"],
            "expected_effect": item["expected_effect"],
            "falsification_rule": item["falsification_rule"],
            "changed_parameters": item["changed_parameters"],
            "empirical_basis": item["empirical_basis"],
            "why_not_duplicate": item["why_not_duplicate"],
            "risk_of_overfit": item["risk_of_overfit"],
        })
        for dotted, value in item["patch"].items():
            set_dotted(cfg, dotted, value)
        cfg["strategy_overrides"] = {"risk_management": cfg.get("risk_management", {}), "market_filter": cfg.get("market_filter", {}), "ranking": cfg.get("ranking", {}), "risk_filters": cfg.get("risk_filters", {})}
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
                "parent_strategy_id": "HYP_AUTO_TIME_SERIES_MOMENTUM_SEED",
                "evaluation_mode": "dd20_spy_beater",
                "generation_axis": "dd20_spy_beater",
                "notes": "DD20_SPY_BEATER initial candidate.",
            })
        if sid not in existing_hyp:
            bank.append({
                "hypothesis_id": sid,
                "family": FAMILY,
                "status": "candidate",
                "evaluation_mode": "dd20_spy_beater",
                "generation_axis": "dd20_spy_beater",
                "parent_strategy_id": "HYP_AUTO_TIME_SERIES_MOMENTUM_SEED",
                "parent_hypothesis_id": "HYP_AUTO_TIME_SERIES_MOMENTUM_SEED",
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


def set_dotted(cfg: dict[str, Any], dotted: str, value: Any) -> None:
    cur = cfg
    parts = dotted.split(".")
    for part in parts[:-1]:
        cur = cur.setdefault(part, {})
    cur[parts[-1]] = value


def run_one_dd20_candidate(*, run_id: str, strategy_id: str, config_path: str, weekly_file: str, daily_folder: str, parent_run_id: str, args: argparse.Namespace) -> dict[str, Any]:
    commands = [
        [sys.executable, "scripts/run_backtest.py", "--weekly-file", weekly_file, "--daily-folder", daily_folder, "--strategy-config", config_path, "--project-config", args.project_config, "--run-id", run_id, "--runs-dir", args.runs_dir, "--parent-run-id", parent_run_id, "--parent-strategy-config", args.parent_strategy_config],
        [sys.executable, "scripts/evaluate_candidate.py", "--run-id", run_id, "--runs-dir", args.runs_dir, "--reports-dir", args.reports_dir, "--evaluation-mode", "dd20_spy_beater", "--hypothesis-id", strategy_id, "--family", FAMILY, "--state-dir", args.state_dir, "--parent-run-id", parent_run_id, "--min-trades", str(args.min_trades)],
    ]
    timeout_seconds = float(args.per_run_timeout_minutes or 0) * 60 or None
    for command in commands:
        try:
            result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False, timeout=timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            return {"ok": False, "error": f"command_timeout: {' '.join(command)}\n{exc.stderr or exc.stdout or ''}".strip(), "command": command}
        if result.returncode != 0:
            return {"ok": False, "error": (result.stderr or result.stdout or "").strip(), "command": command}
    run_dir = Path(args.runs_dir) / run_id
    row = row_from_dd20_audit_or_run(run_dir, parent_run_dir=Path(args.runs_dir) / parent_run_id, min_trades=args.min_trades)
    return {"ok": True, "row": row}


def load_all_rows(runs_dir: str, parent_run_id: str, min_trades: int) -> list[dict[str, Any]]:
    root = Path(runs_dir)
    rows: list[dict[str, Any]] = []
    for run_dir in root.iterdir() if root.exists() else []:
        if not run_dir.is_dir() or not (run_dir / "run_manifest.json").exists():
            continue
        try:
            manifest = read_json(run_dir / "run_manifest.json")
            sid = str(manifest.get("strategy_id") or "")
            if "DD20_SPY" not in sid and sid not in {"HYP_DD_FIRST_AUTO002_DYN_EXPOSURE_65_55_45_25_V1", "HYP_DD_FIRST_AUTO002_EXPOSURE_50_V1", "HYP_DD_FIRST_AUTO002_EXPOSURE_60_V1"}:
                continue
            rows.append(row_from_dd20_audit_or_run(run_dir, parent_run_dir=Path(runs_dir) / parent_run_id, min_trades=min_trades))
        except Exception:
            continue
    return rows


def refresh_reports_and_state(args: argparse.Namespace, state: dict[str, Any], learning: dict[str, Any], parent_run_id: str) -> None:
    rows = load_all_rows(args.runs_dir, parent_run_id, args.min_trades)
    valid = valid_dd20_rows(rows)
    state["valid_strategies"] = len(valid)
    state["best_valid_strategy"] = valid[0] if valid else None
    state["best_near_miss"] = None if valid else (max(rows, key=lambda r: float(str(r.get("cagr") or 0).replace(',', '.'))) if rows else None)
    write_dd20_summary_csv(Path(args.reports_dir) / "dd20_spy_beater_summary.csv", rows)
    write_dd20_summary_markdown(Path(args.reports_dir) / "dd20_spy_beater_summary.md", rows)
    save_state(args.state_dir, state)
    save_learning(args.state_dir, learning)


def next_batch_specs(all_specs: list[dict[str, Any]], state: dict[str, Any], batch_size: int) -> list[dict[str, Any]]:
    completed = set(state.get("completed_strategy_ids", []))
    attempted = set(state.get("attempted_strategy_ids", [])) if state.get("resume") else set()
    out = []
    for item in all_specs:
        if item["strategy_id"] in completed or item["strategy_id"] in attempted:
            continue
        out.append(item)
        if len(out) >= batch_size:
            break
    return out


def should_stop(args: argparse.Namespace, state: dict[str, Any], started: float) -> bool:
    if state.get("stop_reason"):
        return True
    if int(state.get("completed_batches", 0)) >= args.max_batches:
        state["stop_reason"] = "max_batches_reached"
        return True
    if int(state.get("total_attempts", 0)) >= args.max_total_attempts:
        state["stop_reason"] = "max_total_attempts_reached"
        return True
    if (time.monotonic() - started) / 3600.0 >= args.max_wall_clock_hours:
        state["stop_reason"] = "max_wall_clock_hours_reached"
        return True
    if int(state.get("valid_strategies", 0)) >= args.target_valid_strategies:
        state["stop_reason"] = "target_valid_strategies_reached"
        return True
    return False


def load_state(state_dir: str, resume: bool) -> dict[str, Any]:
    path = Path(state_dir) / "dd20_spy_beater_state.json"
    state = read_json(path) if resume and path.exists() else {}
    state["resume"] = bool(resume)
    return state


def save_state(state_dir: str, state: dict[str, Any]) -> None:
    write_json(Path(state_dir) / "dd20_spy_beater_state.json", state)


def load_learning(state_dir: str) -> dict[str, Any]:
    path = Path(state_dir) / "dd20_spy_beater_learning.json"
    return read_json(path) if path.exists() else {"events": [], "recommendations": []}


def save_learning(state_dir: str, learning: dict[str, Any]) -> None:
    write_json(Path(state_dir) / "dd20_spy_beater_learning.json", learning)


def append_learning(learning: dict[str, Any], spec: dict[str, Any], row: dict[str, Any] | None, lesson: str) -> None:
    learning.setdefault("events", []).append({"strategy_id": spec["strategy_id"], "run_id": (row or {}).get("run_id"), "decision": (row or {}).get("decision"), "lesson": lesson})
    if row and row.get("decision") == "rejected" and "max_drawdown_breaches_dd20" in str(row.get("rejection_reason")):
        learning["recommendations"] = ["Lower weak/crisis exposure", "Keep strong exposure selectively high", "Combine no_new_entries_in_crisis with equity_drawdown_guard -15/-8"]


def lesson_from_row(row: dict[str, Any]) -> str:
    if row.get("decision") in {"valid_candidate", "strong_candidate", "excellent_candidate"}:
        return "Valid DD20 + SPY-beater candidate found; rank by constrained CAGR."
    reason = str(row.get("rejection_reason") or "")
    if "max_drawdown_breaches_dd20" in reason:
        return "DD remains the binding constraint; next batch should lower weak/crisis exposure or add entry throttles."
    if "does_not_beat_spy" in reason:
        return "Return is the binding constraint; preserve strong-regime exposure while cutting only weak/crisis risk."
    return f"Rejected: {reason}"


def config_path_for(registry_path: str, strategy_id: str) -> str:
    registry = read_json(registry_path)
    for item in registry.get("strategies", []):
        if item.get("strategy_id") == strategy_id:
            return str(item.get("config_path"))
    return f"configs/generated/{strategy_id}.json"


def next_run_id(runs_dir: str, batch_number: int, strategy_id: str) -> str:
    stem = f"DD20BATCH_{batch_number:03d}_{strategy_id}"[:120]
    candidate = stem
    i = 1
    while (Path(runs_dir) / candidate).exists():
        i += 1
        candidate = f"{stem}_{i}"
    return candidate


def assert_full_history_parent(runs_dir: str, parent_run_id: str) -> None:
    if parent_run_id != FULL_HISTORY_PARENT:
        raise RuntimeError(f"DD20_SPY_BEATER requires locked parent {FULL_HISTORY_PARENT}, got {parent_run_id}")
    if not (Path(runs_dir) / parent_run_id).exists():
        raise FileNotFoundError(f"Parent full-history run not found: {parent_run_id}")


if __name__ == "__main__":
    raise SystemExit(main())
