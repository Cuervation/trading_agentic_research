"""Autonomous DD_FIRST batch daemon.

Generates causal DD_FIRST batches, runs real backtests, repairs simple failures,
updates learning/ranking state, and never moves parent or baseline state.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtester.dd_first import row_from_audit_or_run, write_dd_first_summary
from scripts.governance import stable_json_hash
from scripts.run_dd_first_autofix_loop import (
    FAMILY,
    _config_path_for,
    _csv_columns,
    _is_duplicate_or_noop,
    _preflight,
    attempt_repair,
    classify_error,
    read_json,
    read_jsonl,
    run_one_candidate,
    write_json,
    write_jsonl,
)
from scripts.run_dd_first_long_research_loop import (
    completed_run,
    load_existing_dd_first_rows,
    rebuild_axis_memory_from_rows,
    save_axis_memory,
    write_axis_summary,
)

DEFAULT_PARENT_CONFIG = "configs/generated/HYP_AUTO_TIME_SERIES_MOMENTUM_SEED.json"
FULL_HISTORY_PARENT = "RETEST_HYP_AUTO_TIME_SERIES_MOMENTUM_SEED_1999_2026_20260524_174409"
FAMILY_DAEMON = "dd_first_drawdown_control"
HARD_MAX_DRAWDOWN_PCT = -38.0
DEFENSIVE_MAX_DRAWDOWN_PCT = -34.0
RETURN_GUARD_MAX_DRAWDOWN_PCT = -42.0
MIN_TRADES = 3000


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run autonomous DD_FIRST research batches.")
    p.add_argument("--batch-size", type=int, default=5)
    p.add_argument("--max-batches", type=int, default=20)
    p.add_argument("--max-total-attempts", type=int, default=150)
    p.add_argument("--max-wall-clock-hours", type=float, default=24.0)
    p.add_argument("--target-champions", type=int, default=5)
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
    p.add_argument("--generation-mode", choices=["causal"], default="causal")
    p.add_argument("--allow-second-dimension-after-success", action="store_true")
    p.add_argument("--no-parent-update", action=argparse.BooleanOptionalAction, default=True)
    p.add_argument("--min-trades", type=int, default=MIN_TRADES)
    p.add_argument("--per-run-timeout-minutes", type=float, default=45.0)
    return p.parse_args()


def main() -> int:
    args = parse_args()
    started = time.monotonic()
    parent_snapshot = _state_snapshot(args.state_dir)
    state = load_daemon_state(args.state_dir, args.resume, args.batch_size)
    axis_memory = load_daemon_axis_memory(args.state_dir)
    batch_rows: list[dict[str, Any]] = []

    try:
        weekly_file, daily_folder, parent_run_id = _preflight(args)
        if args.parent_run_id != parent_run_id:
            parent_run_id = args.parent_run_id
        validate_full_history_parent(args.runs_dir, parent_run_id)
        weekly_columns = _csv_columns(weekly_file)
        assert_parent_baseline_unchanged(args.state_dir, parent_snapshot)
    except Exception as exc:
        state.update({"status": "failed", "last_error": str(exc), "stop_reason": "preflight_failed"})
        save_daemon_state(args.state_dir, state)
        return 2

    state.setdefault("started_at", datetime.now(timezone.utc).isoformat())
    if state.get("stop_reason") == "target_champions_reached":
        state["stop_reason"] = ""
    state["status"] = "running"
    save_daemon_state(args.state_dir, state)

    while not should_stop(args, state, started, axis_memory):
        state["current_batch"] = int(state.get("current_batch", 0)) + 1
        batch_id = f"DDBATCH_{state['current_batch']:03d}"
        specs = generate_batch_specs(
            batch_size=args.batch_size,
            registry_path=args.strategy_registry,
            axis_memory=axis_memory,
            weekly_columns=weekly_columns,
            allow_second_dimension=args.allow_second_dimension_after_success,
        )
        if not specs:
            state["stop_reason"] = "no_available_causal_specs"
            break
        state["next_batch_plan"] = [s["strategy_id"] for s in specs]
        save_daemon_state(args.state_dir, state)

        completed_this_batch = 0
        for spec in specs:
            if state.get("total_attempts", 0) >= args.max_total_attempts:
                state["stop_reason"] = "max_total_attempts_reached"
                break
            assert_parent_baseline_unchanged(args.state_dir, parent_snapshot)
            strategy_id = ensure_strategy_config(spec, args.parent_strategy_config, args.strategy_registry, args.hypothesis_bank)
            run_id = next_daemon_run_id(args.runs_dir, state["current_batch"], strategy_id)
            state["total_attempts"] = int(state.get("total_attempts", 0)) + 1
            state["current_axis"] = spec["axis"]
            result = run_one_candidate(
                run_id=run_id,
                strategy_id=strategy_id,
                config_path=_config_path_for(args.strategy_registry, strategy_id),
                weekly_file=weekly_file,
                daily_folder=daily_folder,
                parent_run_id=parent_run_id,
                args=args,
            )
            batch_row = {
                "batch_id": batch_id,
                "strategy_id": strategy_id,
                "axis": spec["axis"],
                "run_id": run_id,
                "status": "failed",
                "error": "",
                "repair_action": "",
            }
            if not result["ok"]:
                classification = classify_daemon_error(result["error"])
                state["failed_attempts"] = int(state.get("failed_attempts", 0)) + 1
                state["last_error"] = f"{classification}: {result['error'][:800]}"
                repair_class = "missing_field" if classification == "data_or_column_error" else classification
                repaired = attempt_repair(repair_class, _config_path_for(args.strategy_registry, strategy_id), weekly_columns)
                batch_row.update({"error": state["last_error"], "repair_action": "attempt_repair" if repaired else "none"})
                if repaired:
                    state["repaired_errors"] = int(state.get("repaired_errors", 0)) + 1
                    retry_id = next_daemon_run_id(args.runs_dir, state["current_batch"], strategy_id)
                    retry = run_one_candidate(
                        run_id=retry_id,
                        strategy_id=strategy_id,
                        config_path=_config_path_for(args.strategy_registry, strategy_id),
                        weekly_file=weekly_file,
                        daily_folder=daily_folder,
                        parent_run_id=parent_run_id,
                        args=args,
                    )
                    if retry["ok"]:
                        result = retry
                        run_id = retry_id
                        batch_row["run_id"] = retry_id
                if not result["ok"]:
                    batch_rows.append(batch_row)
                    update_axis_failure(axis_memory, spec["axis"], classification)
                    continue

            row = dict(result["row"])
            row["axis"] = spec["axis"]
            row["completed_run"] = completed_run(Path(args.runs_dir) / run_id)
            row["useful_candidate"] = is_champion_candidate(row, args.min_trades)
            status = "completed" if row["completed_run"] else "incomplete"
            if row["completed_run"] and not _is_duplicate_or_noop(row) and int(row.get("trades") or 0) > 0:
                completed_this_batch += 1
            batch_row.update(row_to_batch_row(batch_id, row, spec["axis"], status))
            batch_rows.append(batch_row)
            update_axis_after_row(axis_memory, spec["axis"], row, args.min_trades)
            append_learning(args.state_dir, row, spec["axis"], spec)
            save_progress(args, state, axis_memory, batch_rows, parent_run_id)

        state["completed_batches"] = int(state.get("completed_batches", 0)) + 1
        rows = load_existing_dd_first_rows(args.runs_dir, args.min_trades, parent_run_id=parent_run_id)
        state["completed_runs"] = len([r for r in rows if completed_run(Path(args.runs_dir) / str(r.get("run_id")))])
        state["useful_candidates"] = len([r for r in rows if is_champion_candidate(r, args.min_trades)])
        champions = select_champions(rows, args.min_trades)
        state["champions_found"] = champion_count(champions)
        state["last_lesson"] = latest_lesson(args.state_dir)
        save_progress(args, state, axis_memory, batch_rows, parent_run_id)
        if completed_this_batch < args.batch_size and state.get("stop_reason"):
            break

    stop_reason = state.get("stop_reason") or "target_or_limit_reached"
    state["status"] = "completed" if stop_reason in {"max_batches_reached", "max_total_attempts_reached", "max_wall_clock_hours_reached", "all_axes_exhausted_or_cooldown"} else "stopped"
    state["stop_reason"] = stop_reason
    save_progress(args, state, axis_memory, batch_rows, args.parent_run_id)
    print(f"DD_FIRST daemon {state['status']}: batches={state.get('completed_batches')} attempts={state.get('total_attempts')} champions={state.get('champions_found')} stop={state.get('stop_reason')}")
    return 0 if state["status"] in {"completed", "stopped"} else 2


def generate_batch_specs(*, batch_size: int, registry_path: str, axis_memory: dict[str, Any], weekly_columns: set[str], allow_second_dimension: bool) -> list[dict[str, Any]]:
    existing_ids = existing_strategy_ids(registry_path)
    out = []
    for spec in candidate_specs(weekly_columns, allow_second_dimension):
        axis = spec["axis"]
        if axis_memory.get("axes", {}).get(axis, {}).get("status") in {"cooldown", "exhausted"}:
            continue
        if spec["strategy_id"] in existing_ids:
            continue
        out.append(spec)
        if len(out) >= batch_size:
            break
    return out


def candidate_specs(weekly_columns: set[str], allow_second_dimension: bool) -> list[dict[str, Any]]:
    specs = [
        dyn_spec("75_60_50_25", 75, 60, 50, 25),
        dyn_spec("70_60_50_25", 70, 60, 50, 25),
        dyn_spec("75_60_55_35", 75, 60, 55, 35),
        dyn_spec("70_55_45_25", 70, 55, 45, 25),
        dyn_spec("65_55_45_25", 65, 55, 45, 25),
        breakeven_spec(8, 0),
        breakeven_spec(10, 0),
        breakeven_spec(12, 0),
        breakeven_spec(10, 1),
        soft_topn_spec(5),
        soft_topn_spec(8),
        soft_topn_spec(10),
    ]
    if {"weekly_range_pct", "atr_14w_pct", "volatility_12w_pct"} & weekly_columns:
        specs.extend([lowvol_spec("weekly_range_pct", 0.05), lowvol_spec("atr_14w_pct", 0.05), lowvol_spec("volatility_12w_pct", 0.05)])
    if "close_vs_sma52w_pct" in weekly_columns:
        specs.append(extension_spec("close_vs_sma52w_pct", 80))
    if "close_vs_sma20w_pct" in weekly_columns:
        specs.append(extension_spec("close_vs_sma20w_pct", 60))
    if allow_second_dimension:
        specs.extend([combo_spec("EXPOSURE60_BREAKEVEN10", {"risk_management.max_gross_exposure_pct": 60, "risk_management.breakeven_after_gain_pct": 10})])
    return specs


def dyn_spec(name: str, strong: int, neutral: int, weak: int, crisis: int) -> dict[str, Any]:
    return {
        "strategy_id": f"HYP_DD_FIRST_AUTO002_DYN_EXPOSURE_{name}_V1",
        "axis": "dynamic_regime_exposure",
        "patch": {"risk_management.dynamic_regime_exposure_pct": {"strong": strong, "neutral": neutral, "weak": weak, "crisis": crisis}, "risk_management.max_gross_exposure_pct": neutral},
        "causal_mechanism": "Scale gross exposure by SPY regime around the proven fixed 60% balance instead of turning signals off.",
    }


def breakeven_spec(trigger: int, buffer: int) -> dict[str, Any]:
    return {
        "strategy_id": f"HYP_DD_FIRST_AUTO002_EXPOSURE60_BREAKEVEN_{trigger}_{buffer}_V1",
        "axis": "exposure_plus_breakeven",
        "patch": {"risk_management.max_gross_exposure_pct": 60, "risk_management.breakeven_after_gain_pct": trigger, "risk_management.breakeven_buffer_pct": buffer},
        "causal_mechanism": "Keep fixed 60% exposure and protect winners that already moved enough to avoid round-trip losses.",
    }


def soft_topn_spec(topn: int) -> dict[str, Any]:
    return {
        "strategy_id": f"HYP_DD_FIRST_AUTO002_EXPOSURE60_SOFT_SPY_TOPN_{topn}_V1",
        "axis": "exposure_plus_soft_spy_topn",
        "patch": {"risk_management.max_gross_exposure_pct": 60, "market_filter.soft_weak_regime_top_n": topn},
        "causal_mechanism": "Keep 60% exposure but throttle breadth in weak SPY regime without hard-zeroing trades.",
    }


def lowvol_spec(field: str, weight: float) -> dict[str, Any]:
    return {
        "strategy_id": f"HYP_DD_FIRST_AUTO002_EXPOSURE60_LOWVOL_{field.upper()}_W{int(weight*100)}_V1",
        "axis": "exposure_plus_low_vol_penalty",
        "patch": {"risk_management.max_gross_exposure_pct": 60, "ranking.secondary_penalty_field": field, "ranking.secondary_penalty_weight": weight},
        "causal_mechanism": "Keep 60% exposure and softly penalize volatile momentum names rather than filtering them out.",
    }


def extension_spec(field: str, threshold: int) -> dict[str, Any]:
    return {
        "strategy_id": f"HYP_DD_FIRST_AUTO002_EXPOSURE60_ANTI_EXTENSION_{field.upper()}_{threshold}_V1",
        "axis": "exposure_plus_anti_extension",
        "patch": {"risk_management.max_gross_exposure_pct": 60, "risk_filters.conditions": [{"field": field, "operator": "<=", "value": threshold, "enabled_if_field_exists": True}]},
        "causal_mechanism": "Keep 60% exposure and avoid the most overextended entries with broad thresholds.",
    }


def combo_spec(name: str, patch: dict[str, Any]) -> dict[str, Any]:
    return {"strategy_id": f"HYP_DD_FIRST_AUTO002_{name}_V1", "axis": "controlled_combos", "patch": patch, "causal_mechanism": "Controlled two-dimension combo after fixed exposure proved useful."}


def ensure_strategy_config(spec: dict[str, Any], parent_config_path: str, registry_path: str, hypothesis_bank_path: str) -> str:
    sid = spec["strategy_id"]
    if sid in existing_strategy_ids(registry_path):
        return sid
    parent = read_json(parent_config_path)
    cfg = deepcopy(parent)
    cfg.update(
        {
            "strategy_id": sid,
            "hypothesis_id": sid,
            "strategy_family": FAMILY_DAEMON,
            "generation_axis": spec["axis"],
            "parent_strategy_id": parent.get("strategy_id"),
            "parent_hypothesis_id": parent.get("hypothesis_id") or parent.get("strategy_id"),
            "bibliography_basis": [{"source_id": "SRC_TIME_SERIES_MOMENTUM_SEED"}],
            "empirical_basis": [
                {"run_id": "DD_FIRST_16_HYP_DD_FIRST_AUTO002_EXPOSURE_60_V1", "reason": "Fixed 60% exposure was the best DD_FIRST balance before daemon generation."}
            ],
            "causal_mechanism": spec["causal_mechanism"],
            "expected_effect": "Reduce max drawdown first while keeping CAGR above SPY and enough trades.",
            "falsification_rule": "Reject if drawdown improvement is not material, CAGR loses to SPY, trades fall below sample needs, or artifacts duplicate prior hypotheses.",
            "novelty_reason": f"Autonomous daemon causal batch axis={spec['axis']}.",
            "why_not_duplicate": "Strategy id and config hash are checked before generation.",
            "risk_of_overfit": "Coarse causal step, not micro-optimized random parameter search.",
            "expected_trade_count_effect": "Preserve trade count; no hard zero-trade filters.",
        }
    )
    changed = apply_patch_to_config(cfg, spec["patch"])
    cfg["changed_parameters"] = changed
    cfg["strategy_overrides"] = {key: cfg.get(key) for key in ["risk_management", "market_filter", "ranking", "risk_filters"] if key in cfg}
    write_strategy_and_hypothesis(cfg, registry_path, hypothesis_bank_path)
    return sid


def apply_patch_to_config(cfg: dict[str, Any], patch: dict[str, Any]) -> list[str]:
    changed = []
    for dotted, value in patch.items():
        if dotted.startswith("risk_management."):
            cfg.setdefault("risk_management", {})[dotted.split(".", 1)[1]] = value
        elif dotted.startswith("market_filter."):
            cfg.setdefault("market_filter", {})[dotted.split(".", 1)[1]] = value
        elif dotted.startswith("ranking."):
            cfg.setdefault("ranking", {})[dotted.split(".", 1)[1]] = value
        elif dotted == "risk_filters.conditions":
            cfg.setdefault("risk_filters", {})["conditions"] = value
        else:
            continue
        changed.append(dotted)
    return changed


def write_strategy_and_hypothesis(cfg: dict[str, Any], registry_path: str, hypothesis_bank_path: str) -> None:
    sid = cfg["strategy_id"]
    config_path = Path("configs/generated") / f"{sid}.json"
    write_json(config_path, cfg)
    registry = read_json(registry_path)
    rows = [r for r in registry.get("strategies", []) if r.get("strategy_id") != sid]
    rows.append({"strategy_id": sid, "strategy_family": FAMILY_DAEMON, "status": "candidate", "benchmark_ticker": "SPY", "config_path": config_path.as_posix(), "signal_frequency": "weekly", "execution_frequency": "daily", "rebalance_frequency": "monthly", "parent_strategy_id": cfg.get("parent_strategy_id"), "evaluation_mode": "dd_first", "generation_axis": cfg.get("generation_axis"), "notes": "DD_FIRST autonomous daemon candidate."})
    registry["strategies"] = rows
    write_json(registry_path, registry)
    bank_rows = [r for r in read_jsonl(hypothesis_bank_path) if r.get("hypothesis_id") != sid]
    bank_rows.append({"hypothesis_id": sid, "family": FAMILY_DAEMON, "status": "candidate", "evaluation_mode": "dd_first", "generation_axis": cfg.get("generation_axis"), "parent_strategy_id": cfg.get("parent_strategy_id"), "parent_hypothesis_id": cfg.get("parent_hypothesis_id"), "bibliography_basis": cfg.get("bibliography_basis", []), "empirical_basis": cfg.get("empirical_basis", []), "causal_mechanism": cfg.get("causal_mechanism"), "expected_effect": cfg.get("expected_effect"), "falsification_rule": cfg.get("falsification_rule"), "changed_parameters": cfg.get("changed_parameters", []), "strategy_overrides": cfg.get("strategy_overrides", {}), "novelty_reason": cfg.get("novelty_reason"), "why_not_duplicate": cfg.get("why_not_duplicate"), "risk_of_overfit": cfg.get("risk_of_overfit"), "expected_trade_count_effect": cfg.get("expected_trade_count_effect")})
    write_jsonl(hypothesis_bank_path, bank_rows)


def select_champions(rows: list[dict[str, Any]], min_trades: int = MIN_TRADES) -> dict[str, Any]:
    candidates = [r for r in rows if is_champion_candidate(r, min_trades)]
    dd_min = [r for r in candidates if _f(r, "strategy_max_drawdown_pct") >= DEFENSIVE_MAX_DRAWDOWN_PCT]
    balanced = [r for r in candidates if _f(r, "strategy_max_drawdown_pct") >= HARD_MAX_DRAWDOWN_PCT]
    ret_guard = [r for r in candidates if _f(r, "strategy_max_drawdown_pct") >= RETURN_GUARD_MAX_DRAWDOWN_PCT]
    return {
        "dd_min_champion": min(dd_min or candidates, key=lambda r: abs(_f(r, "strategy_max_drawdown_pct")), default=None),
        "balanced_dd_champion": max(balanced or candidates, key=lambda r: balanced_score(r), default=None),
        "return_with_dd_guard_champion": max(ret_guard or candidates, key=lambda r: _f(r, "strategy_cagr_pct"), default=None),
        "pareto_frontier": pareto_frontier(candidates),
        "rejected_champions": [r for r in rows if not is_champion_candidate(r, min_trades)],
        "champion_history": candidates,
    }


def is_champion_candidate(row: dict[str, Any], min_trades: int = MIN_TRADES) -> bool:
    return (
        _i(row, "trades") >= min_trades
        and _f(row, "strategy_cagr_pct") > _f(row, "spy_cagr_pct")
        and _i(row, "years_beating_spy") > _i(row, "years_losing_to_spy")
        and _f(row, "drawdown_improvement_vs_parent_pct") >= 25.0
        and not _is_duplicate_or_noop(row)
        and _i(row, "trades") > 0
    )


def balanced_score(row: dict[str, Any]) -> float:
    return _f(row, "drawdown_improvement_vs_parent_pct") * 2 + _f(row, "calmar_ratio") * 30 + max(_f(row, "excess_cagr_pct"), 0)


def pareto_frontier(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    frontier = []
    for row in rows:
        dominated = False
        for other in rows:
            if other is row:
                continue
            if abs(_f(other, "strategy_max_drawdown_pct")) <= abs(_f(row, "strategy_max_drawdown_pct")) and _f(other, "strategy_cagr_pct") >= _f(row, "strategy_cagr_pct") and _f(other, "calmar_ratio") >= _f(row, "calmar_ratio"):
                dominated = True
                break
        if not dominated:
            frontier.append(row)
    return sorted(frontier, key=lambda r: (_f(r, "drawdown_improvement_vs_parent_pct"), _f(r, "calmar_ratio")), reverse=True)


def load_daemon_state(state_dir: str, resume: bool, batch_size: int) -> dict[str, Any]:
    path = Path(state_dir) / "dd_first_daemon_state.json"
    if resume and path.exists():
        return read_json(path)
    return {"status": "initialized", "current_batch": 0, "batch_size": batch_size, "completed_batches": 0, "total_attempts": 0, "completed_runs": 0, "useful_candidates": 0, "champions_found": 0, "failed_attempts": 0, "repaired_errors": 0, "current_axis": "", "cooldown_axes": [], "exhausted_axes": [], "last_error": "", "last_repair": "", "last_lesson": "", "next_batch_plan": []}


def save_daemon_state(state_dir: str, state: dict[str, Any]) -> None:
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    write_json(Path(state_dir) / "dd_first_daemon_state.json", state)


def load_daemon_axis_memory(state_dir: str) -> dict[str, Any]:
    path = Path(state_dir) / "dd_first_axis_memory.json"
    payload = read_json(path) if path.exists() else {"axes": {}}
    for axis in ["dynamic_regime_exposure", "exposure_plus_crisis_guard", "exposure_plus_breakeven", "exposure_plus_soft_spy_topn", "exposure_plus_low_vol_penalty", "exposure_plus_anti_extension", "controlled_combos"]:
        payload.setdefault("axes", {}).setdefault(axis, {"attempts": 0, "completed_runs": 0, "useful_candidates": 0, "champion_candidates": 0, "failures": [], "zero_trade_runs": 0, "duplicate_runs": 0, "worse_drawdown_runs": 0, "best_run_id": None, "best_drawdown": None, "best_cagr": None, "best_calmar": None, "status": "active", "lessons": [], "next_action": "generate_batch"})
    return payload


def update_axis_after_row(axis_memory: dict[str, Any], axis: str, row: dict[str, Any], min_trades: int) -> None:
    data = axis_memory["axes"].setdefault(axis, {"status": "active", "failures": [], "lessons": []})
    data["attempts"] = int(data.get("attempts", 0)) + 1
    data["completed_runs"] = int(data.get("completed_runs", 0)) + int(bool(row.get("completed_run")))
    data["useful_candidates"] = int(data.get("useful_candidates", 0)) + int(is_champion_candidate(row, min_trades))
    data["champion_candidates"] = int(data.get("champion_candidates", 0)) + int(is_champion_candidate(row, min_trades))
    data["zero_trade_runs"] = int(data.get("zero_trade_runs", 0)) + int(_i(row, "trades") == 0)
    data["duplicate_runs"] = int(data.get("duplicate_runs", 0)) + int(_is_duplicate_or_noop(row))
    data["worse_drawdown_runs"] = int(data.get("worse_drawdown_runs", 0)) + int(_f(row, "drawdown_improvement_vs_parent_pct") < 0)
    if data.get("best_drawdown") is None or abs(_f(row, "strategy_max_drawdown_pct")) < abs(float(data["best_drawdown"])):
        data.update({"best_run_id": row.get("run_id"), "best_drawdown": _f(row, "strategy_max_drawdown_pct"), "best_cagr": _f(row, "strategy_cagr_pct"), "best_calmar": _f(row, "calmar_ratio")})
    data.setdefault("lessons", []).append(lesson_from_row(row, axis))
    if data["champion_candidates"] > 0:
        data["status"] = "active"
        data["next_action"] = "refine_or_controlled_combo"
    elif data["worse_drawdown_runs"] >= 3 or data["zero_trade_runs"] >= 2:
        data["status"] = "cooldown"
        data["next_action"] = "skip_until_new_evidence"
    elif data["duplicate_runs"] >= 2:
        data["status"] = "exhausted"
        data["next_action"] = "avoid_duplicates"


def update_axis_failure(axis_memory: dict[str, Any], axis: str, classification: str) -> None:
    data = axis_memory["axes"].setdefault(axis, {"status": "active", "failures": [], "lessons": []})
    data.setdefault("failures", []).append(classification)


def save_progress(args: argparse.Namespace, state: dict[str, Any], axis_memory: dict[str, Any], batch_rows: list[dict[str, Any]], parent_run_id: str) -> None:
    rows = load_existing_dd_first_rows(args.runs_dir, args.min_trades, parent_run_id=parent_run_id)
    if not batch_rows:
        batch_rows = infer_daemon_batch_rows(rows)
    state["completed_runs"] = len([r for r in rows if completed_run(Path(args.runs_dir) / str(r.get("run_id")))])
    state["useful_candidates"] = len([r for r in rows if is_champion_candidate(r, args.min_trades)])
    write_dd_first_summary(Path(args.reports_dir) / "dd_first_summary.csv", rows)
    champions = select_champions(rows, args.min_trades)
    state["champions_found"] = champion_count(champions)
    write_json(Path(args.state_dir) / "dd_first_champions.json", champions)
    write_champion_reports(args.reports_dir, champions)
    write_batch_reports(args.reports_dir, batch_rows)
    write_daemon_summary(args.reports_dir, state, axis_memory, champions)
    save_axis_memory(args.state_dir, axis_memory)
    write_axis_summary(args.reports_dir, axis_memory)
    save_daemon_state(args.state_dir, state)


def infer_daemon_batch_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    inferred = []
    for row in rows:
        run_id = str(row.get("run_id", ""))
        if not run_id.startswith("DDDAEMON_"):
            continue
        parts = run_id.split("_", 2)
        batch_id = f"DDBATCH_{parts[1]}" if len(parts) > 1 else "DDBATCH_UNKNOWN"
        inferred.append(row_to_batch_row(batch_id, row, row.get("axis") or "dynamic_regime_exposure", "completed"))
    return inferred


def write_champion_reports(reports_dir: str, champions: dict[str, Any]) -> None:
    rows = []
    for name in ["dd_min_champion", "balanced_dd_champion", "return_with_dd_guard_champion"]:
        row = champions.get(name)
        if row:
            rows.append({"champion_type": name, **compact_row(row)})
    write_csv(Path(reports_dir) / "dd_first_champions.csv", rows)
    write_csv(Path(reports_dir) / "dd_first_pareto_frontier.csv", [compact_row(r) for r in champions.get("pareto_frontier", [])])


def write_batch_reports(reports_dir: str, rows: list[dict[str, Any]]) -> None:
    cols = ["batch_id", "strategy_id", "axis", "run_id", "status", "decision", "cagr", "spy_cagr", "excess_cagr", "max_drawdown", "parent_drawdown", "dd_improvement", "calmar", "trades", "years_wl", "error", "repair_action", "lesson"]
    write_csv(Path(reports_dir) / "dd_first_daemon_batches.csv", rows, cols)
    latest = rows[-5:]
    lines = ["# DD_FIRST Latest Batch", "", "| strategy | axis | run | CAGR | DD | Calmar | trades | decision |", "|---|---|---|---:|---:|---:|---:|---|"]
    for row in latest:
        lines.append(f"| {row.get('strategy_id')} | {row.get('axis')} | {row.get('run_id')} | {row.get('cagr')} | {row.get('max_drawdown')} | {row.get('calmar')} | {row.get('trades')} | {row.get('decision')} |")
    Path(reports_dir, "dd_first_batch_latest.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_daemon_summary(reports_dir: str, state: dict[str, Any], axis_memory: dict[str, Any], champions: dict[str, Any]) -> None:
    lines = ["# DD_FIRST Autonomous Daemon Summary", "", f"- Status: {state.get('status')}", f"- Batch: {state.get('current_batch')}", f"- Total attempts: {state.get('total_attempts')}", f"- Completed runs: {state.get('completed_runs')}", f"- Champions found: {state.get('champions_found')}", f"- Last error: {state.get('last_error')}", f"- Last lesson: {state.get('last_lesson')}", f"- Next batch plan: {', '.join(state.get('next_batch_plan', []))}", "", "## Champions"]
    for name in ["dd_min_champion", "balanced_dd_champion", "return_with_dd_guard_champion"]:
        row = champions.get(name) or {}
        lines.append(f"- {name}: {row.get('strategy_id', '')} / {row.get('run_id', '')} DD={row.get('strategy_max_drawdown_pct', '')} CAGR={row.get('strategy_cagr_pct', '')}")
    lines.append("\n## Axis status")
    for axis, data in axis_memory.get("axes", {}).items():
        lines.append(f"- {axis}: {data.get('status')} attempts={data.get('attempts', 0)} champions={data.get('champion_candidates', 0)}")
    Path(reports_dir, "dd_first_daemon_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def row_to_batch_row(batch_id: str, row: dict[str, Any], axis: str, status: str) -> dict[str, Any]:
    return {"batch_id": batch_id, "strategy_id": row.get("strategy_id"), "axis": axis, "run_id": row.get("run_id"), "status": status, "decision": row.get("dd_first_decision") or row.get("decision"), "cagr": row.get("strategy_cagr_pct"), "spy_cagr": row.get("spy_cagr_pct"), "excess_cagr": row.get("excess_cagr_pct"), "max_drawdown": row.get("strategy_max_drawdown_pct"), "parent_drawdown": row.get("parent_max_drawdown_pct"), "dd_improvement": row.get("drawdown_improvement_vs_parent_pct"), "calmar": row.get("calmar_ratio"), "trades": row.get("trades"), "years_wl": f"{row.get('years_beating_spy')}/{row.get('years_losing_to_spy')}", "error": "", "repair_action": "", "lesson": lesson_from_row(row, axis)}


def compact_row(row: dict[str, Any]) -> dict[str, Any]:
    keys = ["run_id", "strategy_id", "strategy_cagr_pct", "spy_cagr_pct", "excess_cagr_pct", "strategy_max_drawdown_pct", "parent_max_drawdown_pct", "drawdown_improvement_vs_parent_pct", "calmar_ratio", "years_beating_spy", "years_losing_to_spy", "months_beating_spy", "months_losing_to_spy", "trades", "dd_first_decision", "value_delivered"]
    return {k: row.get(k, "") for k in keys}


def write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = columns or sorted({k for row in rows for k in row})
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns, delimiter=";", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: csv_value(row.get(k, "")) for k in columns})


def append_learning(state_dir: str, row: dict[str, Any], axis: str, spec: dict[str, Any]) -> None:
    path = Path(state_dir) / "dd_first_learning_memory.json"
    payload = read_json(path) if path.exists() else {"events": []}
    payload.setdefault("events", []).append({"created_at": datetime.now(timezone.utc).isoformat(), "axis": axis, "run_id": row.get("run_id"), "strategy_id": row.get("strategy_id"), "decision": row.get("dd_first_decision"), "completed_run": row.get("completed_run"), "useful_candidate": row.get("useful_candidate"), "value_delivered": row.get("value_delivered"), "lesson": lesson_from_row(row, axis), "parameter_patch": spec.get("patch", {})})
    write_json(path, payload)


def lesson_from_row(row: dict[str, Any], axis: str) -> str:
    if _i(row, "trades") == 0:
        return f"{axis}: zero trades, not useful."
    if _f(row, "drawdown_improvement_vs_parent_pct") < 0:
        return f"{axis}: worsened drawdown, not DD_FIRST."
    if is_champion_candidate(row):
        return f"{axis}: champion candidate under DD_FIRST constraints."
    return f"{axis}: informative but below champion thresholds."


def classify_daemon_error(error: str) -> str:
    base = classify_error(error)
    if base == "missing_field":
        return "data_or_column_error"
    if base == "unknown_error":
        lower = error.lower()
        if "duplicate" in lower or "metric_no_effect" in lower:
            return "duplicate_or_noop"
        if "0 trades" in lower:
            return "zero_trades"
    return base


def should_stop(args: argparse.Namespace, state: dict[str, Any], started: float, axis_memory: dict[str, Any]) -> bool:
    if int(state.get("completed_batches", 0)) >= args.max_batches:
        state["stop_reason"] = "max_batches_reached"
        return True
    if int(state.get("total_attempts", 0)) >= args.max_total_attempts:
        state["stop_reason"] = "max_total_attempts_reached"
        return True
    if (time.monotonic() - started) / 3600 >= args.max_wall_clock_hours:
        state["stop_reason"] = "max_wall_clock_hours_reached"
        return True
    active = [a for a, d in axis_memory.get("axes", {}).items() if d.get("status") == "active"]
    if not active:
        state["stop_reason"] = "all_axes_exhausted_or_cooldown"
        return True
    return False


def champion_count(champions: dict[str, Any]) -> int:
    ids = {champions.get(k, {}).get("strategy_id") for k in ["dd_min_champion", "balanced_dd_champion", "return_with_dd_guard_champion"] if champions.get(k)}
    return len(ids)


def existing_strategy_ids(registry_path: str) -> set[str]:
    return {str(r.get("strategy_id")) for r in read_json(registry_path).get("strategies", [])}


def next_daemon_run_id(runs_dir: str, batch_number: int, strategy_id: str) -> str:
    stem = f"DDDAEMON_{batch_number:03d}_{strategy_id}"[:130]
    path = Path(runs_dir) / stem
    i = 1
    while path.exists():
        i += 1
        path = Path(runs_dir) / f"{stem}_{i}"
    return path.name


def validate_full_history_parent(runs_dir: str, parent_run_id: str) -> None:
    parent = Path(runs_dir) / parent_run_id
    required = ["metrics.json", "run_manifest.json", "trades.csv", "equity_curve.csv"]
    missing = [name for name in required if not (parent / name).exists()]
    if missing:
        raise FileNotFoundError(f"Missing full-history parent artifacts for {parent_run_id}: {missing}")


def assert_parent_baseline_unchanged(state_dir: str, snapshot: dict[str, str]) -> None:
    if _state_snapshot(state_dir) != snapshot:
        raise RuntimeError("Parent/baseline lock compromised.")


def _state_snapshot(state_dir: str) -> dict[str, str]:
    out = {}
    for name in ["current_parent.json", "current_baseline.json"]:
        p = Path(state_dir) / name
        out[name] = p.read_text(encoding="utf-8-sig") if p.exists() else ""
    return out


def latest_lesson(state_dir: str) -> str:
    path = Path(state_dir) / "dd_first_learning_memory.json"
    if not path.exists():
        return ""
    events = read_json(path).get("events", [])
    return str(events[-1].get("lesson", "")) if events else ""


def _f(row: dict[str, Any], key: str) -> float:
    try:
        return float(str(row.get(key, 0)).replace(",", "."))
    except (TypeError, ValueError):
        return 0.0


def _i(row: dict[str, Any], key: str) -> int:
    try:
        return int(row.get(key, 0))
    except (TypeError, ValueError):
        return 0


def csv_value(value: Any) -> Any:
    if isinstance(value, float):
        return str(round(value, 6)).replace(".", ",")
    return value


if __name__ == "__main__":
    raise SystemExit(main())
