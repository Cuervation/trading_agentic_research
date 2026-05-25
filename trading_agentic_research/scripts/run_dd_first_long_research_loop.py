"""Long-running, resumable DD_FIRST research loop.

This wrapper keeps the DD_FIRST series isolated from normal research state:
it never passes --allow-parent-update, never writes current_parent/current_baseline,
and only creates candidate configs, DD_FIRST reports, and DD_FIRST state.
"""

from __future__ import annotations

import argparse
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

from backtester.dd_first import evaluate_dd_first_run, row_from_audit_or_run, write_dd_first_summary
from scripts.governance import has_real_strategy_change, stable_json_hash
from scripts.run_dd_first_autofix_loop import (
    FAMILY,
    _candidate_strategy_ids,
    _config_path_for,
    _csv_columns,
    _is_duplicate_or_noop,
    _next_run_id,
    _preflight,
    attempt_repair,
    classify_error,
    is_real_completed_run,
    read_json,
    read_jsonl,
    run_one_candidate,
    write_json,
    write_jsonl,
)

DEFAULT_PARENT_CONFIG = "configs/generated/HYP_AUTO_TIME_SERIES_MOMENTUM_SEED.json"
LONG_STATE_FILE = "dd_first_loop_state.json"
AXIS_MEMORY_FILE = "dd_first_axis_memory.json"
LEARNING_FILE = "dd_first_learning_memory.json"
AXIS_SUMMARY_FILE = "dd_first_axis_summary.csv"

AXIS_PRIORITY = [
    "exposure_reduction_partial",
    "soft_spy_regime",
    "low_vol_momentum_soft_penalty",
    "anti_extension_soft_filter",
    "drawdown_proxy_filter",
    "trailing_and_exit_refinement",
    "diversification_cap",
]

