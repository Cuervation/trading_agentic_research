"""Controlled autonomous DD_FIRST mini-loop.

The loop is intentionally conservative: it runs real backtests, audits them with
DD_FIRST rules, writes DD_FIRST learning/report artifacts, and never moves parent
or baseline state.
"""

from __future__ import annotations

import argparse
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

from backtester.dd_first import DD_REQUIRED_RUN_FILES, row_from_audit_or_run, write_dd_first_summary

INITIAL_IDS = [
    "HYP_DD_FIRST_AUTO002_SPY_REGIME_EXPOSURE_V1",
    "HYP_DD_FIRST_AUTO002_QUALITY_LOWVOL_RANK_V1",
    "HYP_DD_FIRST_AUTO002_TRAILING_18_TOPN_9_V1",
]
FAMILY = "dd_first_drawdown_control"
DEFAULT_PARENT_CONFIG = "configs/generated/HYP_AUTO_TIME_SERIES_MOMENTUM_SEED.json"
AXES = [
    "spy_regime_strict",
    "exposure_reduction",
    "quality_momentum",
    "low_volatility_momentum",
    "downside_risk_filter",
    "breadth_regime_proxy",
    "trailing_stop",
    "top_n_concentration",
    "exit_rank_threshold",
    "anti_extension_filter",
]


