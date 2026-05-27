"""Continuous supervisor for the adaptive DD20 daemon.

This wrapper keeps launching short adaptive-daemon cycles. It only stops on
supervisor-level safety conditions, manual stop file, or hard governance issues.
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtester.dd20_spy_beater import DD20_MIN_TRADES
from scripts.dd20_adaptive_strategy_generator import DD20_AXIS_ORDER, build_frontier_memory, classify_row, expand_generation_space
from scripts.run_dd20_adaptive_research_daemon import load_axis_memory
from scripts.run_dd20_spy_beater_daemon import FULL_HISTORY_PARENT, assert_full_history_parent
from scripts.run_dd20_stop_trailing_repair import f, i
from scripts.run_dd_first_autofix_loop import attempt_repair, classify_error, read_json, write_json
from scripts.run_dd_first_autonomous_daemon import _state_snapshot, assert_parent_baseline_unchanged

STOP_FILE = "stop_dd20_supervisor.txt"
CONTINUE_STOP_REASONS = {
    "max_batches_reached",
    "max_total_attempts_reached",
    "max_wall_clock_hours_reached",
    "target_valid_strategies_reached",
    "no_new_non_duplicate_strategies",
}
REPAIRABLE_ERRORS = {"config_error", "data_or_column_error", "code_error", "timeout", "missing_artifacts", "unknown"}
CYCLE_COLUMNS = [
    "cycle",
    "started_at",
    "ended_at",
    "daemon_stop_reason",
    "attempts_before",
    "attempts_after",
    "real_runs_before",
    "real_runs_after",
    "best_near_valid_before",
    "best_near_valid_after",
    "best_valid_after",
    "expansion_done",
    "repair_done",
    "next_axis",
]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Continuously supervise the adaptive DD20 daemon.")
    p.add_argument("--cycle-max-batches", type=int, default=5)
    p.add_argument("--cycle-max-total-attempts", type=int, default=50)
    p.add_argument("--max-cycles", type=int, default=100)
    p.add_argument("--max-wall-clock-hours", type=float, default=168)
    p.add_argument("--per-run-timeout-minutes", type=float, default=45)
    p.add_argument("--continue-after-first-valid", action="store_true", default=True)
    p.add_argument("--stop-after-excellent", action="store_true", default=False)
    p.add_argument("--target-valid-strategies", type=int, default=5)
    p.add_argument("--target-excellent-strategies", type=int, default=1)
    p.add_argument("--sleep-between-cycles-seconds", type=float, default=30)
    p.add_argument("--resume", action="store_true")
    p.add_argument("--weekly-file", default="data/sp500_feature_store_weekly_master_260523155332.csv")
    p.add_argument("--daily-folder", default="data")
    p.add_argument("--parent-strategy-config", default="configs/generated/HYP_AUTO_TIME_SERIES_MOMENTUM_SEED.json")
    p.add_argument("--parent-run-id", default=FULL_HISTORY_PARENT)
    p.add_argument("--project-config", default="configs/project_config.json")
    p.add_argument("--strategy-registry", default="configs/strategy_registry.json")
    p.add_argument("--runs-dir", default="runs")
    p.add_argument("--reports-dir", default="reports")
    p.add_argument("--state-dir", default="state")
    p.add_argument("--min-trades", type=int, default=DD20_MIN_TRADES)
    p.add_argument("--substantial-improvement-mode", action="store_true")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    state_path = Path(args.state_dir) / "dd20_supervisor_state.json"
    state = read_json(state_path) if args.resume and state_path.exists() else {}
    state.update({"status": "running", "parent_run_id": args.parent_run_id, "last_error": ""})
    parent_snapshot = _state_snapshot(args.state_dir)
    start = time.monotonic()

    try:
        assert_full_history_parent(args.runs_dir, args.parent_run_id)
        assert_parent_baseline_unchanged(args.state_dir, parent_snapshot)
    except Exception as exc:
        state.update({"status": "failed", "stop_reason": "parent_or_baseline_lock_compromised", "last_error": str(exc), "updated_at": utc_now()})
        write_supervisor_reports(args, state, [])
        return 2

    cycles = load_cycles(args.reports_dir) if args.resume else []
    repeated_errors = dict(state.get("repeated_errors", {}))
    no_improve_cycles = int(state.get("no_improve_cycles", 0))
    no_substantial_cycles = int(state.get("no_substantial_cycles", 0))
    previous_best_key = best_key(read_frontier(args))
    cycle_start_number = int(state.get("cycle", 0)) + 1 if args.resume else 1

    for cycle in range(cycle_start_number, args.max_cycles + 1):
        if manual_stop_requested(ROOT):
            state.update({"status": "stopped", "stop_reason": "manual_stop_file", "next_action": "stopped by stop_dd20_supervisor.txt"})
            break
        if (time.monotonic() - start) / 3600.0 >= args.max_wall_clock_hours:
            state.update({"status": "stopped", "stop_reason": "supervisor_max_wall_clock_reached", "next_action": "increase max-wall-clock-hours to continue"})
            break

        daemon_before = read_daemon_state(args.state_dir)
        frontier_before = read_frontier(args)
        attempts_before = int(daemon_before.get("total_attempts", 0))
        real_before = int(daemon_before.get("completed_real_runs", 0))
        started_at = utc_now()

        result = run_daemon_cycle(args, daemon_before)
        daemon_after = read_daemon_state(args.state_dir)
        stop_reason = str(daemon_after.get("stop_reason") or ("daemon_failed" if result.returncode else "unknown"))
        frontier_after = build_frontier_memory(
            reports_dir=args.reports_dir,
            runs_dir=args.runs_dir,
            state_dir=args.state_dir,
            parent_run_id=args.parent_run_id,
            min_trades=args.min_trades,
        )

        repair_done = ""
        expansion_done = ""
        if result.returncode != 0:
            err_class = classify_error((result.stderr or result.stdout or "")[-2000:])
            repeated_errors[err_class] = int(repeated_errors.get(err_class, 0)) + 1
            if err_class in REPAIRABLE_ERRORS:
                repair_done = err_class
                attempt_repair(err_class, args.parent_strategy_config, set())
            if repeated_errors[err_class] >= 5:
                state.update({"status": "failed", "stop_reason": "same_error_not_repairable_5_times", "last_error": err_class})
                break

        current_best_key = best_key(frontier_after)
        no_improve_cycles = no_improve_cycles + 1 if current_best_key == previous_best_key else 0
        previous_best_key = current_best_key
        no_substantial_cycles = substantial_cycles_since_improvement(args, no_substantial_cycles)
        if args.substantial_improvement_mode and no_substantial_cycles >= 15:
            switch_axis_after_stale_substantial_search(args, frontier_after)
            expansion_done = "axis_changed_after_15_no_substantial"
        if args.substantial_improvement_mode and no_substantial_cycles >= 40:
            stop_reason = "expand_after_40_no_substantial"
        if stop_reason in {"no_new_non_duplicate_strategies", "expand_after_40_no_substantial"} or no_improve_cycles >= 2:
            axis_memory = load_axis_memory(args.state_dir)
            expanded = expand_generation_space(frontier_after, axis_memory)
            write_json(Path(args.state_dir) / "dd20_axis_memory.json", expanded)
            expansion_done = str((expanded.get("last_expansion") or {}).get("spec_count", ""))
            no_improve_cycles = 0
        if args.substantial_improvement_mode and all_axes_exhausted(args.state_dir):
            stop_reason = "all_axes_exhausted"

        row = {
            "cycle": cycle,
            "started_at": started_at,
            "ended_at": utc_now(),
            "daemon_stop_reason": stop_reason,
            "attempts_before": attempts_before,
            "attempts_after": int(daemon_after.get("total_attempts", 0)),
            "real_runs_before": real_before,
            "real_runs_after": int(daemon_after.get("completed_real_runs", 0)),
            "best_near_valid_before": fmt_strategy(frontier_before.get("best_near_valid")),
            "best_near_valid_after": fmt_strategy(frontier_after.get("best_near_valid")),
            "best_valid_after": fmt_strategy(frontier_after.get("best_valid_by_cagr")),
            "expansion_done": expansion_done,
            "repair_done": repair_done,
            "next_axis": frontier_after.get("next_axis_recommendation", ""),
        }
        cycles.append(row)
        state.update(
            {
                "status": "running",
                "cycle": cycle,
                "daemon_state": {
                    "total_attempts": int(daemon_after.get("total_attempts", 0)),
                    "completed_real_runs": int(daemon_after.get("completed_real_runs", 0)),
                    "last_batch": int(daemon_after.get("last_batch", 0) or 0),
                },
                "last_stop_reason": stop_reason,
                "last_repair": repair_done,
                "last_expansion": expansion_done,
                "no_improve_cycles": no_improve_cycles,
                "no_substantial_cycles": no_substantial_cycles,
                "repeated_errors": repeated_errors,
                "next_action": decide_next_action(stop_reason, args, frontier_after),
                "updated_at": utc_now(),
            }
        )
        write_supervisor_reports(args, state, cycles)
        assert_parent_baseline_unchanged(args.state_dir, parent_snapshot)

        if should_stop_after_cycle(stop_reason, args, frontier_after, result.returncode):
            state["status"] = "stopped"
            break
        if manual_stop_requested(ROOT):
            state.update({"status": "stopped", "stop_reason": "manual_stop_file", "next_action": "stopped by stop_dd20_supervisor.txt"})
            break
        time.sleep(max(0.0, float(args.sleep_between_cycles_seconds)))

    state.setdefault("stop_reason", "max_cycles_reached")
    state["daemon_state"] = {
        "total_attempts": int(read_daemon_state(args.state_dir).get("total_attempts", 0)),
        "completed_real_runs": int(read_daemon_state(args.state_dir).get("completed_real_runs", 0)),
        "last_batch": int(read_daemon_state(args.state_dir).get("last_batch", 0) or 0),
    }
    if state.get("status") == "running":
        state["status"] = "completed"
        state["stop_reason"] = "max_cycles_reached"
    state["updated_at"] = utc_now()
    write_supervisor_reports(args, state, cycles)
    print(f"DD20 supervisor {state['status']}: cycle={state.get('cycle', 0)} stop={state.get('stop_reason') or state.get('last_stop_reason')} next={state.get('next_action')}")
    return 0 if state.get("status") != "failed" else 2


def run_daemon_cycle(args: argparse.Namespace, daemon_before: dict[str, Any]) -> subprocess.CompletedProcess[str]:
    max_batches = int(daemon_before.get("last_batch", 0)) + int(args.cycle_max_batches)
    max_attempts = int(daemon_before.get("total_attempts", 0)) + int(args.cycle_max_total_attempts)
    cmd = [
        sys.executable,
        "scripts/run_dd20_adaptive_research_daemon.py",
        "--batch-size",
        "5",
        "--max-batches",
        str(max_batches),
        "--max-total-attempts",
        str(max_attempts),
        "--max-wall-clock-hours",
        str(args.max_wall_clock_hours),
        "--per-run-timeout-minutes",
        str(args.per_run_timeout_minutes),
        "--target-valid-strategies",
        str(args.target_valid_strategies),
        "--target-excellent-strategies",
        str(args.target_excellent_strategies),
        "--weekly-file",
        args.weekly_file,
        "--daily-folder",
        args.daily_folder,
        "--parent-strategy-config",
        args.parent_strategy_config,
        "--parent-run-id",
        args.parent_run_id,
        "--project-config",
        args.project_config,
        "--strategy-registry",
        args.strategy_registry,
        "--runs-dir",
        args.runs_dir,
        "--reports-dir",
        args.reports_dir,
        "--state-dir",
        args.state_dir,
        "--min-trades",
        str(args.min_trades),
        "--resume",
    ]
    if args.continue_after_first_valid:
        cmd.append("--continue-after-first-valid")
    if args.substantial_improvement_mode:
        cmd.append("--substantial-improvement-mode")
    return subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, check=False)


def should_stop_after_cycle(stop_reason: str, args: argparse.Namespace, frontier: dict[str, Any], returncode: int = 0) -> bool:
    if returncode != 0 and stop_reason not in CONTINUE_STOP_REASONS:
        return True
    if stop_reason == "target_valid_strategies_reached" and args.continue_after_first_valid:
        return False
    if stop_reason in CONTINUE_STOP_REASONS:
        return False
    if args.stop_after_excellent and len(frontier.get("valid_candidate", [])) >= args.target_excellent_strategies:
        return True
    return stop_reason in {"parent_or_baseline_lock_compromised", "missing_real_data", "same_error_appeared_5_times", "all_axes_exhausted"}


def substantial_cycles_since_improvement(args: argparse.Namespace, current: int) -> int:
    state = read_substantial_state(args.state_dir)
    last = state.get("last_substantial_improvement") or {}
    marker = str(last.get("strategy_id") or "") if isinstance(last, dict) else ""
    previous_marker = str(read_daemon_state(args.state_dir).get("last_substantial_marker") or "")
    daemon_state = read_daemon_state(args.state_dir)
    if marker and marker != previous_marker:
        daemon_state["last_substantial_marker"] = marker
        write_json(Path(args.state_dir) / "dd20_adaptive_daemon_state.json", daemon_state)
        return 0
    return current + 1


def switch_axis_after_stale_substantial_search(args: argparse.Namespace, frontier: dict[str, Any]) -> None:
    axis = str(frontier.get("next_axis_recommendation") or "")
    memory = load_axis_memory(args.state_dir)
    cooldown = set(memory.get("cooldown_axes", []))
    if axis:
        cooldown.add(axis)
    memory["cooldown_axes"] = sorted(cooldown)
    write_json(Path(args.state_dir) / "dd20_axis_memory.json", memory)


def all_axes_exhausted(state_dir: str) -> bool:
    memory = load_axis_memory(state_dir)
    exhausted = set(memory.get("exhausted_axes", []))
    return bool(DD20_AXIS_ORDER) and set(DD20_AXIS_ORDER).issubset(exhausted)


def read_substantial_state(state_dir: str) -> dict[str, Any]:
    path = Path(state_dir) / "dd20_substantial_improvement_state.json"
    return read_json(path) if path.exists() else {}


def decide_next_action(stop_reason: str, args: argparse.Namespace, frontier: dict[str, Any]) -> str:
    if stop_reason == "all_axes_exhausted":
        return "stopped_all_axes_exhausted"
    if stop_reason == "expand_after_40_no_substantial":
        return "expand_generation_space_then_continue"
    if stop_reason == "no_new_non_duplicate_strategies":
        return "expand_generation_space_then_continue"
    if stop_reason in CONTINUE_STOP_REASONS:
        return "continue_next_cycle"
    if frontier.get("best_valid_by_cagr") and args.continue_after_first_valid:
        return "continue_searching_better_valid"
    return "inspect_stop_reason"


def write_supervisor_reports(args: argparse.Namespace, state: dict[str, Any], cycles: list[dict[str, Any]]) -> None:
    reports = Path(args.reports_dir)
    reports.mkdir(parents=True, exist_ok=True)
    state_path = Path(args.state_dir) / "dd20_supervisor_state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(state_path, state)
    write_csv(reports / "dd20_supervisor_cycles.csv", cycles, CYCLE_COLUMNS)
    frontier = read_frontier(args)
    (reports / "dd20_supervisor_summary.md").write_text(build_summary(state, frontier), encoding="utf-8")


def build_summary(state: dict[str, Any], frontier: dict[str, Any]) -> str:
    daemon = state.get("daemon_state") or {}
    valid = frontier.get("best_valid_by_cagr")
    near = frontier.get("best_near_valid")
    dd_ok = _first(frontier.get("near_valid_low_trades", [])) or frontier.get("best_trade_count_under_dd20")
    return "\n".join(
        [
            "# DD20 Continuous Supervisor Summary",
            "",
            f"- Status: {state.get('status', '')}",
            f"- Cycle: {state.get('cycle', 0)}",
            f"- Total attempts: {daemon.get('total_attempts', '')}",
            f"- Total real runs: {daemon.get('completed_real_runs', '')}",
            f"- Valid candidates: {len(frontier.get('valid_candidate', []))}",
            f"- Excellent candidates: {len([r for r in frontier.get('valid_candidate', []) if f(r.get('cagr')) >= 10 and f(r.get('calmar')) >= 0.50])}",
            f"- Best valid: {fmt_strategy(valid)}",
            f"- Best near-valid: {fmt_strategy(near)}",
            f"- Best CAGR under DD20: {fmt_strategy(frontier.get('best_years_wl_under_dd20'))}",
            f"- Best DD20 + SPY: {fmt_strategy(dd_ok)}",
            f"- Current axis: `{frontier.get('next_axis_recommendation', '')}`",
            f"- Last stop_reason: {state.get('last_stop_reason') or state.get('stop_reason', '')}",
            f"- Last repair: {state.get('last_repair', '')}",
            f"- Last expansion: {state.get('last_expansion', '')}",
            f"- Next action: {state.get('next_action', '')}",
            "- Manual stop: create `stop_dd20_supervisor.txt` in repo root; supervisor exits after current cycle.",
            "",
        ]
    )


def read_daemon_state(state_dir: str) -> dict[str, Any]:
    path = Path(state_dir) / "dd20_adaptive_daemon_state.json"
    return read_json(path) if path.exists() else {}


def read_frontier(args: argparse.Namespace) -> dict[str, Any]:
    return build_frontier_memory(reports_dir=args.reports_dir, runs_dir=args.runs_dir, state_dir=args.state_dir, parent_run_id=args.parent_run_id, min_trades=getattr(args, "min_trades", DD20_MIN_TRADES))


def manual_stop_requested(root: Path = ROOT) -> bool:
    return (root / STOP_FILE).exists()


def best_key(frontier: dict[str, Any]) -> str:
    row = frontier.get("best_near_valid") or frontier.get("best_valid_by_cagr") or {}
    return "|".join(str(row.get(k, "")) for k in ["strategy_id", "cagr", "max_drawdown", "trades", "years_beating_spy", "years_losing_to_spy"])


def fmt_strategy(row: dict[str, Any] | None) -> str:
    if not row:
        return ""
    return f"{row.get('strategy_id')} cagr={f(row.get('cagr')):.4f} dd={f(row.get('max_drawdown')):.4f} trades={i(row.get('trades'))} years={i(row.get('years_beating_spy'))}/{i(row.get('years_losing_to_spy'))} class={row.get('frontier_class', classify_row(row))}"


def _first(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    return rows[0] if rows else None


def load_cycles(reports_dir: str) -> list[dict[str, Any]]:
    path = Path(reports_dir) / "dd20_supervisor_cycles.csv"
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh, delimiter=";"))


def write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore", delimiter=";")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