REQUIRED_RUN_FILES = [
    "equity_curve.csv",
    "trades.csv",
    "metrics.json",
    "spy_comparison_daily.csv",
    "spy_comparison_monthly.csv",
    "spy_comparison_yearly.csv",
    "spy_comparison_summary.json",
    "audit.json",
    "summary.md",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a long, causal DD_FIRST research loop.")
    parser.add_argument("--target-useful-candidates", type=int, default=3)
    parser.add_argument("--max-total-attempts", type=int, default=80)
    parser.add_argument("--max-completed-runs", type=int, default=30)
    parser.add_argument("--max-wall-clock-hours", type=float, default=10.0)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--generation-mode", choices=["causal"], default="causal")
    parser.add_argument("--only-axis", default=None)
    parser.add_argument("--strategy-ids", default=None, help="Comma-separated strategy ids to run before opening any other generation.")
    parser.add_argument("--weekly-file", default=None)
    parser.add_argument("--daily-folder", default=None)
    parser.add_argument("--parent-strategy-config", default=DEFAULT_PARENT_CONFIG)
    parser.add_argument("--parent-run-id", default=None)
    parser.add_argument("--project-config", default="configs/project_config.json")
    parser.add_argument("--strategy-registry", default="configs/strategy_registry.json")
    parser.add_argument("--hypothesis-bank", default="bibliography/hypothesis_bank.jsonl")
    parser.add_argument("--runs-dir", default="runs")
    parser.add_argument("--reports-dir", default="reports")
    parser.add_argument("--state-dir", default="state")
    parser.add_argument("--min-trades", type=int, default=50)
    parser.add_argument("--max-repair-cycles", type=int, default=5)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    start = time.monotonic()
    state = load_loop_state(args.state_dir, resume=args.resume)
    axis_memory = load_axis_memory(args.state_dir)
    parent_snapshot = _read_state_snapshot(args.state_dir)
    rows = load_existing_dd_first_rows(args.runs_dir, args.min_trades, parent_run_id=None)

    state.update(
        {
            "status": "running",
            "generation_mode": args.generation_mode,
            "stop_reason": "",
            "last_error": "",
            "started_at": state.get("started_at") or datetime.now(timezone.utc).isoformat(),
        }
    )
    save_loop_state(args.state_dir, state)

    try:
        weekly_file, daily_folder, parent_run_id = _preflight(args)
        parent_run_id = resolve_parent_run_id(args, parent_run_id)
        state["comparison_parent_run_id"] = parent_run_id
        weekly_columns = _csv_columns(weekly_file)
        refresh_axis_memory_support(axis_memory, weekly_columns)
        ensure_requested_strategy_ids(args, weekly_columns, axis_memory)
        _assert_parent_baseline_unchanged(args.state_dir, parent_snapshot)
    except Exception as exc:
        state.update({"status": "failed", "stop_reason": "preflight_failed", "last_error": str(exc)})
        save_loop_state(args.state_dir, state)
        write_loop_summary(args, rows, state, axis_memory)
        print(f"DD_FIRST long loop preflight failed: {exc}")
        return 2

    repair_counts: dict[str, int] = {}

    while True:
        rows = load_existing_dd_first_rows(args.runs_dir, args.min_trades, parent_run_id=parent_run_id)
        rebuild_axis_memory_from_rows(axis_memory, rows, args.min_trades)
        completed_runs = [r for r in rows if completed_run(Path(args.runs_dir) / str(r.get("run_id")))]
        useful_rows = [r for r in completed_runs if useful_candidate(r, args.min_trades)]
        state["completed_real_runs"] = len(completed_runs)
        state["useful_candidates"] = len(useful_rows)

        reason_to_stop = stop_reason(args, state, axis_memory, start)
        if reason_to_stop:
            state["stop_reason"] = reason_to_stop
            break

        _assert_parent_baseline_unchanged(args.state_dir, parent_snapshot)
        state["current_cycle"] = int(state.get("current_cycle", 0)) + 1

        strategy_id = next_pending_strategy_id(args, axis_memory)
        if strategy_id is None:
            generated = generate_next_causal_hypothesis(
                parent_config_path=args.parent_strategy_config,
                registry_path=args.strategy_registry,
                hypothesis_bank_path=args.hypothesis_bank,
                weekly_columns=weekly_columns,
                axis_memory=axis_memory,
                only_axis=args.only_axis,
                allowed_strategy_ids=requested_strategy_ids(args),
            )
            if generated is None:
                mark_axes_without_remaining_specs(axis_memory, args.strategy_registry, weekly_columns)
                state["stop_reason"] = "no_more_causal_hypotheses"
                break
            strategy_id = generated
            state.setdefault("generated_hypotheses", []).append(strategy_id)

        axis = axis_from_config(_config_path_for(args.strategy_registry, strategy_id))
        state["current_axis"] = axis
        state["total_attempts"] = int(state.get("total_attempts", 0)) + 1
        axis_event(axis_memory, axis, attempts=1)
        run_id = _next_run_id(args.runs_dir, strategy_id, int(state["total_attempts"]))
        print(f"DD_FIRST long attempt {state['total_attempts']}: axis={axis} strategy={strategy_id} run={run_id}")

        result = run_one_candidate(
            run_id=run_id,
            strategy_id=strategy_id,
            config_path=_config_path_for(args.strategy_registry, strategy_id),
            weekly_file=weekly_file,
            daily_folder=daily_folder,
            parent_run_id=parent_run_id,
            args=args,
        )
        state["last_run_id"] = run_id

        if not result["ok"]:
            classification = classify_error(result["error"])
            state["failed_attempts"] = int(state.get("failed_attempts", 0)) + 1
            state["last_error"] = f"{classification}: {result['error'][:1000]}"
            axis_memory["axes"][axis]["failures"].append(classification)
            repaired = attempt_repair(classification, _config_path_for(args.strategy_registry, strategy_id), weekly_columns)
            if repaired:
                state["repaired_errors"] = int(state.get("repaired_errors", 0)) + 1
                repair_counts[classification] = repair_counts.get(classification, 0) + 1
                if repair_counts[classification] >= args.max_repair_cycles:
                    state["stop_reason"] = "same_error_repair_limit"
                    break
            elif classification == "data_error":
                state["stop_reason"] = "no_valid_data"
                break
            else:
                mark_axis_status(axis_memory, axis)
            save_all_state(args, state, axis_memory, rows)
            continue

        row = dict(result["row"])
        row["axis"] = axis
        row["completed_run"] = completed_run(Path(args.runs_dir) / run_id)
        row["useful_candidate"] = useful_candidate(row, args.min_trades)
        update_learning(args.state_dir, row, axis, _parameter_patch(_config_path_for(args.strategy_registry, strategy_id)))
        update_axis_memory(axis_memory, axis, row, args.min_trades)
        state.setdefault("generated_hypotheses", []).append(strategy_id)
        if row.get("dd_first_decision") == "rejected":
            state.setdefault("rejected_hypotheses", []).append(strategy_id)

        rows = load_existing_dd_first_rows(args.runs_dir, args.min_trades, parent_run_id=parent_run_id)
        save_all_state(args, state, axis_memory, rows)

    rows = load_existing_dd_first_rows(args.runs_dir, args.min_trades, parent_run_id=parent_run_id if "parent_run_id" in locals() else None)
    rebuild_axis_memory_from_rows(axis_memory, rows, args.min_trades)
    state["status"] = "completed" if state.get("stop_reason") in {"target_useful_candidates_reached", "max_completed_runs_reached", "requested_strategy_ids_completed"} else "stopped"
    state["completed_real_runs"] = len([r for r in rows if completed_run(Path(args.runs_dir) / str(r.get("run_id")))])
    state["useful_candidates"] = len([r for r in rows if useful_candidate(r, args.min_trades)])
    save_all_state(args, state, axis_memory, rows)
    print(
        "DD_FIRST long loop "
        f"{state['status']}: completed_runs={state['completed_real_runs']} "
        f"useful_candidates={state['useful_candidates']} "
        f"total_attempts={state.get('total_attempts', 0)} "
        f"stop_reason={state.get('stop_reason')}"
    )
    return 0 if state["status"] == "completed" else 2


def load_loop_state(state_dir: str, *, resume: bool) -> dict[str, Any]:
    path = Path(state_dir) / LONG_STATE_FILE
    if resume and path.exists():
        return read_json(path)
    return {
        "status": "initialized",
        "completed_real_runs": 0,
        "useful_candidates": 0,
        "total_attempts": 0,
        "failed_attempts": 0,
        "repaired_errors": 0,
        "generated_hypotheses": [],
        "rejected_hypotheses": [],
        "current_cycle": 0,
        "current_axis": "",
        "stop_reason": "",
        "last_run_id": "",
        "last_error": "",
    }


def save_loop_state(state_dir: str, state: dict[str, Any]) -> None:
    for key in ("generated_hypotheses", "rejected_hypotheses", "exhausted_axes", "cooldown_axes"):
        if isinstance(state.get(key), list):
            state[key] = sorted(set(state[key]))
    state["last_updated_at"] = datetime.now(timezone.utc).isoformat()
    write_json(Path(state_dir) / LONG_STATE_FILE, state)


def load_axis_memory(state_dir: str) -> dict[str, Any]:
    path = Path(state_dir) / AXIS_MEMORY_FILE
    if path.exists():
        payload = read_json(path)
    else:
        payload = {"axes": {}}
    axes = payload.setdefault("axes", {})
    for axis in AXIS_PRIORITY:
        axes.setdefault(
            axis,
            {
                "attempts": 0,
                "completed_runs": 0,
                "useful_candidates": 0,
                "rejected": 0,
                "zero_trade_runs": 0,
                "metric_no_effect_runs": 0,
                "strong_worse_drawdown_runs": 0,
                "failures": [],
                "best_run_id": None,
                "best_drawdown": None,
                "best_cagr": None,
                "best_calmar": None,
                "status": "active",
                "lessons": [],
            },
        )
    return payload


def save_axis_memory(state_dir: str, axis_memory: dict[str, Any]) -> None:
    write_json(Path(state_dir) / AXIS_MEMORY_FILE, axis_memory)


def axis_event(axis_memory: dict[str, Any], axis: str, *, attempts: int = 0) -> None:
    axis_memory["axes"].setdefault(axis, {})
    axis_memory["axes"][axis]["attempts"] = int(axis_memory["axes"][axis].get("attempts", 0)) + attempts


def completed_run(run_dir: Path) -> bool:
    return run_dir.exists() and all((run_dir / name).exists() for name in REQUIRED_RUN_FILES)


def useful_candidate(row: dict[str, Any], min_trades: int = 50) -> bool:
    trades = _as_int(row.get("trades"))
    if trades <= 0 or trades < min_trades or _is_duplicate_or_noop(row):
        return False
    improvement = _as_float(row.get("drawdown_improvement_vs_parent_pct"))
    excess = _as_float(row.get("excess_cagr_pct"))
    calmar = _as_float(row.get("calmar_ratio"))
    parent_calmar = _as_float(row.get("parent_calmar_ratio"))
    years_w = _as_int(row.get("years_beating_spy"))
    years_l = _as_int(row.get("years_losing_to_spy"))
    if improvement < 0:
        return False
    defensive = improvement >= 10 and excess >= 0 and years_w >= years_l
    strong = improvement >= 15 and calmar > parent_calmar and excess > 0 and years_w > years_l
    return defensive or strong


def load_existing_dd_first_rows(runs_dir: str, min_trades: int, parent_run_id: str | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    root = Path(runs_dir)
    if not root.exists():
        return rows
    parent_run_dir = Path(runs_dir) / parent_run_id if parent_run_id else None
    for run_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        if not run_dir.name.startswith("DD_FIRST_"):
            continue
        try:
            manifest_path = run_dir / "run_manifest.json"
            manifest = read_json(manifest_path) if manifest_path.exists() else {}
            if parent_run_dir is not None and manifest.get("parent_run_id") != parent_run_id:
                row = evaluate_dd_first_run(run_dir, parent_run_dir=parent_run_dir, min_trades=min_trades)["dd_first"]
            else:
                row = row_from_audit_or_run(run_dir, parent_run_dir=parent_run_dir, min_trades=min_trades)
        except Exception:
            continue
        cfg_path = run_dir / "run_manifest.json"
        if cfg_path.exists():
            manifest = read_json(cfg_path)
            config = manifest.get("strategy_config_path")
            if config and Path(config).exists():
                row["axis"] = axis_from_config(config)
        rows.append(row)
    return rows


def resolve_parent_run_id(args: argparse.Namespace, fallback_parent_run_id: str) -> str:
    """Choose an apples-to-apples parent run without moving locked parent state.

    The locked parent id can point to the original 2020-2026 run. When the loop
    is run on full-history data, DD_FIRST comparison must use the same parent
    strategy over the longest available comparable period, otherwise every
    full-history candidate is unfairly compared against a shorter parent.
    Passing --parent-run-id keeps explicit user control.
    """
    if args.parent_run_id:
        return fallback_parent_run_id
    parent_cfg = read_json(args.parent_strategy_config)
    parent_strategy_id = str(parent_cfg.get("strategy_id") or "")
    candidates: list[tuple[int, float, str]] = []
    for run_dir in Path(args.runs_dir).iterdir() if Path(args.runs_dir).exists() else []:
        if not run_dir.is_dir() or not (run_dir / "run_manifest.json").exists() or not (run_dir / "metrics.json").exists():
            continue
        try:
            manifest = read_json(run_dir / "run_manifest.json")
            metrics = read_json(run_dir / "metrics.json").get("strategy", {})
        except Exception:
            continue
        if manifest.get("strategy_id") != parent_strategy_id:
            continue
        span = _date_span_days(metrics.get("start_date"), metrics.get("end_date"))
        candidates.append((span, run_dir.stat().st_mtime, run_dir.name))
    if not candidates:
        return fallback_parent_run_id
    return sorted(candidates, reverse=True)[0][2]


def next_pending_strategy_id(args: argparse.Namespace, axis_memory: dict[str, Any]) -> str | None:
    attempted = set(_attempted_strategy_ids(args.runs_dir))
    requested = requested_strategy_ids(args)
    for strategy_id in _candidate_strategy_ids(args.strategy_registry):
        if requested and strategy_id not in requested:
            continue
        if strategy_id in attempted:
            continue
        try:
            axis = axis_from_config(_config_path_for(args.strategy_registry, strategy_id))
        except Exception:
            axis = ""
        if args.only_axis and axis != args.only_axis:
            continue
        if axis in axis_memory.get("axes", {}) and axis_memory["axes"][axis].get("status") in {"cooldown", "exhausted"}:
            continue
        return strategy_id
    return None


def generate_next_causal_hypothesis(
    *,
    parent_config_path: str,
    registry_path: str,
    hypothesis_bank_path: str,
    weekly_columns: set[str],
    axis_memory: dict[str, Any],
    only_axis: str | None = None,
    allowed_strategy_ids: set[str] | None = None,
) -> str | None:
    parent = read_json(parent_config_path)
    existing = _existing_config_hashes(registry_path)
    used_ids = set(_candidate_strategy_ids(registry_path))
    for spec in _causal_specs(weekly_columns):
        if only_axis and spec["axis"] != only_axis:
            continue
        axis_state = axis_memory["axes"].get(spec["axis"], {})
        if axis_state.get("status") in {"cooldown", "exhausted"}:
            continue
        sid = spec["strategy_id"]
        if allowed_strategy_ids and sid not in allowed_strategy_ids:
            continue
        if sid in used_ids:
            continue
        cfg = build_causal_config(parent, spec, weekly_columns)
        if cfg is None:
            axis_state["status"] = "exhausted"
            axis_state.setdefault("lessons", []).append(f"Axis {spec['axis']} unsupported by available columns.")
            continue
        if not validate_generated_config(parent, cfg, weekly_columns, existing):
            continue
        write_strategy_and_hypothesis(cfg, registry_path, hypothesis_bank_path)
        return sid
    return None


def requested_strategy_ids(args: argparse.Namespace) -> set[str]:
    raw = str(args.strategy_ids or "").strip()
    if not raw:
        return set()
    return {part.strip() for part in raw.split(",") if part.strip()}


def ensure_requested_strategy_ids(args: argparse.Namespace, weekly_columns: set[str], axis_memory: dict[str, Any]) -> None:
    requested = requested_strategy_ids(args)
    if not requested:
        return
    parent = read_json(args.parent_strategy_config)
    existing = set(_candidate_strategy_ids(args.strategy_registry))
    existing_hashes = _existing_config_hashes(args.strategy_registry)
    specs = {spec["strategy_id"]: spec for spec in _causal_specs(weekly_columns)}
    for strategy_id in requested:
        if strategy_id in existing:
            continue
        spec = specs.get(strategy_id)
        if spec is None:
            raise ValueError(f"Requested strategy id is not a supported causal spec: {strategy_id}")
        if args.only_axis and spec["axis"] != args.only_axis:
            raise ValueError(f"Requested strategy {strategy_id} belongs to axis={spec['axis']}, not --only-axis={args.only_axis}")
        cfg = build_causal_config(parent, spec, weekly_columns)
        if cfg is None or not validate_generated_config(parent, cfg, weekly_columns, existing_hashes):
            raise ValueError(f"Requested strategy cannot be generated safely: {strategy_id}")
        write_strategy_and_hypothesis(cfg, args.strategy_registry, args.hypothesis_bank)
        axis_memory["axes"].setdefault(spec["axis"], {}).setdefault("status", "active")


def refresh_axis_memory_support(axis_memory: dict[str, Any], weekly_columns: set[str]) -> None:
    """Revive axes that were marked unsupported before column-aware specs improved."""
    for axis, data in axis_memory.get("axes", {}).items():
        if data.get("status") != "exhausted" or int(data.get("attempts", 0)) > 0:
            continue
        if any(_spec_can_build(spec, weekly_columns) for spec in _causal_specs(weekly_columns) if spec["axis"] == axis):
            data["status"] = "active"
            data.setdefault("lessons", []).append("Axis revived because current weekly columns support a causal variant.")


def mark_axes_without_remaining_specs(axis_memory: dict[str, Any], registry_path: str, weekly_columns: set[str]) -> None:
    used_ids = set(_candidate_strategy_ids(registry_path))
    for axis, data in axis_memory.get("axes", {}).items():
        if data.get("status") in {"cooldown", "exhausted"}:
            continue
        remaining = [
            spec
            for spec in _causal_specs(weekly_columns)
            if spec["axis"] == axis and spec["strategy_id"] not in used_ids and _spec_can_build(spec, weekly_columns)
        ]
        if not remaining and int(data.get("useful_candidates", 0)) == 0:
            data["status"] = "exhausted"
            data.setdefault("lessons", []).append("No remaining non-duplicate causal variants for this axis.")


def _spec_can_build(spec: dict[str, Any], weekly_columns: set[str]) -> bool:
    patch = spec.get("patch", {})
    if spec["axis"] == "diversification_cap":
        return "sector" in weekly_columns or "industry" in weekly_columns
    if "ranking.low_vol_penalty_field" in patch:
        return _first_existing(weekly_columns, patch["ranking.low_vol_penalty_field"]) is not None
    return True


def build_causal_config(parent: dict[str, Any], spec: dict[str, Any], weekly_columns: set[str]) -> dict[str, Any] | None:
    cfg = deepcopy(parent)
    sid = spec["strategy_id"]
    axis = spec["axis"]
    cfg.update(
        {
            "strategy_id": sid,
            "hypothesis_id": sid,
            "strategy_family": FAMILY,
            "generation_axis": axis,
            "parent_hypothesis_id": parent.get("hypothesis_id") or parent.get("strategy_id"),
            "parent_strategy_id": parent.get("strategy_id"),
            "bibliography_basis": [{"source_id": "SRC_TIME_SERIES_MOMENTUM_SEED"}],
            "empirical_basis": [
                {
                    "run_id": "DD_FIRST_SERIES",
                    "reason": "Prior DD_FIRST runs showed binary filters can kill trades; generated causal one-axis refinement.",
                }
            ],
            "causal_mechanism": spec["causal_mechanism"],
            "expected_effect": spec["expected_effect"],
            "falsification_rule": spec["falsification_rule"],
            "novelty_reason": spec["novelty_reason"],
            "why_not_duplicate": spec["why_not_duplicate"],
            "risk_of_overfit": spec["risk_of_overfit"],
            "expected_trade_count_effect": spec["expected_trade_count_effect"],
            "evaluation_mode": "dd_first",
        }
    )
    if axis == "exposure_reduction_partial" and any(token in sid for token in ("EXPOSURE_55", "EXPOSURE_60", "EXPOSURE_65", "EXPOSURE_70")):
        cfg["empirical_basis"] = [
            {"run_id": "DD_FIRST_02_HYP_DD_FIRST_AUTO002_EXPOSURE_50_V1", "reason": "50% exposure produced the strongest drawdown reduction with positive excess CAGR."},
            {"run_id": "DD_FIRST_01_HYP_DD_FIRST_AUTO002_EXPOSURE_75_V1", "reason": "75% exposure preserved more CAGR while still improving drawdown materially."},
            {"run_id": "DD_FIRST_03_HYP_DD_FIRST_AUTO002_EXPOSURE_85_V1", "reason": "85% exposure defined the upper bound where drawdown improvement became marginal."},
        ]
    changed = []
    patch = spec["patch"]
    if axis == "diversification_cap":
        if "sector" not in weekly_columns and "industry" not in weekly_columns:
            return None
    if "risk_management.max_gross_exposure_pct" in patch:
        cfg["risk_management"] = {**cfg.get("risk_management", {}), "max_gross_exposure_pct": patch["risk_management.max_gross_exposure_pct"]}
        changed.append("risk_management.max_gross_exposure_pct")
    if "market_filter.soft_weak_regime_top_n" in patch:
        cfg["market_filter"] = {
            **cfg.get("market_filter", {}),
            "soft_weak_regime_top_n": patch["market_filter.soft_weak_regime_top_n"],
            "fallback_allow_if_missing_spy_metric": True,
        }
        changed.extend(["market_filter.soft_weak_regime_top_n", "market_filter.fallback_allow_if_missing_spy_metric"])
    if "risk_filters.conditions" in patch:
        conditions = []
        for cond in patch["risk_filters.conditions"]:
            if cond["field"] not in weekly_columns:
                cond = {**cond, "enabled_if_field_exists": True}
            conditions.append(cond)
        cfg["risk_filters"] = {**cfg.get("risk_filters", {}), "conditions": conditions}
        changed.append("risk_filters.conditions")
    if "risk_management.trailing_stop_pct" in patch:
        cfg["risk_management"] = {**cfg.get("risk_management", {}), "trailing_stop_pct": patch["risk_management.trailing_stop_pct"]}
        changed.append("risk_management.trailing_stop_pct")
    if "entry_rule.top_n" in patch:
        cfg["entry_rule"] = {**cfg.get("entry_rule", {}), "top_n": patch["entry_rule.top_n"]}
        changed.append("entry_rule.top_n")
    if "ranking.low_vol_penalty_field" in patch:
        field = _first_existing(weekly_columns, patch["ranking.low_vol_penalty_field"])
        if field is None:
            return None
        cfg["ranking"] = {**cfg.get("ranking", {}), "secondary_penalty_field": field, "secondary_penalty_weight": patch["ranking.secondary_penalty_weight"]}
        changed.extend(["ranking.secondary_penalty_field", "ranking.secondary_penalty_weight"])
    cfg["changed_parameters"] = changed
    cfg["strategy_overrides"] = _parameter_patch_from_config(cfg)
    return cfg


def validate_generated_config(parent: dict[str, Any], cfg: dict[str, Any], weekly_columns: set[str], existing_hashes: set[str]) -> bool:
    if not cfg.get("changed_parameters") or not cfg.get("strategy_overrides"):
        return False
    if not has_real_strategy_change(parent, cfg):
        return False
    ranking_field = str(cfg.get("ranking", {}).get("field") or cfg.get("entry_rule", {}).get("by") or "")
    if ranking_field and ranking_field not in weekly_columns:
        return False
    dominant = cfg.get("generation_axis")
    if not dominant or any(dominant != cfg.get("generation_axis") for _ in [0]):
        return False
    for cond in cfg.get("risk_filters", {}).get("conditions", []) or []:
        if cond.get("field") not in weekly_columns and not cond.get("enabled_if_field_exists"):
            return False
    return stable_json_hash(_strategy_payload(cfg)) not in existing_hashes


def write_strategy_and_hypothesis(cfg: dict[str, Any], registry_path: str, hypothesis_bank_path: str) -> None:
    strategy_id = cfg["strategy_id"]
    config_path = Path("configs/generated") / f"{strategy_id}.json"
    write_json(config_path, cfg)

    registry = read_json(registry_path)
    rows = [r for r in registry.get("strategies", []) if r.get("strategy_id") != strategy_id]
    rows.append(
        {
            "strategy_id": strategy_id,
            "strategy_family": FAMILY,
            "status": "candidate",
            "benchmark_ticker": "SPY",
            "config_path": config_path.as_posix(),
            "signal_frequency": "weekly",
            "execution_frequency": "daily",
            "rebalance_frequency": "monthly",
            "parent_strategy_id": cfg.get("parent_strategy_id"),
            "evaluation_mode": "dd_first",
            "generation_axis": cfg.get("generation_axis"),
            "notes": f"DD_FIRST long-loop causal candidate axis={cfg.get('generation_axis')}.",
        }
    )
    registry["strategies"] = rows
    write_json(registry_path, registry)

    bank_rows = [r for r in read_jsonl(hypothesis_bank_path) if r.get("hypothesis_id") != strategy_id]
    bank_rows.append(
        {
            "hypothesis_id": strategy_id,
            "family": FAMILY,
            "status": "candidate",
            "required_spy_comparison": "monthly_and_yearly",
            "evaluation_mode": "dd_first",
            "parent_strategy_id": cfg.get("parent_strategy_id"),
            "parent_hypothesis_id": cfg.get("parent_hypothesis_id"),
            "generation_axis": cfg.get("generation_axis"),
            "bibliography_basis": cfg.get("bibliography_basis", []),
            "empirical_basis": cfg.get("empirical_basis", []),
            "causal_mechanism": cfg.get("causal_mechanism"),
            "expected_effect": cfg.get("expected_effect"),
            "falsification_rule": cfg.get("falsification_rule"),
            "changed_parameters": cfg.get("changed_parameters", []),
            "strategy_overrides": cfg.get("strategy_overrides", {}),
            "novelty_reason": cfg.get("novelty_reason"),
            "why_not_duplicate": cfg.get("why_not_duplicate"),
            "risk_of_overfit": cfg.get("risk_of_overfit"),
            "expected_trade_count_effect": cfg.get("expected_trade_count_effect"),
        }
    )
    write_jsonl(hypothesis_bank_path, bank_rows)


def _causal_specs(weekly_columns: set[str]) -> list[dict[str, Any]]:
    return [
        _spec("exposure_reduction_partial", "HYP_DD_FIRST_AUTO002_EXPOSURE_75_V1", {"risk_management.max_gross_exposure_pct": 75}, "Reduce gross exposure to 75% while preserving the parent signal set."),
        _spec("exposure_reduction_partial", "HYP_DD_FIRST_AUTO002_EXPOSURE_50_V1", {"risk_management.max_gross_exposure_pct": 50}, "Reduce gross exposure to 50% without turning the strategy off."),
        _spec("exposure_reduction_partial", "HYP_DD_FIRST_AUTO002_EXPOSURE_55_V1", {"risk_management.max_gross_exposure_pct": 55}, "Monotonic refinement between 50% and 75% to recover CAGR while keeping most drawdown reduction."),
        _spec("exposure_reduction_partial", "HYP_DD_FIRST_AUTO002_EXPOSURE_60_V1", {"risk_management.max_gross_exposure_pct": 60}, "Monotonic refinement between 50% and 75% to recover CAGR while keeping material drawdown reduction."),
        _spec("exposure_reduction_partial", "HYP_DD_FIRST_AUTO002_EXPOSURE_65_V1", {"risk_management.max_gross_exposure_pct": 65}, "Monotonic refinement between 50% and 75% to find the best drawdown/CAGR tradeoff."),
        _spec("exposure_reduction_partial", "HYP_DD_FIRST_AUTO002_EXPOSURE_70_V1", {"risk_management.max_gross_exposure_pct": 70}, "Monotonic refinement close to 75% to test whether CAGR improves without giving back too much drawdown."),
        _spec("exposure_reduction_partial", "HYP_DD_FIRST_AUTO002_EXPOSURE_85_V1", {"risk_management.max_gross_exposure_pct": 85}, "Milder exposure reduction to recover CAGR if 50/75 are too defensive."),
        _spec("soft_spy_regime", "HYP_DD_FIRST_AUTO002_SOFT_SPY_TOPN_8_V1", {"market_filter.soft_weak_regime_top_n": 8}, "In weak SPY regime, reduce new entries instead of going fully to cash."),
        _spec("soft_spy_regime", "HYP_DD_FIRST_AUTO002_SOFT_SPY_TOPN_5_V1", {"market_filter.soft_weak_regime_top_n": 5}, "Stronger soft regime throttle that should still allow trades."),
        _spec("low_vol_momentum_soft_penalty", "HYP_DD_FIRST_AUTO002_LOWVOL_PENALTY_V1", {"ranking.low_vol_penalty_field": ["weekly_range_pct", "atr_14w_pct", "volatility_12w_pct", "daily_range_pct", "atr_14_pct", "realized_vol_13w_pct"], "ranking.secondary_penalty_weight": 0.15}, "Penalize volatile momentum names without making low-vol a hard filter."),
        _spec("low_vol_momentum_soft_penalty", "HYP_DD_FIRST_AUTO002_LOWVOL_PENALTY_LIGHT_V1", {"ranking.low_vol_penalty_field": ["weekly_range_pct", "atr_14w_pct", "volatility_12w_pct"], "ranking.secondary_penalty_weight": 0.05}, "Apply a lighter volatility penalty if the first penalty over-rotates away from momentum."),
        _spec("anti_extension_soft_filter", "HYP_DD_FIRST_AUTO002_ANTI_EXTENSION_SMA52_80_V1", {"risk_filters.conditions": [{"field": "close_vs_sma52w_pct", "operator": "<=", "value": 80, "enabled_if_field_exists": True}]}, "Avoid extremely extended entries while preserving the parent momentum ranking."),
        _spec("anti_extension_soft_filter", "HYP_DD_FIRST_AUTO002_ANTI_EXTENSION_SMA20W_60_V1", {"risk_filters.conditions": [{"field": "close_vs_sma20w_pct", "operator": "<=", "value": 60, "enabled_if_field_exists": True}]}, "Avoid shorter-window over-extension without changing the parent ranking."),
        _spec("drawdown_proxy_filter", "HYP_DD_FIRST_AUTO002_DD_PROXY_26W_V2", {"risk_filters.conditions": [{"field": "drawdown_from_high_26w_pct", "operator": ">=", "value": -30, "enabled_if_field_exists": True}]}, "Avoid names already showing dangerous local drawdown using the available 26w drawdown-from-high proxy."),
        _spec("drawdown_proxy_filter", "HYP_DD_FIRST_AUTO002_DD_PROXY_13W_V1", {"risk_filters.conditions": [{"field": "drawdown_from_high_13w_pct", "operator": ">=", "value": -20, "enabled_if_field_exists": True}]}, "Avoid names breaking down on a faster 13w drawdown proxy."),
        _spec("trailing_and_exit_refinement", "HYP_DD_FIRST_AUTO002_TRAILING_24_V1", {"risk_management.trailing_stop_pct": 24}, "Try a less aggressive trailing stop after trailing 18 worsened drawdown."),
        _spec("trailing_and_exit_refinement", "HYP_DD_FIRST_AUTO002_TOPN_12_V1", {"entry_rule.top_n": 12}, "Reduce concentration moderately without changing ranking."),
        _spec("diversification_cap", "HYP_DD_FIRST_AUTO002_DIVERSIFICATION_CAP_V1", {}, "Use sector/industry caps only if those columns exist."),
    ]


def _spec(axis: str, strategy_id: str, patch: dict[str, Any], claim: str) -> dict[str, Any]:
    return {
        "axis": axis,
        "strategy_id": strategy_id,
        "patch": patch,
        "causal_mechanism": claim,
        "expected_effect": "Lower max drawdown first, preserve enough trades, then retain positive excess CAGR versus SPY.",
        "falsification_rule": "Reject if drawdown worsens versus parent, trades fall below minimum, artifacts duplicate parent, or SPY excess turns negative without material drawdown improvement.",
        "novelty_reason": f"Tests a deterministic one-axis DD_FIRST change: {axis}.",
        "why_not_duplicate": "Strategy id and strategy_overrides are checked against existing registered configs before writing.",
        "risk_of_overfit": "Single-axis causal change; no parameter search over historical winners.",
        "expected_trade_count_effect": "Should preserve trade count unless the axis is explicitly a soft throttle.",
    }


def update_learning(state_dir: str, row: dict[str, Any], axis: str, parameter_patch: dict[str, Any]) -> None:
    path = Path(state_dir) / LEARNING_FILE
    payload = read_json(path) if path.exists() else {"events": []}
    event = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "axis": axis,
        "parameter_patch": parameter_patch,
        "completed_run": bool(row.get("completed_run")),
        "useful_candidate": bool(row.get("useful_candidate")),
        "run_id": row.get("run_id"),
        "strategy_id": row.get("strategy_id"),
        "hypothesis_id": row.get("hypothesis_id"),
        "family": FAMILY,
        "decision": row.get("dd_first_decision") or row.get("decision"),
        "strategy_cagr_pct": row.get("strategy_cagr_pct"),
        "spy_cagr_pct": row.get("spy_cagr_pct"),
        "excess_cagr_pct": row.get("excess_cagr_pct"),
        "strategy_max_drawdown_pct": row.get("strategy_max_drawdown_pct"),
        "spy_max_drawdown_pct": row.get("spy_max_drawdown_pct"),
        "parent_max_drawdown_pct": row.get("parent_max_drawdown_pct"),
        "drawdown_improvement_vs_parent_pct": row.get("drawdown_improvement_vs_parent_pct"),
        "calmar_ratio": row.get("calmar_ratio"),
        "parent_calmar_ratio": row.get("parent_calmar_ratio"),
        "years_beating_spy": row.get("years_beating_spy"),
        "years_losing_to_spy": row.get("years_losing_to_spy"),
        "trades": row.get("trades"),
        "value_delivered": row.get("value_delivered"),
        "lesson": lesson_from_row(row, axis),
        "failure_mode": failure_mode(row),
        "next_axis": next_axis_after(axis),
        "exhausted_axis": axis if should_cooldown_or_exhaust(row) == "exhausted" else "",
        "should_retry_axis": should_retry_axis(row),
        "should_cooldown_axis": should_cooldown_or_exhaust(row) == "cooldown",
        "trade_count_effect": trade_count_effect(row),
        "drawdown_effect": drawdown_effect(row),
        "cagr_effect": cagr_effect(row),
        "calmar_effect": calmar_effect(row),
        "spy_consistency_effect": spy_consistency_effect(row),
    }
    payload.setdefault("events", []).append(event)
    write_json(path, payload)


def update_axis_memory(axis_memory: dict[str, Any], axis: str, row: dict[str, Any], min_trades: int) -> None:
    state = axis_memory["axes"][axis]
    state["completed_runs"] = int(state.get("completed_runs", 0)) + int(bool(row.get("completed_run")))
    state["useful_candidates"] = int(state.get("useful_candidates", 0)) + int(useful_candidate(row, min_trades))
    state["rejected"] = int(state.get("rejected", 0)) + int((row.get("dd_first_decision") or row.get("decision")) == "rejected")
    if _as_int(row.get("trades")) == 0:
        state["zero_trade_runs"] = int(state.get("zero_trade_runs", 0)) + 1
    if _is_duplicate_or_noop(row):
        state["metric_no_effect_runs"] = int(state.get("metric_no_effect_runs", 0)) + 1
    if _as_float(row.get("drawdown_improvement_vs_parent_pct")) < -25:
        state["strong_worse_drawdown_runs"] = int(state.get("strong_worse_drawdown_runs", 0)) + 1
    _update_best_axis_run(state, row)
    state.setdefault("lessons", []).append(lesson_from_row(row, axis))
    mark_axis_status(axis_memory, axis)


def rebuild_axis_memory_from_rows(axis_memory: dict[str, Any], rows: list[dict[str, Any]], min_trades: int) -> None:
    for axis, data in axis_memory.get("axes", {}).items():
        preserved = {
            "attempts": data.get("attempts", 0),
            "failures": data.get("failures", []),
            "status": data.get("status", "active"),
            "lessons": data.get("lessons", []),
        }
        data.clear()
        data.update(
            {
                **preserved,
                "completed_runs": 0,
                "useful_candidates": 0,
                "rejected": 0,
                "zero_trade_runs": 0,
                "metric_no_effect_runs": 0,
                "strong_worse_drawdown_runs": 0,
                "best_run_id": None,
                "best_drawdown": None,
                "best_cagr": None,
                "best_calmar": None,
            }
        )
    for row in rows:
        axis = row.get("axis") or axis_from_strategy_id(str(row.get("strategy_id", "")))
        if axis not in axis_memory.get("axes", {}):
            continue
        data = axis_memory["axes"][axis]
        data["completed_runs"] = int(data.get("completed_runs", 0)) + int(row.get("completed_run", True))
        data["useful_candidates"] = int(data.get("useful_candidates", 0)) + int(useful_candidate(row, min_trades))
        data["rejected"] = int(data.get("rejected", 0)) + int((row.get("dd_first_decision") or row.get("decision")) == "rejected")
        data["zero_trade_runs"] = int(data.get("zero_trade_runs", 0)) + int(_as_int(row.get("trades")) == 0)
        data["metric_no_effect_runs"] = int(data.get("metric_no_effect_runs", 0)) + int(_is_duplicate_or_noop(row))
        data["strong_worse_drawdown_runs"] = int(data.get("strong_worse_drawdown_runs", 0)) + int(_as_float(row.get("drawdown_improvement_vs_parent_pct")) < -25)
        _update_best_axis_run(data, row)
    for axis in axis_memory.get("axes", {}):
        mark_axis_status(axis_memory, axis)


def mark_axis_status(axis_memory: dict[str, Any], axis: str) -> None:
    state = axis_memory["axes"][axis]
    if int(state.get("useful_candidates", 0)) > 0:
        state["status"] = "active"
    elif int(state.get("metric_no_effect_runs", 0)) >= 3:
        state["status"] = "cooldown"
    elif int(state.get("zero_trade_runs", 0)) >= 2:
        state["status"] = "cooldown"
    elif int(state.get("strong_worse_drawdown_runs", 0)) >= 3:
        state["status"] = "cooldown"
    elif int(state.get("attempts", 0)) >= len([s for s in _causal_specs(set()) if s["axis"] == axis]) and int(state.get("completed_runs", 0)) == 0:
        state["status"] = "exhausted"
    else:
        state.setdefault("status", "active")


def write_axis_summary(reports_dir: str, axis_memory: dict[str, Any]) -> None:
    import csv

    path = Path(reports_dir) / AXIS_SUMMARY_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = [
        "axis",
        "attempts",
        "completed_runs",
        "useful_candidates",
        "rejected",
        "zero_trade_runs",
        "metric_no_effect_runs",
        "best_run_id",
        "best_drawdown",
        "best_cagr",
        "best_calmar",
        "status",
        "next_action",
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns, delimiter=";")
        writer.writeheader()
        for axis in AXIS_PRIORITY:
            data = axis_memory["axes"].get(axis, {})
            row = {key: data.get(key, "") for key in columns}
            row["axis"] = axis
            row["next_action"] = _axis_next_action(data)
            writer.writerow({k: _csv_value(v) for k, v in row.items()})


def write_loop_summary(args: argparse.Namespace, rows: list[dict[str, Any]], state: dict[str, Any], axis_memory: dict[str, Any]) -> None:
    useful_rows = [r for r in rows if useful_candidate(r, args.min_trades)]
    best = best_dd_first_candidate(rows)
    lines = [
        "# DD_FIRST Long Loop Summary",
        "",
        f"- Status: {state.get('status')}",
        f"- Stop reason: {state.get('stop_reason')}",
        f"- Completed runs: {state.get('completed_real_runs', 0)}",
        f"- Useful candidates: {state.get('useful_candidates', len(useful_rows))}",
        f"- Total attempts: {state.get('total_attempts', 0)}",
        f"- Failed attempts: {state.get('failed_attempts', 0)}",
        f"- Repaired errors: {state.get('repaired_errors', 0)}",
        f"- Generated hypotheses: {len(set(state.get('generated_hypotheses', [])))}",
        f"- Current axis: {state.get('current_axis', '')}",
        f"- Exhausted axes: {', '.join(_axes_with_status(axis_memory, 'exhausted'))}",
        f"- Cooldown axes: {', '.join(_axes_with_status(axis_memory, 'cooldown'))}",
        f"- Best DD_FIRST candidate: {best.get('run_id', '') if best else ''}",
        f"- Last error: {state.get('last_error', '')}",
        f"- Last lesson: {last_lesson(args.state_dir)}",
        f"- Next action: {next_action(state, axis_memory)}",
        "",
        "| run_id | strategy_id | axis | CAGR | SPY CAGR | excess | max DD | parent DD | DD improvement | Calmar | years W/L | trades | decision | value_delivered |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|",
    ]
    for row in rows:
        axis = row.get("axis") or axis_from_strategy_id(str(row.get("strategy_id", "")))
        lines.append(
            f"| {row.get('run_id')} | {row.get('strategy_id')} | {axis} | {row.get('strategy_cagr_pct')} | "
            f"{row.get('spy_cagr_pct')} | {row.get('excess_cagr_pct')} | {row.get('strategy_max_drawdown_pct')} | "
            f"{row.get('parent_max_drawdown_pct')} | {row.get('drawdown_improvement_vs_parent_pct')} | "
            f"{row.get('calmar_ratio')} | {row.get('years_beating_spy')}/{row.get('years_losing_to_spy')} | "
            f"{row.get('trades')} | {row.get('dd_first_decision') or row.get('decision')} | {row.get('value_delivered')} |"
        )
    path = Path(args.reports_dir) / "dd_first_loop_summary.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def save_all_state(args: argparse.Namespace, state: dict[str, Any], axis_memory: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    state["rejected_hypotheses"] = sorted(
        {
            str(row.get("strategy_id"))
            for row in rows
            if (row.get("dd_first_decision") or row.get("decision")) == "rejected" and row.get("strategy_id")
        }
    )
    save_loop_state(args.state_dir, state)
    save_axis_memory(args.state_dir, axis_memory)
    write_axis_summary(args.reports_dir, axis_memory)
    write_dd_first_summary(Path(args.reports_dir) / "dd_first_summary.csv", rows)
    write_loop_summary(args, rows, state, axis_memory)