def read_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write_json(path: str | Path, payload: dict[str, Any]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    p = Path(path)
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8-sig").splitlines() if line.strip()]


def write_jsonl(path: str | Path, rows: list[dict[str, Any]]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a controlled DD_FIRST autofix loop until N real completed runs.")
    parser.add_argument("--target-completed-runs", type=int, default=3)
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
    parser.add_argument("--max-attempts", type=int, default=15)
    parser.add_argument("--max-generated-hypotheses", type=int, default=10)
    parser.add_argument("--max-repair-cycles", type=int, default=5)
    parser.add_argument("--min-trades", type=int, default=50)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    state = _load_loop_state(args.state_dir)
    state.update({"status": "running", "stop_reason": "", "last_error": "", "current_cycle": int(state.get("current_cycle", 0))})
    _save_loop_state(args.state_dir, state)

    try:
        weekly_file, daily_folder, parent_run_id = _preflight(args)
        weekly_columns = _csv_columns(weekly_file)
        ensured = ensure_initial_hypotheses(
            parent_config_path=args.parent_strategy_config,
            registry_path=args.strategy_registry,
            hypothesis_bank_path=args.hypothesis_bank,
            weekly_columns=weekly_columns,
        )
        state["generated_hypotheses"] = sorted(set(state.get("generated_hypotheses", []) + ensured))
        _save_loop_state(args.state_dir, state)
    except Exception as exc:
        state.update({"status": "failed", "stop_reason": "preflight_failed", "last_error": str(exc)})
        _save_loop_state(args.state_dir, state)
        _write_loop_summary(args, [], state)
        print(f"DD_FIRST preflight failed: {exc}")
        return 2

    completed_rows: list[dict[str, Any]] = []
    attempted: set[str] = set()
    total_attempts = 0
    repair_counts: dict[str, int] = {}

    while len(completed_rows) < args.target_completed_runs:
        state["current_cycle"] = int(state.get("current_cycle", 0)) + 1
        if total_attempts >= args.max_attempts:
            state["stop_reason"] = "total_attempts_exceeded"
            break
        if len(state.get("generated_hypotheses", [])) > args.max_generated_hypotheses:
            state["stop_reason"] = "generated_hypotheses_exceeded"
            break

        candidates = _candidate_strategy_ids(args.strategy_registry)
        strategy_id = next((sid for sid in candidates if sid not in attempted), None)
        if strategy_id is None:
            strategy_id = generate_next_hypothesis(
                parent_config_path=args.parent_strategy_config,
                registry_path=args.strategy_registry,
                hypothesis_bank_path=args.hypothesis_bank,
                weekly_columns=weekly_columns,
                used_ids=set(candidates),
                exhausted_axes=set(_exhausted_axes(args.state_dir)),
            )
            if not strategy_id:
                state["stop_reason"] = "all_dd_first_axes_exhausted"
                break
            state.setdefault("generated_hypotheses", []).append(strategy_id)
            candidates.append(strategy_id)

        attempted.add(strategy_id)
        total_attempts += 1
        state["failed_attempts"] = int(state.get("failed_attempts", 0))
        _save_loop_state(args.state_dir, state)

        config_path = _config_path_for(args.strategy_registry, strategy_id)
        run_id = _next_run_id(args.runs_dir, strategy_id, total_attempts)
        print(f"DD_FIRST attempt {total_attempts}: {strategy_id} -> {run_id}")

        result = run_one_candidate(
            run_id=run_id,
            strategy_id=strategy_id,
            config_path=config_path,
            weekly_file=weekly_file,
            daily_folder=daily_folder,
            parent_run_id=parent_run_id,
            args=args,
        )
        state["last_run_id"] = run_id

        if not result["ok"]:
            state["failed_attempts"] = int(state.get("failed_attempts", 0)) + 1
            state["last_error"] = result["error"]
            classification = classify_error(result["error"])
            repaired = attempt_repair(classification, config_path, weekly_columns)
            if repaired:
                state["repaired_errors"] = int(state.get("repaired_errors", 0)) + 1
                repair_counts[classification] = repair_counts.get(classification, 0) + 1
                if repair_counts[classification] > args.max_repair_cycles:
                    state["stop_reason"] = "repair_cycles_exceeded"
                    break
                attempted.discard(strategy_id)
            elif classification == "data_error":
                state["stop_reason"] = "no_valid_data"
                break
            else:
                state["stop_reason"] = "unrepairable_error"
                break
            _save_loop_state(args.state_dir, state)
            continue

        row = result["row"]
        useful_real_run = is_real_completed_run(Path(args.runs_dir) / run_id) and not _is_duplicate_or_noop(row)
        learning_event = update_learning_memory(args.state_dir, row, useful_real_run)
        if row.get("dd_first_decision") == "rejected":
            state.setdefault("rejected_hypotheses", []).append(strategy_id)
            if learning_event.get("exhausted_axis"):
                state.setdefault("exhausted_axes", []).append(learning_event["exhausted_axis"])
        if not useful_real_run:
            state["rejected_hypotheses"] = sorted(set(state.get("rejected_hypotheses", [])))
            state["exhausted_axes"] = sorted(set(state.get("exhausted_axes", [])))
        else:
            completed_rows.append(row)
            state["completed_real_runs"] = len(completed_rows)

        _save_loop_state(args.state_dir, state)
        _rewrite_reports(args, completed_rows)
        _write_loop_summary(args, completed_rows, state)

    if len(completed_rows) >= args.target_completed_runs:
        state["status"] = "completed"
        state["stop_reason"] = "target_completed_runs_reached"
    else:
        state["status"] = "stopped"
        state.setdefault("stop_reason", "stopped_before_target")
    state["completed_real_runs"] = len(completed_rows)
    _save_loop_state(args.state_dir, state)
    _rewrite_reports(args, completed_rows)
    _write_loop_summary(args, completed_rows, state)
    print(f"DD_FIRST loop {state['status']}: completed_real_runs={len(completed_rows)} stop_reason={state.get('stop_reason')}")
    return 0 if len(completed_rows) >= args.target_completed_runs else 2


def _preflight(args: argparse.Namespace) -> tuple[str, str, str]:
    weekly = Path(args.weekly_file) if args.weekly_file else detect_weekly_file(Path("data"))
    daily = Path(args.daily_folder) if args.daily_folder else detect_daily_folder(Path("data"))
    expected = "data/*weekly*master*.csv and data/ with daily master CSVs"
    if weekly is None or not weekly.exists():
        raise FileNotFoundError(f"Weekly feature store not found. Expected: {expected}")
    if daily is None or not daily.exists():
        raise FileNotFoundError(f"Daily feature store folder not found. Expected: {expected}")
    parent_config = Path(args.parent_strategy_config)
    if not parent_config.exists():
        raise FileNotFoundError(f"Parent config not found: {parent_config}")
    current_parent_path = Path(args.state_dir) / "current_parent.json"
    if not current_parent_path.exists():
        raise FileNotFoundError(f"Missing parent state: {current_parent_path}")
    current_parent = read_json(current_parent_path)
    if not (current_parent.get("parent_promotion_blocked") is True or current_parent.get("parent_updates_require_manual_approval") is True):
        raise RuntimeError("Parent lock is not active; DD_FIRST loop refuses to run.")
    parent_run_id = args.parent_run_id or str(current_parent.get("current_parent_run_id") or "")
    if not parent_run_id or not (Path(args.runs_dir) / parent_run_id).exists():
        raise FileNotFoundError(f"Parent run not found under {args.runs_dir}: {parent_run_id}")
    return str(weekly), str(daily), parent_run_id


def detect_weekly_file(data_dir: Path) -> Path | None:
    if not data_dir.exists():
        return None
    matches = [p for p in data_dir.glob("*.csv") if all(token in p.name.lower() for token in ("weekly", "master"))]
    if not matches:
        matches = [p for p in data_dir.glob("*.csv") if any(token in p.name.lower() for token in ("weekly", "signal", "features"))]
    return sorted(matches, key=lambda p: p.stat().st_size, reverse=True)[0] if matches else None


def detect_daily_folder(data_dir: Path) -> Path | None:
    if not data_dir.exists():
        return None
    if any("daily" in p.name.lower() and p.suffix.lower() == ".csv" for p in data_dir.iterdir()):
        return data_dir
    daily_dirs = [p for p in data_dir.iterdir() if p.is_dir() and "daily" in p.name.lower()]
    return daily_dirs[0] if daily_dirs else None


def _csv_columns(path: str | Path) -> set[str]:
    return set(pd.read_csv(path, nrows=0).columns)


def ensure_initial_hypotheses(parent_config_path: str, registry_path: str, hypothesis_bank_path: str, weekly_columns: set[str]) -> list[str]:
    parent = read_json(parent_config_path)
    specs = [
        _initial_spy_regime(parent),
        _initial_quality_lowvol(parent, weekly_columns),
        _initial_trailing(parent),
    ]
    for cfg in specs:
        _write_strategy_and_hypothesis(cfg, registry_path, hypothesis_bank_path, "DD_FIRST_SERIES initial candidate.")
    return [cfg["strategy_id"] for cfg in specs]


def _initial_spy_regime(parent: dict[str, Any]) -> dict[str, Any]:
    cfg = deepcopy(parent)
    cfg.update(_base_dd_meta("HYP_DD_FIRST_AUTO002_SPY_REGIME_EXPOSURE_V1", parent, "SPY regime strict filter to reduce weak-regime drawdown.", "spy_regime_strict"))
    cfg["market_filter"] = {**cfg.get("market_filter", {}), "require_positive_trend": True, "fallback_allow_if_missing_spy_metric": False, "condition_any": [{"field": "spy_close_vs_sma50_pct", "operator": ">", "value": 0, "enabled_if_field_exists": True}]}
    cfg["changed_parameters"] = ["market_filter.require_positive_trend", "market_filter.fallback_allow_if_missing_spy_metric", "market_filter.condition_any"]
    return cfg


def _initial_quality_lowvol(parent: dict[str, Any], weekly_columns: set[str]) -> dict[str, Any]:
    cfg = deepcopy(parent)
    ranking = _first_existing(weekly_columns, ["channel_r2", "close_sma_50_slope_5d_pct", "close_vs_sma52w_pct", "ret_52w_pct"])
    cfg.update(_base_dd_meta("HYP_DD_FIRST_AUTO002_QUALITY_LOWVOL_RANK_V1", parent, "Quality/low-risk ranking to keep momentum but reduce fragile winners.", "quality_momentum"))
    cfg["ranking"] = {"field": ranking, "order": "desc"}
    cfg["entry_rule"] = {**cfg.get("entry_rule", {}), "by": ranking}
    required = [x for x in ["ret_52w_pct", "close", ranking] if x in weekly_columns]
    cfg["risk_filters"] = {"require_non_null_fields": required, "conditions": [{"field": "channel_r2", "operator": ">=", "value": 0.35, "enabled_if_field_exists": True}, {"field": "daily_range_pct", "operator": "<=", "value": 3.5, "enabled_if_field_exists": True}]}
    cfg["changed_parameters"] = ["ranking.field", "entry_rule.by", "risk_filters.require_non_null_fields", "risk_filters.conditions"]
    return cfg


def _initial_trailing(parent: dict[str, Any]) -> dict[str, Any]:
    cfg = deepcopy(parent)
    cfg.update(_base_dd_meta("HYP_DD_FIRST_AUTO002_TRAILING_18_TOPN_9_V1", parent, "Broader basket plus 18% trailing stop to reduce drawdown without changing ranking.", "trailing_stop"))
    cfg["entry_rule"] = {**cfg.get("entry_rule", {}), "top_n": 9}
    cfg["risk_management"] = {**cfg.get("risk_management", {}), "trailing_stop_pct": 18}
    cfg["changed_parameters"] = ["entry_rule.top_n", "risk_management.trailing_stop_pct"]
    return cfg


def _base_dd_meta(strategy_id: str, parent: dict[str, Any], claim: str, axis: str) -> dict[str, Any]:
    return {
        "strategy_id": strategy_id,
        "hypothesis_id": strategy_id,
        "strategy_family": FAMILY,
        "parent_strategy_id": parent.get("strategy_id"),
        "bibliography_basis": [{"source_id": "SRC_TIME_SERIES_MOMENTUM_SEED"}],
        "empirical_basis": [{"run_id": "AUTO_002", "reason": "Locked parent for DD_FIRST_SERIES controlled loop."}],
        "claim": claim,
        "dominant_dimension": axis,
        "evaluation_mode": "dd_first",
        "expected_effect": "Reduce max drawdown first while preserving positive excess CAGR vs SPY and enough trades.",
        "falsification_rule": "Reject if drawdown fails to improve materially, Calmar worsens for promotion, SPY edge disappears, trades become insufficient, or artifacts duplicate parent.",
        "dd_first_objective": {"priority_order": ["minimize_max_drawdown", "improve_calmar", "keep_positive_excess_cagr", "beat_spy_year_month", "keep_sufficient_trades"]},
    }


def _write_strategy_and_hypothesis(cfg: dict[str, Any], registry_path: str, hypothesis_bank_path: str, notes: str) -> None:
    strategy_id = cfg["strategy_id"]
    config_path = Path("configs/generated") / f"{strategy_id}.json"
    write_json(config_path, cfg)
    registry = read_json(registry_path)
    rows = [r for r in registry.get("strategies", []) if r.get("strategy_id") != strategy_id]
    rows.append({"strategy_id": strategy_id, "strategy_family": FAMILY, "status": "candidate", "benchmark_ticker": "SPY", "config_path": config_path.as_posix(), "signal_frequency": "weekly", "execution_frequency": "daily", "rebalance_frequency": "monthly", "parent_strategy_id": cfg.get("parent_strategy_id"), "evaluation_mode": "dd_first", "notes": notes})
    registry["strategies"] = rows
    write_json(registry_path, registry)
    bank_rows = [r for r in read_jsonl(hypothesis_bank_path) if r.get("hypothesis_id") != strategy_id]
    bank_rows.append({"hypothesis_id": strategy_id, "family": FAMILY, "status": "candidate", "required_spy_comparison": "monthly_and_yearly", "evaluation_mode": "dd_first", "parent_strategy_id": cfg.get("parent_strategy_id"), "bibliography_basis": cfg.get("bibliography_basis", []), "empirical_basis": cfg.get("empirical_basis", []), "claim": cfg.get("claim"), "dominant_dimension": cfg.get("dominant_dimension"), "expected_effect": cfg.get("expected_effect"), "falsification_rule": cfg.get("falsification_rule"), "changed_parameters": cfg.get("changed_parameters", []), "strategy_overrides": cfg})
    write_jsonl(hypothesis_bank_path, bank_rows)


def _candidate_strategy_ids(registry_path: str) -> list[str]:
    registry = read_json(registry_path)
    return [str(r["strategy_id"]) for r in registry.get("strategies", []) if r.get("strategy_family") == FAMILY and r.get("status") == "candidate"]


def _config_path_for(registry_path: str, strategy_id: str) -> str:
    for row in read_json(registry_path).get("strategies", []):
        if row.get("strategy_id") == strategy_id:
            return str(row["config_path"])
    raise KeyError(f"Strategy not found in registry: {strategy_id}")


def _next_run_id(runs_dir: str, strategy_id: str, attempt: int) -> str:
    stem = f"DD_FIRST_{attempt:02d}_{strategy_id}"
    stem = stem[:120]
    candidate = stem
    i = 1
    while (Path(runs_dir) / candidate).exists():
        i += 1
        candidate = f"{stem}_{i}"
    return candidate


def run_one_candidate(*, run_id: str, strategy_id: str, config_path: str, weekly_file: str, daily_folder: str, parent_run_id: str, args: argparse.Namespace) -> dict[str, Any]:
    commands = [
        [sys.executable, "scripts/run_backtest.py", "--weekly-file", weekly_file, "--daily-folder", daily_folder, "--strategy-config", config_path, "--project-config", args.project_config, "--run-id", run_id, "--runs-dir", args.runs_dir, "--parent-run-id", parent_run_id, "--parent-strategy-config", args.parent_strategy_config],
        [sys.executable, "scripts/evaluate_candidate.py", "--run-id", run_id, "--runs-dir", args.runs_dir, "--reports-dir", args.reports_dir, "--evaluation-mode", "dd_first", "--hypothesis-id", strategy_id, "--family", FAMILY, "--state-dir", args.state_dir, "--parent-run-id", parent_run_id, "--min-trades", str(args.min_trades)],
        [sys.executable, "scripts/summarize_runs.py", "--runs-dir", args.runs_dir, "--output", str(Path(args.reports_dir) / "runs_summary.csv")],
        [sys.executable, "scripts/summarize_dd_first.py", "--runs-dir", args.runs_dir, "--output", str(Path(args.reports_dir) / "dd_first_summary.csv"), "--min-trades", str(args.min_trades)],
    ]
    timeout_minutes = float(getattr(args, "per_run_timeout_minutes", 0) or 0)
    timeout_seconds = timeout_minutes * 60 if timeout_minutes > 0 else None
    for command in commands:
        try:
            result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False, timeout=timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            return {
                "ok": False,
                "error": f"command_timeout_after_{timeout_minutes:g}_minutes: {' '.join(command)}\n{exc.stderr or exc.stdout or ''}".strip(),
                "command": command,
            }
        if result.returncode != 0:
            return {"ok": False, "error": (result.stderr or result.stdout or "").strip(), "command": command}
    run_dir = Path(args.runs_dir) / run_id
    try:
        row = row_from_audit_or_run(run_dir, parent_run_dir=Path(args.runs_dir) / parent_run_id, min_trades=args.min_trades)
    except Exception as exc:
        return {"ok": False, "error": str(exc), "command": commands[-1]}
    return {"ok": True, "row": row}


def is_real_completed_run(run_dir: Path) -> bool:
    return run_dir.exists() and all((run_dir / name).exists() for name in [*DD_REQUIRED_RUN_FILES, "audit.json", "summary.md"])


def _is_duplicate_or_noop(row: dict[str, Any]) -> bool:
    text = str(row.get("dd_first_rejection_reason") or row.get("rejection_reason") or "")
    return "duplicate_artifact" in text or "metric_no_effect" in text


def classify_error(error: str) -> str:
    lower = error.lower()
    if "weekly_df must contain ranking column" in lower or "ranking column" in lower or "risk filter field missing" in lower:
        return "missing_field"
    if "json" in lower or "hypothesis" in lower or "changed_parameters" in lower or "basis" in lower:
        return "config_error"
    if "filenotfound" in lower or "missing required columns" in lower or "spy" in lower:
        return "data_error"
    if "traceback" in lower or "importerror" in lower or "typeerror" in lower:
        return "code_error"
    return "unknown_error"


def attempt_repair(classification: str, config_path: str, weekly_columns: set[str]) -> bool:
    if classification not in {"missing_field", "config_error"}:
        return False
    path = Path(config_path)
    cfg = read_json(path)
    ranking = cfg.get("ranking", {}).get("field")
    changed = False
    if ranking not in weekly_columns:
        fallback = _first_existing(weekly_columns, ["channel_r2", "close_sma_50_slope_5d_pct", "close_vs_sma52w_pct", "ret_52w_pct"])
        cfg.setdefault("ranking", {})["field"] = fallback
        cfg.setdefault("entry_rule", {})["by"] = fallback
        changed = True
    filters = cfg.get("risk_filters", {}) or {}
    conditions = []
    for cond in filters.get("conditions", []) or []:
        if cond.get("field") not in weekly_columns:
            cond["enabled_if_field_exists"] = True
        conditions.append(cond)
    if conditions != filters.get("conditions", []):
        filters["conditions"] = conditions
        cfg["risk_filters"] = filters
        changed = True
    if changed:
        write_json(path, cfg)
    return changed


def generate_next_hypothesis(parent_config_path: str, registry_path: str, hypothesis_bank_path: str, weekly_columns: set[str], used_ids: set[str], exhausted_axes: set[str]) -> str | None:
    parent = read_json(parent_config_path)
    for axis in AXES:
        if axis in exhausted_axes:
            continue
        sid = f"HYP_DD_FIRST_AUTO002_{axis.upper()}_V1"
        if sid in used_ids:
            continue
        cfg = _generated_for_axis(parent, weekly_columns, sid, axis)
        if cfg is None:
            continue
        _write_strategy_and_hypothesis(cfg, registry_path, hypothesis_bank_path, f"DD_FIRST generated candidate axis={axis}.")
        return sid
    return None


def _generated_for_axis(parent: dict[str, Any], weekly_columns: set[str], sid: str, axis: str) -> dict[str, Any] | None:
    cfg = deepcopy(parent)
    cfg.update(_base_dd_meta(sid, parent, f"DD_FIRST causal axis: {axis}.", axis))
    if axis == "exposure_reduction":
        cfg["risk_management"] = {**cfg.get("risk_management", {}), "max_gross_exposure_pct": 75}
        cfg["changed_parameters"] = ["risk_management.max_gross_exposure_pct"]
    elif axis == "low_volatility_momentum":
        field = _first_existing(weekly_columns, ["realized_vol_13w_pct", "volatility_12w_pct", "atr_14_pct", "ret_52w_pct"])
        cfg["ranking"] = {"field": field, "order": "asc"}
        cfg["entry_rule"] = {**cfg.get("entry_rule", {}), "by": field}
        cfg["changed_parameters"] = ["ranking.field", "ranking.order", "entry_rule.by"]
    elif axis == "downside_risk_filter":
        field = _first_existing(weekly_columns, ["max_drawdown_26w_pct", "drawdown_13w_pct", "ret_52w_pct"])
        cfg["risk_filters"] = {**cfg.get("risk_filters", {}), "conditions": [{"field": field, "operator": ">", "value": -25, "enabled_if_field_exists": True}]}
        cfg["changed_parameters"] = ["risk_filters.conditions.downside_risk"]
    elif axis == "top_n_concentration":
        cfg["entry_rule"] = {**cfg.get("entry_rule", {}), "top_n": 10}
        cfg["changed_parameters"] = ["entry_rule.top_n"]
    elif axis == "exit_rank_threshold":
        cfg["exit_rule"] = {**cfg.get("exit_rule", {}), "rank_threshold": 16}
        cfg["changed_parameters"] = ["exit_rule.rank_threshold"]
    elif axis == "anti_extension_filter":
        field = _first_existing(weekly_columns, ["close_vs_sma52w_pct", "ret_52w_pct"])
        cfg["risk_filters"] = {**cfg.get("risk_filters", {}), "conditions": [{"field": field, "operator": "<=", "value": 80, "enabled_if_field_exists": True}]}
        cfg["changed_parameters"] = ["risk_filters.conditions.anti_extension"]
    else:
        continue_cfg = {"spy_regime_strict", "quality_momentum", "breadth_regime_proxy", "trailing_stop"}
        if axis in continue_cfg:
            cfg = None
    return cfg


def _first_existing(columns: set[str], candidates: list[str]) -> str:
    for candidate in candidates:
        if candidate in columns:
            return candidate
    return candidates[-1]


def update_learning_memory(state_dir: str, row: dict[str, Any], useful_real_run: bool) -> dict[str, Any]:
    path = Path(state_dir) / "dd_first_learning_memory.json"
    payload = read_json(path) if path.exists() else {"events": []}
    decision = str(row.get("dd_first_decision") or row.get("decision") or "")
    rejected = decision == "rejected"
    lesson = _lesson_from_row(row, useful_real_run)
    event = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "run_id": row.get("run_id"),
        "strategy_id": row.get("strategy_id"),
        "hypothesis_id": row.get("hypothesis_id"),
        "family": FAMILY,
        "decision": decision,
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
        "lesson": lesson,
        "exhausted_axis": _axis_from_strategy(str(row.get("strategy_id"))) if rejected else "",
        "next_recommended_axis": row.get("next_action") or "try_more_defensive_axis",
    }
    payload.setdefault("events", []).append(event)
    write_json(path, payload)
    return event


def _lesson_from_row(row: dict[str, Any], useful_real_run: bool) -> str:
    if not useful_real_run:
        return "Run completed but did not count because it was duplicate/no-effect or missing required artifacts."
    if row.get("dd_first_decision") == "rejected":
        return f"Rejected by DD_FIRST: {row.get('dd_first_rejection_reason') or row.get('rejection_reason')}"
    return "DD_FIRST candidate delivered usable drawdown-adjusted evidence."


def _axis_from_strategy(strategy_id: str) -> str:
    text = strategy_id.lower()
    for axis in AXES:
        if axis.replace("_", "") in text.replace("_", ""):
            return axis
    if "quality" in text:
        return "quality_momentum"
    if "trail" in text:
        return "trailing_stop"
    if "regime" in text:
        return "spy_regime_strict"
    return ""


def _exhausted_axes(state_dir: str) -> list[str]:
    path = Path(state_dir) / "dd_first_learning_memory.json"
    if not path.exists():
        return []
    payload = read_json(path)
    return [str(e.get("exhausted_axis")) for e in payload.get("events", []) if e.get("exhausted_axis")]


def _load_loop_state(state_dir: str) -> dict[str, Any]:
    path = Path(state_dir) / "dd_first_loop_state.json"
    if path.exists():
        return read_json(path)
    return {"status": "initialized", "completed_real_runs": 0, "failed_attempts": 0, "repaired_errors": 0, "generated_hypotheses": [], "rejected_hypotheses": [], "current_cycle": 0, "stop_reason": "", "last_run_id": "", "last_error": ""}


def _save_loop_state(state_dir: str, state: dict[str, Any]) -> None:
    state["last_updated_at"] = datetime.now(timezone.utc).isoformat()
    for key in ("generated_hypotheses", "rejected_hypotheses", "exhausted_axes"):
        if key in state and isinstance(state[key], list):
            state[key] = sorted(set(state[key]))
    write_json(Path(state_dir) / "dd_first_loop_state.json", state)


def _rewrite_reports(args: argparse.Namespace, rows: list[dict[str, Any]]) -> None:
    write_dd_first_summary(Path(args.reports_dir) / "dd_first_summary.csv", rows)


def _write_loop_summary(args: argparse.Namespace, rows: list[dict[str, Any]], state: dict[str, Any]) -> None:
    lines = ["# DD_FIRST Loop Summary", "", f"- Status: {state.get('status')}", f"- Stop reason: {state.get('stop_reason')}", f"- Completed real runs: {len(rows)}", f"- Failed attempts: {state.get('failed_attempts', 0)}", f"- Repaired errors: {state.get('repaired_errors', 0)}", "", "| run_id | strategy_id | CAGR | SPY CAGR | excess | max DD | parent DD | DD improvement | Calmar | years W/L | trades | decision |", "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|"]
    for row in rows:
        lines.append(f"| {row.get('run_id')} | {row.get('strategy_id')} | {row.get('strategy_cagr_pct')} | {row.get('spy_cagr_pct')} | {row.get('excess_cagr_pct')} | {row.get('strategy_max_drawdown_pct')} | {row.get('parent_max_drawdown_pct')} | {row.get('drawdown_improvement_vs_parent_pct')} | {row.get('calmar_ratio')} | {row.get('years_beating_spy')}/{row.get('years_losing_to_spy')} | {row.get('trades')} | {row.get('dd_first_decision')} |")
    path = Path(args.reports_dir) / "dd_first_loop_summary.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
