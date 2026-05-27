"""Adaptive DD20 research daemon.

Loop: observe empirical frontier -> choose causal axis -> generate candidates ->
run/evaluate real backtests -> update reports/frontier -> repeat.
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

from backtester.dd20_spy_beater import DD20_MIN_TRADES, row_from_dd20_audit_or_run, write_dd20_summary_csv, write_dd20_summary_markdown
from scripts.dd20_adaptive_strategy_generator import (
    BASE_NEAR_VALID_SL10,
    DEFAULT_AXIS_MEMORY,
    FAMILY,
    build_frontier_memory,
    classify_row,
    config_hash,
    generate_next_dd20_strategies,
    hypothesis_entry,
    render_strategy_config,
    strategy_registry_entry,
)
from scripts.run_dd20_spy_beater_daemon import FULL_HISTORY_PARENT, assert_full_history_parent, config_path_for
from scripts.run_dd20_stop_trailing_repair import exit_counts, f, i
from scripts.run_dd_first_autofix_loop import _preflight, attempt_repair, classify_error, read_json, read_jsonl, write_json, write_jsonl
from scripts.run_dd_first_autonomous_daemon import _state_snapshot, assert_parent_baseline_unchanged

ADAPTIVE_COLUMNS = [
    "batch",
    "run_id",
    "strategy_id",
    "generation_axis",
    "cagr",
    "spy_cagr",
    "excess_cagr",
    "max_drawdown",
    "calmar",
    "trades",
    "years_beating_spy",
    "years_losing_to_spy",
    "stop_loss_pct",
    "guard_stop",
    "guard_resume",
    "reduced_exposure_pct_when_active",
    "cooldown_rebalances",
    "allow_entries_when_active_top_n",
    "stop_loss_exit_count",
    "trailing_exit_count",
    "decision",
    "frontier_class",
    "rejection_reason",
]
REQUIRED_REAL_RUN_FILES = {
    "equity_curve.csv",
    "trades.csv",
    "metrics.json",
    "spy_comparison_daily.csv",
    "spy_comparison_monthly.csv",
    "spy_comparison_yearly.csv",
    "spy_comparison_summary.json",
    "run_manifest.json",
}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run adaptive DD20 SPY-beater research daemon.")
    p.add_argument("--batch-size", type=int, default=5)
    p.add_argument("--max-batches", type=int, default=1)
    p.add_argument("--max-total-attempts", type=int, default=25)
    p.add_argument("--max-wall-clock-hours", type=float, default=8)
    p.add_argument("--target-valid-strategies", type=int, default=1)
    p.add_argument("--target-excellent-strategies", type=int, default=1)
    p.add_argument("--continue-after-first-valid", action="store_true")
    p.add_argument("--resume", action="store_true")
    p.add_argument("--weekly-file", default="data/sp500_feature_store_weekly_master_260523155332.csv")
    p.add_argument("--daily-folder", default="data")
    p.add_argument("--parent-strategy-config", default="configs/generated/HYP_AUTO_TIME_SERIES_MOMENTUM_SEED.json")
    p.add_argument("--parent-run-id", default=FULL_HISTORY_PARENT)
    p.add_argument("--project-config", default="configs/project_config.json")
    p.add_argument("--strategy-registry", default="configs/strategy_registry.json")
    p.add_argument("--hypothesis-bank", default="bibliography/hypothesis_bank.jsonl")
    p.add_argument("--runs-dir", default="runs")
    p.add_argument("--reports-dir", default="reports")
    p.add_argument("--state-dir", default="state")
    p.add_argument("--per-run-timeout-minutes", type=float, default=45)
    p.add_argument("--min-trades", type=int, default=DD20_MIN_TRADES)
    return p.parse_args()


def main() -> int:
    args = parse_args()
    parent_snapshot = _state_snapshot(args.state_dir)
    state_path = Path(args.state_dir) / "dd20_adaptive_daemon_state.json"
    state = read_json(state_path) if args.resume and state_path.exists() else {}
    state.update({"status": "running", "phase": "dd20_adaptive_research", "parent_run_id": args.parent_run_id, "last_error": ""})
    write_json(state_path, state)

    try:
        weekly_file, daily_folder, parent_run_id = _preflight(args)
        if parent_run_id != args.parent_run_id:
            parent_run_id = args.parent_run_id
        assert_full_history_parent(args.runs_dir, parent_run_id)
        assert_parent_baseline_unchanged(args.state_dir, parent_snapshot)
    except Exception as exc:
        state.update({"status": "failed", "stop_reason": "preflight_failed", "last_error": str(exc)})
        write_json(state_path, state)
        return 2

    start = time.monotonic()
    attempts = int(state.get("total_attempts", 0)) if args.resume else 0
    completed_real = int(state.get("completed_real_runs", 0)) if args.resume else 0
    consecutive_error_counts: dict[str, int] = {}
    stop_reason = ""

    for batch_number in range(int(state.get("last_batch", 0)) + 1, args.max_batches + 1):
        completed_this_batch = 0
        batch_specs = []
        while completed_this_batch < args.batch_size:
            if attempts >= args.max_total_attempts:
                stop_reason = "max_total_attempts_reached"
                break
            if (time.monotonic() - start) / 3600.0 >= args.max_wall_clock_hours:
                stop_reason = "max_wall_clock_hours_reached"
                break
            assert_parent_baseline_unchanged(args.state_dir, parent_snapshot)
            frontier = build_frontier_memory(
                reports_dir=args.reports_dir,
                runs_dir=args.runs_dir,
                state_dir=args.state_dir,
                parent_run_id=parent_run_id,
                min_trades=args.min_trades,
            )
            axis_memory = load_axis_memory(args.state_dir)
            specs = generate_next_dd20_strategies(frontier, axis_memory, batch_size=max(1, args.batch_size - completed_this_batch))
            specs = [s for s in specs if s["strategy_id"] not in state.get("completed_strategy_ids", []) and s["strategy_id"] not in state.get("attempted_strategy_ids", [])]
            if not specs:
                stop_reason = "no_new_non_duplicate_strategies"
                break
            for spec in specs:
                if completed_this_batch >= args.batch_size or attempts >= args.max_total_attempts:
                    break
                write_strategy_artifacts(args, spec)
                attempts += 1
                state["total_attempts"] = attempts
                state.setdefault("attempted_strategy_ids", []).append(spec["strategy_id"])
                run_id = next_run_id(args.runs_dir, batch_number, spec["strategy_id"])
                result = run_candidate(run_id, spec["strategy_id"], config_path_for(args.strategy_registry, spec["strategy_id"]), weekly_file, daily_folder, parent_run_id, args)
                if not result["ok"]:
                    classification = classify_error(result["error"])
                    consecutive_error_counts[classification] = consecutive_error_counts.get(classification, 0) + 1
                    state["last_error"] = f"{classification}: {result['error'][:500]}"
                    repaired = attempt_repair(classification, config_path_for(args.strategy_registry, spec["strategy_id"]), set())
                    if repaired and attempts < args.max_total_attempts:
                        attempts += 1
                        run_id = next_run_id(args.runs_dir, batch_number, spec["strategy_id"])
                        result = run_candidate(run_id, spec["strategy_id"], config_path_for(args.strategy_registry, spec["strategy_id"]), weekly_file, daily_folder, parent_run_id, args)
                    if not result["ok"]:
                        update_axis_memory(args.state_dir, spec["generation_axis"], {"error": classification})
                        if consecutive_error_counts[classification] >= 5:
                            stop_reason = "same_error_appeared_5_times"
                            break
                        continue
                if not is_real_run(Path(args.runs_dir) / run_id):
                    state["last_error"] = f"missing_real_run_artifacts:{run_id}"
                    update_axis_memory(args.state_dir, spec["generation_axis"], {"error": "missing_real_run_artifacts"})
                    continue
                row = result["row"]
                frontier_class = classify_row(row, min_trades=args.min_trades)
                if i(row.get("trades")) == 0:
                    update_axis_memory(args.state_dir, spec["generation_axis"], {"zero_trades": True})
                    continue
                completed_this_batch += 1
                completed_real += 1
                batch_specs.append(spec["strategy_id"])
                state.setdefault("completed_strategy_ids", []).append(spec["strategy_id"])
                state["completed_real_runs"] = completed_real
                state["last_run_id"] = run_id
                update_axis_memory(args.state_dir, spec["generation_axis"], {"row": row, "frontier_class": frontier_class})
                update_reports(args, parent_run_id, batch_number, state)
                write_json(state_path, state)
            if stop_reason:
                break
        state["last_batch"] = batch_number
        update_reports(args, parent_run_id, batch_number, state)
        valid_count = len([r for r in read_frontier_rows(args) if classify_row(r, min_trades=args.min_trades) == "valid_candidate"])
        if valid_count >= args.target_valid_strategies and not args.continue_after_first_valid:
            stop_reason = "target_valid_strategies_reached"
        if stop_reason:
            break

    state.update({"status": "completed" if not stop_reason or not stop_reason.endswith("failed") else "failed", "stop_reason": stop_reason or "max_batches_reached", "updated_at": utc_now()})
    update_reports(args, args.parent_run_id, int(state.get("last_batch", 0) or 0), state)
    write_json(state_path, state)
    print(f"DD20 adaptive daemon completed: attempts={state.get('total_attempts')} real_runs={state.get('completed_real_runs')} stop={state.get('stop_reason')}")
    return 0


def write_strategy_artifacts(args: argparse.Namespace, spec: dict[str, Any]) -> None:
    cfg = render_strategy_config(spec)
    out_path = Path("configs/generated") / f"{spec['strategy_id']}.json"
    write_json(out_path, cfg)

    registry = read_json(args.strategy_registry)
    existing = {item.get("strategy_id") for item in registry.get("strategies", [])}
    if spec["strategy_id"] not in existing:
        registry.setdefault("strategies", []).append(strategy_registry_entry(spec, out_path))
        write_json(args.strategy_registry, registry)

    bank = read_jsonl(args.hypothesis_bank)
    existing_hyp = {item.get("hypothesis_id") for item in bank}
    if spec["strategy_id"] not in existing_hyp:
        bank.append(hypothesis_entry(spec, cfg))
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


def update_reports(args: argparse.Namespace, parent_run_id: str, batch_number: int, state: dict[str, Any]) -> None:
    frontier = build_frontier_memory(
        reports_dir=args.reports_dir,
        runs_dir=args.runs_dir,
        state_dir=args.state_dir,
        parent_run_id=parent_run_id,
        min_trades=args.min_trades,
    )
    all_rows = frontier.get("all_rows", [])
    write_dd20_summary_csv(Path(args.reports_dir) / "dd20_spy_beater_summary.csv", all_rows)
    write_dd20_summary_markdown(Path(args.reports_dir) / "dd20_spy_beater_summary.md", all_rows)

    adaptive_rows = [enrich_adaptive_row(args, r, batch_number) for r in all_rows if str(r.get("strategy_id", "")).startswith("HYP_DD20_ADAPT_")]
    write_csv(Path(args.reports_dir) / "dd20_adaptive_batches.csv", adaptive_rows, ADAPTIVE_COLUMNS)
    write_csv(Path(args.reports_dir) / "dd20_frontier.csv", all_rows, sorted({k for row in all_rows for k in row.keys()}))
    write_axis_summary(args.state_dir, args.reports_dir)
    Path(args.reports_dir, "dd20_adaptive_daemon_summary.md").write_text(build_adaptive_markdown(frontier, adaptive_rows, state), encoding="utf-8")
    Path(args.reports_dir, "dd20_best_so_far.md").write_text(build_best_so_far(frontier), encoding="utf-8")
    state["frontier"] = {k: frontier.get(k) for k in ["class_counts", "best_valid_by_cagr", "best_near_valid", "best_near_valid_low_trades", "next_axis_recommendation", "last_generation_reason"]}
    state["updated_at"] = utc_now()
    write_json(Path(args.state_dir) / "dd20_spy_beater_state.json", state)
    update_learning(args.state_dir, frontier)


def enrich_adaptive_row(args: argparse.Namespace, row: dict[str, Any], batch_number: int) -> dict[str, Any]:
    sid = str(row.get("strategy_id") or "")
    cfg = read_json(config_path_for(args.strategy_registry, sid)) if sid else {}
    risk = cfg.get("risk_management", {}) or {}
    guard = risk.get("equity_drawdown_guard", {}) or {}
    counts = exit_counts(Path(args.runs_dir) / str(row.get("run_id")) / "trades.csv")
    out = dict(row)
    out.update(
        {
            "batch": batch_number,
            "generation_axis": cfg.get("generation_axis", ""),
            "stop_loss_pct": risk.get("stop_loss_pct", ""),
            "guard_stop": guard.get("stop_new_entries_drawdown_pct", ""),
            "guard_resume": guard.get("resume_drawdown_pct", ""),
            "reduced_exposure_pct_when_active": guard.get("reduced_exposure_pct_when_active", ""),
            "cooldown_rebalances": guard.get("cooldown_rebalances", ""),
            "allow_entries_when_active_top_n": guard.get("allow_entries_when_active_top_n", ""),
            "stop_loss_exit_count": counts.get("stop_loss", 0),
            "trailing_exit_count": counts.get("trailing_stop", 0),
            "frontier_class": classify_row(row, min_trades=args.min_trades),
        }
    )
    return out


def build_adaptive_markdown(frontier: dict[str, Any], adaptive_rows: list[dict[str, Any]], state: dict[str, Any]) -> str:
    valid = frontier.get("valid_candidate", [])
    near = frontier.get("best_near_valid")
    lines = [
        "# DD20 Adaptive Daemon Summary",
        "",
        f"- Completed real runs: {state.get('completed_real_runs', 0)}",
        f"- Next axis: `{frontier.get('next_axis_recommendation', '')}`",
        f"- Reason: {frontier.get('last_generation_reason', '')}",
        "",
        "## Valid candidates",
        "",
    ]
    lines += ["- none"] if not valid else [_fmt(r) for r in valid]
    lines += ["", "## Best near-valid", "", _fmt(near), "", "## Adaptive batch rows", ""]
    lines += ["| strategy_id | CAGR | DD | trades | years W/L | class |", "|:---|---:|---:|---:|:---|:---|"]
    for row in sorted(adaptive_rows, key=lambda r: (r.get("frontier_class") != "valid_candidate", -f(r.get("cagr")))):
        lines.append(f"| `{row.get('strategy_id')}` | {f(row.get('cagr')):.4f}% | {f(row.get('max_drawdown')):.4f}% | {i(row.get('trades'))} | {i(row.get('years_beating_spy'))}/{i(row.get('years_losing_to_spy'))} | {row.get('frontier_class')} |")
    return "\n".join(lines) + "\n"


def build_best_so_far(frontier: dict[str, Any]) -> str:
    rows = frontier.get("all_rows", [])
    dd_ok = [r for r in rows if f(r.get("max_drawdown")) >= -20]
    dd_spy_ok = [r for r in dd_ok if f(r.get("cagr")) > f(r.get("spy_cagr"))]
    high_dd_breach = frontier.get("best_high_cagr_dd_breach")
    valid = frontier.get("best_valid_by_cagr")
    near = frontier.get("best_near_valid")
    lines = [
        "# DD20 Best So Far",
        "",
        f"- Best valid by CAGR: {_fmt(valid)}",
        f"- Best near-valid: {_fmt(near)}",
        f"- Highest CAGR under DD20: {_fmt(max(dd_ok, key=lambda r: f(r.get('cagr'))) if dd_ok else None)}",
        f"- Highest CAGR under DD20 and CAGR > SPY: {_fmt(max(dd_spy_ok, key=lambda r: f(r.get('cagr'))) if dd_spy_ok else None)}",
        f"- Best trade count under DD20: {_fmt(frontier.get('best_trade_count_under_dd20'))}",
        f"- Best years W/L under DD20: {_fmt(frontier.get('best_years_wl_under_dd20'))}",
        f"- Best DD-breach learning row: {_fmt(high_dd_breach)}",
        f"- What remains: {_missing(near)}",
        f"- Next axis: `{frontier.get('next_axis_recommendation', '')}`",
        f"- Why: {frontier.get('last_generation_reason', '')}",
    ]
    return "\n".join(lines) + "\n"


def write_axis_summary(state_dir: str, reports_dir: str) -> None:
    memory = load_axis_memory(state_dir)
    rows = []
    for axis, data in (memory.get("axis_outcomes") or {}).items():
        rows.append({"axis": axis, **data})
    write_csv(Path(reports_dir) / "dd20_axis_summary.csv", rows, sorted({k for row in rows for k in row.keys()}) or ["axis"])


def update_learning(state_dir: str, frontier: dict[str, Any]) -> None:
    path = Path(state_dir) / "dd20_spy_beater_learning.json"
    learning = read_json(path) if path.exists() else {"events": [], "recommendations": []}
    events = [event for event in learning.get("events", []) if event.get("phase") != "dd20_adaptive_research"]
    events.append(
        {
            "phase": "dd20_adaptive_research",
            "best_near_valid": frontier.get("best_near_valid"),
            "next_axis": frontier.get("next_axis_recommendation"),
            "lesson": frontier.get("last_generation_reason"),
        }
    )
    learning["events"] = events[-30:]
    learning["recommendations"] = [frontier.get("last_generation_reason", "Continue adaptive frontier search.")]
    write_json(path, learning)


def load_axis_memory(state_dir: str) -> dict[str, Any]:
    path = Path(state_dir) / "dd20_axis_memory.json"
    return read_json(path) if path.exists() else dict(DEFAULT_AXIS_MEMORY)


def update_axis_memory(state_dir: str, axis: str, outcome: dict[str, Any]) -> None:
    memory = load_axis_memory(state_dir)
    data = memory.setdefault("axis_outcomes", {}).setdefault(axis, {"runs": 0, "dd_breaches": 0, "low_trade_runs": 0, "duplicates": 0, "improvements": 0})
    data["runs"] = int(data.get("runs", 0)) + 1
    row = outcome.get("row") or {}
    if row:
        if f(row.get("max_drawdown")) < -22:
            data["dd_breaches"] = int(data.get("dd_breaches", 0)) + 1
        if i(row.get("trades")) < 500:
            data["low_trade_runs"] = int(data.get("low_trade_runs", 0)) + 1
        if outcome.get("frontier_class") in {"valid_candidate", "near_valid_low_trades"}:
            data["improvements"] = int(data.get("improvements", 0)) + 1
    if outcome.get("error") in {"duplicate", "no_op"}:
        data["duplicates"] = int(data.get("duplicates", 0)) + 1
    cooldown = set(memory.get("cooldown_axes", []))
    exhausted = set(memory.get("exhausted_axes", []))
    if int(data.get("dd_breaches", 0)) >= 3 or int(data.get("low_trade_runs", 0)) >= 3:
        cooldown.add(axis)
    if int(data.get("duplicates", 0)) >= 3:
        exhausted.add(axis)
    memory["cooldown_axes"] = sorted(cooldown)
    memory["exhausted_axes"] = sorted(exhausted)
    memory["active_axes"] = sorted({axis for axis in memory.get("axis_outcomes", {}) if axis not in cooldown and axis not in exhausted})
    write_json(Path(state_dir) / "dd20_axis_memory.json", memory)


def read_frontier_rows(args: argparse.Namespace) -> list[dict[str, Any]]:
    path = Path(args.reports_dir) / "dd20_frontier.csv"
    if path.exists():
        with path.open("r", encoding="utf-8-sig", newline="") as fh:
            return list(csv.DictReader(fh, delimiter=";"))
    return []


def is_real_run(run_dir: Path) -> bool:
    return run_dir.exists() and all((run_dir / name).exists() for name in REQUIRED_REAL_RUN_FILES)


def next_run_id(runs_dir: str, batch_number: int, strategy_id: str) -> str:
    stem = f"DD20ADAPT_{batch_number:03d}_{strategy_id}"[:120]
    candidate = stem
    n = 1
    while (Path(runs_dir) / candidate).exists():
        n += 1
        candidate = f"{stem}_{n}"
    return candidate


def write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore", delimiter=";")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _csv_value(row.get(key, "")) for key in columns})


def _fmt(row: dict[str, Any] | None) -> str:
    if not row:
        return "none"
    return f"`{row.get('strategy_id')}` CAGR {f(row.get('cagr')):.4f}%, DD {f(row.get('max_drawdown')):.4f}%, trades {i(row.get('trades'))}, years {i(row.get('years_beating_spy'))}/{i(row.get('years_losing_to_spy'))}, class {row.get('frontier_class', classify_row(row))}"


def _missing(row: dict[str, Any] | None) -> str:
    if not row:
        return "no near-valid frontier yet"
    gaps = []
    if f(row.get("max_drawdown")) < -20:
        gaps.append("DD20")
    if f(row.get("cagr")) <= f(row.get("spy_cagr")):
        gaps.append("CAGR > SPY")
    if i(row.get("trades")) < DD20_MIN_TRADES:
        gaps.append(f"trades +{DD20_MIN_TRADES - i(row.get('trades'))}")
    if i(row.get("years_beating_spy")) < i(row.get("years_losing_to_spy")):
        gaps.append("years W/L")
    return ", ".join(gaps) or "nothing"


def _csv_value(value: Any) -> Any:
    if isinstance(value, float):
        return str(value).replace(".", ",")
    return value


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