def stop_reason(args: argparse.Namespace, state: dict[str, Any], axis_memory: dict[str, Any], start: float) -> str:
    requested = requested_strategy_ids(args)
    if requested and requested.issubset(set(_attempted_strategy_ids(args.runs_dir))):
        return "requested_strategy_ids_completed"
    if not requested and int(state.get("useful_candidates", 0)) >= args.target_useful_candidates:
        return "target_useful_candidates_reached"
    if not requested and int(state.get("completed_real_runs", 0)) >= args.max_completed_runs:
        return "max_completed_runs_reached"
    if int(state.get("total_attempts", 0)) >= args.max_total_attempts:
        return "max_total_attempts_reached"
    if (time.monotonic() - start) / 3600 >= args.max_wall_clock_hours:
        return "max_wall_clock_hours_reached"
    if all(axis_memory["axes"][axis].get("status") in {"cooldown", "exhausted"} for axis in AXIS_PRIORITY):
        return "all_axes_exhausted_or_cooldown"
    return ""


def _attempted_strategy_ids(runs_dir: str) -> list[str]:
    ids: list[str] = []
    for run_dir in Path(runs_dir).glob("DD_FIRST_*"):
        manifest = run_dir / "run_manifest.json"
        if manifest.exists():
            try:
                ids.append(str(read_json(manifest).get("strategy_id") or ""))
            except Exception:
                pass
    return ids


def _existing_config_hashes(registry_path: str) -> set[str]:
    hashes = set()
    for row in read_json(registry_path).get("strategies", []):
        path = Path(str(row.get("config_path", "")))
        if not path.exists():
            continue
        try:
            hashes.add(stable_json_hash(_strategy_payload(read_json(path))))
        except Exception:
            continue
    return hashes


def _strategy_payload(cfg: dict[str, Any]) -> dict[str, Any]:
    keys = ["ranking", "entry_rule", "exit_rule", "market_filter", "risk_filters", "risk_management", "costs"]
    return {key: cfg.get(key) for key in keys if key in cfg}


def _parameter_patch(config_path: str) -> dict[str, Any]:
    return _parameter_patch_from_config(read_json(config_path))


def _parameter_patch_from_config(cfg: dict[str, Any]) -> dict[str, Any]:
    return {key: cfg.get(key) for key in ["ranking", "entry_rule", "exit_rule", "market_filter", "risk_filters", "risk_management"] if key in cfg}


def axis_from_config(config_path: str) -> str:
    try:
        cfg = read_json(config_path)
        return str(cfg.get("generation_axis") or cfg.get("dominant_dimension") or axis_from_strategy_id(str(cfg.get("strategy_id", ""))))
    except Exception:
        return ""


def axis_from_strategy_id(strategy_id: str) -> str:
    text = strategy_id.lower()
    for axis in AXIS_PRIORITY:
        tokens = axis.split("_")
        if all(token in text for token in tokens[:2]):
            return axis
    if "exposure" in text:
        return "exposure_reduction_partial"
    if "soft_spy" in text or "regime" in text:
        return "soft_spy_regime"
    if "lowvol" in text or "low_vol" in text:
        return "low_vol_momentum_soft_penalty"
    if "extension" in text:
        return "anti_extension_soft_filter"
    if "proxy" in text or "drawdown" in text:
        return "drawdown_proxy_filter"
    if "trail" in text or "topn" in text:
        return "trailing_and_exit_refinement"
    return ""


def _first_existing(columns: set[str], candidates: list[str]) -> str | None:
    for candidate in candidates:
        if candidate in columns:
            return candidate
    return None


def _update_best_axis_run(axis_state: dict[str, Any], row: dict[str, Any]) -> None:
    dd = _as_float(row.get("strategy_max_drawdown_pct"))
    calmar = _as_float(row.get("calmar_ratio"))
    cagr = _as_float(row.get("strategy_cagr_pct"))
    current_best = axis_state.get("best_drawdown")
    if current_best is None or abs(dd) < abs(_as_float(current_best)):
        axis_state["best_run_id"] = row.get("run_id")
        axis_state["best_drawdown"] = dd
        axis_state["best_cagr"] = cagr
        axis_state["best_calmar"] = calmar


def lesson_from_row(row: dict[str, Any], axis: str) -> str:
    if _as_int(row.get("trades")) == 0:
        return f"{axis}: overstrict_filter_zero_trades; no sirve porque mata la muestra."
    if _as_float(row.get("drawdown_improvement_vs_parent_pct")) < 0:
        return f"{axis}: not_dd_first; mejora retorno o cambia señal pero empeora drawdown."
    if useful_candidate(row):
        return f"{axis}: useful DD_FIRST candidate; follow-up monotónico permitido."
    return f"{axis}: completed learning; {row.get('dd_first_rejection_reason') or row.get('rejection_reason') or 'rejected'}"


def failure_mode(row: dict[str, Any]) -> str:
    reasons = str(row.get("dd_first_rejection_reason") or row.get("rejection_reason") or "").lower()
    if _as_int(row.get("trades")) == 0:
        return "overstrict_filter_zero_trades"
    if "metric_no_effect" in reasons:
        return "metric_no_effect"
    if "duplicate_artifact" in reasons:
        return "duplicate_artifact"
    if _as_float(row.get("drawdown_improvement_vs_parent_pct")) < 0:
        return "worse_drawdown_than_parent"
    return "accepted_or_informative"


def should_retry_axis(row: dict[str, Any]) -> bool:
    improvement = _as_float(row.get("drawdown_improvement_vs_parent_pct"))
    excess = _as_float(row.get("excess_cagr_pct"))
    return improvement > 0 and excess < 0 and _as_int(row.get("trades")) > 0


def should_cooldown_or_exhaust(row: dict[str, Any]) -> str:
    if _as_int(row.get("trades")) == 0:
        return "cooldown"
    if _is_duplicate_or_noop(row):
        return "cooldown"
    return ""


def trade_count_effect(row: dict[str, Any]) -> str:
    trades = _as_int(row.get("trades"))
    if trades == 0:
        return "killed_sample"
    if trades < 50:
        return "insufficient_sample"
    return "sample_preserved"


def drawdown_effect(row: dict[str, Any]) -> str:
    improvement = _as_float(row.get("drawdown_improvement_vs_parent_pct"))
    if improvement >= 10:
        return "material_improvement"
    if improvement > 0:
        return "small_improvement"
    return "worse_or_no_improvement"


def cagr_effect(row: dict[str, Any]) -> str:
    excess = _as_float(row.get("excess_cagr_pct"))
    return "positive_excess" if excess >= 0 else "negative_excess"


def calmar_effect(row: dict[str, Any]) -> str:
    return "improved" if _as_float(row.get("calmar_ratio")) > _as_float(row.get("parent_calmar_ratio")) else "not_improved"


def spy_consistency_effect(row: dict[str, Any]) -> str:
    return "years_ok" if _as_int(row.get("years_beating_spy")) >= _as_int(row.get("years_losing_to_spy")) else "years_weak"


def next_axis_after(axis: str) -> str:
    try:
        return AXIS_PRIORITY[AXIS_PRIORITY.index(axis) + 1]
    except (ValueError, IndexError):
        return ""


def best_dd_first_candidate(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not rows:
        return None
    tradable = [r for r in rows if _as_int(r.get("trades")) > 0 and _as_float(r.get("drawdown_improvement_vs_parent_pct")) >= 0]
    if not tradable:
        tradable = [r for r in rows if _as_int(r.get("trades")) > 0]
    if not tradable:
        return None
    return sorted(tradable, key=lambda r: (_as_float(r.get("drawdown_improvement_vs_parent_pct")), _as_float(r.get("calmar_ratio"))), reverse=True)[0]


def _axis_next_action(data: dict[str, Any]) -> str:
    if data.get("status") == "cooldown":
        return "skip_until_new_evidence"
    if data.get("status") == "exhausted":
        return "do_not_retry_without_new_columns_or_engine_support"
    if int(data.get("useful_candidates", 0)) > 0:
        return "refine_monotonically"
    return "try_next_causal_variant"


def _axes_with_status(axis_memory: dict[str, Any], status: str) -> list[str]:
    return [axis for axis, data in axis_memory.get("axes", {}).items() if data.get("status") == status]


def last_lesson(state_dir: str) -> str:
    path = Path(state_dir) / LEARNING_FILE
    if not path.exists():
        return ""
    events = read_json(path).get("events", [])
    return str(events[-1].get("lesson", "")) if events else ""


def next_action(state: dict[str, Any], axis_memory: dict[str, Any]) -> str:
    for axis in AXIS_PRIORITY:
        if axis_memory["axes"][axis].get("status") == "active":
            return f"continue_axis:{axis}"
    return state.get("stop_reason") or "review_results"


def _read_state_snapshot(state_dir: str) -> dict[str, str]:
    snapshot = {}
    for name in ("current_parent.json", "current_baseline.json"):
        path = Path(state_dir) / name
        snapshot[name] = path.read_text(encoding="utf-8-sig") if path.exists() else ""
    return snapshot


def _assert_parent_baseline_unchanged(state_dir: str, snapshot: dict[str, str]) -> None:
    current = _read_state_snapshot(state_dir)
    if current != snapshot:
        raise RuntimeError("Parent/baseline lock compromised; DD_FIRST long loop stopped.")


def _csv_value(value: Any) -> Any:
    if isinstance(value, float):
        return str(round(value, 6)).replace(".", ",")
    return value


def _as_float(value: Any) -> float:
    if value is None or value == "":
        return 0.0
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return 0.0


def _as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _date_span_days(start: Any, end: Any) -> int:
    try:
        start_dt = datetime.fromisoformat(str(start).replace("Z", "+00:00"))
        end_dt = datetime.fromisoformat(str(end).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return 0
    return max((end_dt - start_dt).days, 0)


if __name__ == "__main__":
    raise SystemExit(main())
