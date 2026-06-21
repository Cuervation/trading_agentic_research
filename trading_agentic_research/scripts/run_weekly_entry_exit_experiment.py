"""Run causal weekly entry/exit variants for previously executed strategies."""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtester.data_loader import (
    load_daily_feature_store_folder,
    load_weekly_feature_store,
)
from scripts.run_backtest import run_backtest_and_write_artifacts

SUFFIX = "_WEEKLY_ENTRY_EXIT_V1"
PRIORITY_STATUSES = (
    "champion_history",
    "promotion_candidate",
    "secondary_candidate",
    "defensive_secondary_candidate",
    "candidate",
)
REPORT_COLUMNS = [
    "original_run_id",
    "original_strategy_id",
    "weekly_run_id",
    "weekly_strategy_id",
    "original_config_path",
    "weekly_config_path",
    "source",
    "original_cagr_pct",
    "weekly_cagr_pct",
    "spy_cagr_pct",
    "weekly_excess_cagr_pct",
    "original_max_drawdown_pct",
    "weekly_max_drawdown_pct",
    "spy_max_drawdown_pct",
    "dd_delta_vs_original",
    "dd_delta_vs_spy",
    "original_total_return_pct",
    "weekly_total_return_pct",
    "spy_total_return_pct",
    "original_trades",
    "weekly_trades",
    "trade_delta",
    "trade_multiplier",
    "years_beating_spy",
    "years_losing_to_spy",
    "months_beating_spy",
    "months_losing_to_spy",
    "recommendation_hint",
    "status",
    "warnings",
    "error",
]
REPORT_CHECKPOINT_EVERY = 25


def read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )


def optional_float(value):
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def resolve_data_paths(root: Path, project: dict) -> tuple[Path, Path]:
    paths = project.get("data_paths", {}) or {}
    weekly_raw = str(paths.get("weekly_file_path") or "").strip()
    daily_raw = str(paths.get("daily_folder_path") or "").strip()
    if weekly_raw:
        weekly = Path(weekly_raw)
        if not weekly.is_absolute():
            weekly = root / weekly
    else:
        candidates = sorted((root / "data").glob("*weekly*.csv"))
        if not candidates:
            raise FileNotFoundError("No weekly feature store found.")
        weekly = candidates[-1]
    if daily_raw:
        daily = Path(daily_raw)
        if not daily.is_absolute():
            daily = root / daily
    else:
        daily = root / "data"
    return weekly, daily


def registry_rows(root: Path) -> list[dict]:
    registry = read_json(root / "configs" / "strategy_registry.json", {}) or {}
    priority = {status: index for index, status in enumerate(PRIORITY_STATUSES)}
    rows = [
        row
        for row in registry.get("strategies", [])
        if row.get("status") in priority
        and not str(row.get("strategy_id", "")).endswith(SUFFIX)
    ]
    rows.sort(key=lambda row: (priority[row["status"]], str(row["strategy_id"])))
    return rows


def manifest_config_path(root: Path, manifest: dict) -> Path | None:
    for key in (
        "strategy_config_path",
        "config_path",
        "strategy_path",
        "generated_config_path",
    ):
        raw = str(manifest.get(key) or "").strip()
        if not raw:
            continue
        path = Path(raw)
        if not path.is_absolute():
            path = root / path
        if path.exists() and path.is_file():
            return path.resolve()
    return None


def fallback_config_path(
    root: Path, strategy_id: str, registry_by_id: dict[str, dict]
) -> Path | None:
    registry_row = registry_by_id.get(strategy_id, {})
    raw = str(registry_row.get("config_path") or "").strip()
    if raw:
        path = root / raw
        if path.exists():
            return path.resolve()
    direct = root / "configs" / "generated" / f"{strategy_id}.json"
    if direct.exists():
        return direct.resolve()
    return None


def run_metadata_score(candidate: dict) -> tuple[int, int]:
    manifest = candidate["manifest"]
    score = sum(
        bool(manifest.get(key))
        for key in (
            "strategy_config_path",
            "config_hash",
            "parent_run_id",
            "hypothesis_family",
            "strategy_family",
        )
    )
    return score, candidate["mtime_ns"]


def candidates_from_runs(root: Path, registry_by_id: dict[str, dict]) -> list[dict]:
    """Choose one complete, best-metadata/latest real run per strategy."""
    grouped: dict[str, list[dict]] = {}
    seen: set[tuple[str, str]] = set()
    for manifest_path in root.glob("runs/*/run_manifest.json"):
        run_dir = manifest_path.parent
        if not (run_dir / "metrics.json").exists():
            continue
        manifest = read_json(manifest_path, {}) or {}
        strategy_id = str(manifest.get("strategy_id") or "").strip()
        if not strategy_id or strategy_id.endswith(SUFFIX):
            continue
        if manifest.get("experiment") == "weekly_entry_exit":
            continue
        config_hash = str(manifest.get("config_hash") or "")
        key = (strategy_id, config_hash or run_dir.name)
        if key in seen:
            continue
        seen.add(key)
        config_path = manifest_config_path(root, manifest)
        if config_path is None:
            config_path = fallback_config_path(root, strategy_id, registry_by_id)
        grouped.setdefault(strategy_id, []).append(
            {
                "source": "runs",
                "strategy_id": strategy_id,
                "run_id": str(manifest.get("run_id") or run_dir.name),
                "run_dir": run_dir,
                "config_path": config_path,
                "config_hash": config_hash or None,
                "parent_run_id": manifest.get("parent_run_id"),
                "strategy_family": (
                    manifest.get("hypothesis_family")
                    or manifest.get("strategy_family")
                ),
                "manifest": manifest,
                "mtime_ns": manifest_path.stat().st_mtime_ns,
            }
        )
    selected = [
        max(items, key=run_metadata_score)
        for items in grouped.values()
    ]
    return sorted(selected, key=lambda row: row["strategy_id"])


def candidates_from_registry(root: Path) -> list[dict]:
    rows = []
    for row in registry_rows(root):
        path = root / str(row.get("config_path") or "")
        rows.append(
            {
                "source": "registry",
                "strategy_id": str(row["strategy_id"]),
                "run_id": None,
                "run_dir": None,
                "config_path": path.resolve() if path.exists() else None,
                "config_hash": None,
                "parent_run_id": None,
                "strategy_family": row.get("strategy_family"),
                "manifest": {},
                "mtime_ns": 0,
            }
        )
    return rows


def select_candidates(root: Path, source: str) -> list[dict]:
    registry = registry_rows(root)
    registry_by_id = {row["strategy_id"]: row for row in registry}
    run_rows = candidates_from_runs(root, registry_by_id)
    if source == "runs":
        return run_rows
    registry_candidates = candidates_from_registry(root)
    if source == "registry":
        return registry_candidates
    merged = {row["strategy_id"]: row for row in registry_candidates}
    for row in run_rows:
        merged[row["strategy_id"]] = {**merged.get(row["strategy_id"], {}), **row, "source": "both"}
    return sorted(merged.values(), key=lambda row: row["strategy_id"])


def clone_weekly_config(
    original: dict,
    original_path: Path,
    output_dir: Path,
    *,
    force: bool,
) -> tuple[dict, Path]:
    original_id = str(original["strategy_id"])
    weekly_id = f"{original_id}{SUFFIX}"
    weekly_path = output_dir / f"{weekly_id}.json"
    if weekly_path.exists() and not force:
        existing = read_json(weekly_path, {}) or {}
        if existing.get("strategy_id") == weekly_id:
            return existing, weekly_path
    weekly = deepcopy(original)
    weekly.update(
        {
            "strategy_id": weekly_id,
            "hypothesis_id": weekly_id,
            "parent_strategy_id": original_id,
            "decision_frequency": "weekly",
            "entry_frequency": "weekly",
            "exit_frequency": "weekly",
            "position_retention": "hold_until_exit_rank_threshold",
            "weekly_entry_exit_experiment": True,
            "experiment_type": "weekly_entry_exit_frequency_only",
            "original_config_path": str(original_path),
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "changed_parameters": [
                "decision_frequency",
                "entry_frequency",
                "exit_frequency",
                "position_retention",
            ],
        }
    )
    write_json(weekly_path, weekly)
    return weekly, weekly_path


def sanitize_run_component(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", value).strip("_")[:150]


def valid_weekly_run(run_dir: Path) -> bool:
    return (
        (run_dir / "metrics.json").exists()
        and (run_dir / "summary.md").exists()
        and (run_dir / "run_manifest.json").exists()
    )


def find_existing_weekly_run(
    root: Path, original_strategy_id: str, weekly_strategy_id: str
) -> str | None:
    matches = []
    for manifest_path in root.glob("runs/*/run_manifest.json"):
        manifest = read_json(manifest_path, {}) or {}
        if manifest.get("strategy_id") != weekly_strategy_id:
            continue
        if manifest.get("original_strategy_id") not in (None, original_strategy_id):
            continue
        if valid_weekly_run(manifest_path.parent):
            matches.append(manifest_path.parent)
    if not matches:
        return None
    return max(matches, key=lambda path: path.stat().st_mtime_ns).name


def update_weekly_manifest(
    root: Path,
    run_id: str,
    candidate: dict,
) -> None:
    original_id = candidate["strategy_id"]
    manifest_path = root / "runs" / run_id / "run_manifest.json"
    manifest = read_json(manifest_path, {}) or {}
    manifest.update(
        {
            "experiment": "weekly_entry_exit",
            "source": candidate["source"],
            "original_run_id": candidate.get("run_id"),
            "original_strategy_id": original_id,
            "original_config_hash": candidate.get("config_hash"),
            "original_strategy_family": candidate.get("strategy_family"),
            "decision_frequency": "weekly",
            "entry_frequency": "weekly",
            "exit_frequency": "weekly",
            "position_retention": "hold_until_exit_rank_threshold",
            "causal_execution_rule": "first_daily_close_strictly_after_signal_date",
            "governance": {
                "promotion_performed": False,
                "current_parent_updated": False,
                "current_baseline_updated": False,
            },
        }
    )
    write_json(manifest_path, manifest)


def build_weekly_run_id(original_id: str) -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    return (
        f"WEEKLY_{sanitize_run_component(original_id)}_{stamp}_{os.getpid()}"
    )


def run_variant(
    root: Path,
    weekly_file: Path,
    daily_folder: Path,
    project_path: Path,
    original_path: Path,
    weekly_path: Path,
    candidate: dict,
    weekly_id: str,
) -> str:
    original_id = candidate["strategy_id"]
    run_id = build_weekly_run_id(original_id)
    command = [
        sys.executable,
        str(root / "scripts" / "run_backtest.py"),
        "--weekly-file",
        str(weekly_file),
        "--daily-folder",
        str(daily_folder),
        "--strategy-config",
        str(weekly_path),
        "--project-config",
        str(project_path),
        "--run-id",
        run_id,
        "--runs-dir",
        str(root / "runs"),
        "--parent-strategy-config",
        str(original_path),
    ]
    if candidate.get("run_id"):
        command.extend(["--parent-run-id", str(candidate["run_id"])])
    completed = subprocess.run(command, cwd=root, capture_output=True, text=True)
    if completed.returncode:
        raise RuntimeError((completed.stderr or completed.stdout)[-1200:])
    update_weekly_manifest(root, run_id, candidate)
    return run_id


def run_variant_inprocess(
    root: Path,
    weekly_file: Path,
    daily_folder: Path,
    original_path: Path,
    weekly_path: Path,
    weekly_config: dict,
    project_config: dict,
    candidate: dict,
    weekly_df,
    daily_df,
) -> str:
    original_id = candidate["strategy_id"]
    run_id = build_weekly_run_id(original_id)
    parent_strategy_config = read_json(original_path, {}) or {}
    run_backtest_and_write_artifacts(
        weekly_df=weekly_df,
        daily_df=daily_df,
        strategy_config=weekly_config,
        project_config=project_config,
        run_id=run_id,
        runs_dir=root / "runs",
        strategy_config_path=weekly_path,
        weekly_file=weekly_file,
        daily_folder=daily_folder,
        parent_run_id=candidate.get("run_id"),
        parent_strategy_config=parent_strategy_config,
        parent_strategy_config_path=original_path,
    )
    update_weekly_manifest(root, run_id, candidate)
    return run_id


def process_candidate(
    root: Path,
    weekly_file: Path,
    daily_folder: Path,
    project_path: Path,
    generated_dir: Path,
    candidate: dict,
    *,
    generate_only: bool,
    resume: bool,
    force: bool,
    execution_backend: str = "subprocess",
    weekly_df=None,
    daily_df=None,
    project_config: dict | None = None,
) -> dict:
    original_id = candidate["strategy_id"]
    weekly_id = f"{original_id}{SUFFIX}"
    weekly_path = generated_dir / f"{weekly_id}.json"
    original_path = candidate.get("config_path")
    if not original_path:
        return result_row(
            root,
            candidate,
            None,
            weekly_path,
            weekly_id,
            None,
            "skipped_missing_config",
            "Original config could not be resolved from manifest/registry/generated configs.",
        )
    original = read_json(original_path, {}) or {}
    if not original:
        return result_row(
            root,
            candidate,
            original_path,
            weekly_path,
            weekly_id,
            None,
            "skipped_invalid_config",
            "Original config is unreadable or empty.",
        )
    weekly, weekly_path = clone_weekly_config(
        original, original_path, generated_dir, force=force
    )
    weekly_id = weekly["strategy_id"]
    existing_run = (
        find_existing_weekly_run(root, original_id, weekly_id)
        if resume and not force
        else None
    )
    if existing_run:
        return result_row(
            root,
            candidate,
            original_path,
            weekly_path,
            weekly_id,
            existing_run,
            "reused",
        )
    if generate_only:
        return result_row(
            root,
            candidate,
            original_path,
            weekly_path,
            weekly_id,
            None,
            "generated_only",
        )
    try:
        if execution_backend == "inprocess":
            weekly_run_id = run_variant_inprocess(
                root,
                weekly_file,
                daily_folder,
                original_path,
                weekly_path,
                weekly,
                project_config or {},
                candidate,
                weekly_df,
                daily_df,
            )
        else:
            weekly_run_id = run_variant(
                root,
                weekly_file,
                daily_folder,
                project_path,
                original_path,
                weekly_path,
                candidate,
                weekly_id,
            )
        return result_row(
            root,
            candidate,
            original_path,
            weekly_path,
            weekly_id,
            weekly_run_id,
            "completed",
        )
    except Exception as exc:
        return result_row(
            root,
            candidate,
            original_path,
            weekly_path,
            weekly_id,
            None,
            "failed",
            str(exc)[:1200],
        )


def trade_count(run_dir: Path, metrics: dict) -> int | None:
    diagnostics = metrics.get("diagnostics", {}) or {}
    value = diagnostics.get("number_of_trades")
    if value is not None:
        return int(value)
    trades_path = run_dir / "trades.csv"
    if not trades_path.exists():
        return None
    with trades_path.open(encoding="utf-8-sig") as handle:
        return max(sum(1 for _ in handle) - 1, 0)


def metrics_for_run(run_dir: Path | None) -> dict:
    if run_dir is None or not (run_dir / "metrics.json").exists():
        return {}
    metrics = read_json(run_dir / "metrics.json", {}) or {}
    return {
        "strategy": metrics.get("strategy", {}) or {},
        "spy": metrics.get("spy", {}) or {},
        "diagnostics": metrics.get("diagnostics", {}) or {},
        "trades": trade_count(run_dir, metrics),
        "comparison": read_json(run_dir / "spy_comparison_summary.json", {}) or {},
    }


def delta(left, right):
    left_value = optional_float(left)
    right_value = optional_float(right)
    if left_value is None or right_value is None:
        return None
    return left_value - right_value


def result_row(
    root: Path,
    candidate: dict,
    original_path: Path | None,
    weekly_path: Path,
    weekly_id: str,
    weekly_run_id: str | None,
    status: str,
    error: str = "",
) -> dict:
    row = {key: None for key in REPORT_COLUMNS}
    original_run_dir = (
        root / "runs" / str(candidate["run_id"])
        if candidate.get("run_id")
        else None
    )
    original = metrics_for_run(original_run_dir)
    weekly_run_dir = root / "runs" / weekly_run_id if weekly_run_id else None
    weekly = metrics_for_run(weekly_run_dir)
    original_strategy = original.get("strategy", {})
    weekly_strategy = weekly.get("strategy", {})
    weekly_spy = weekly.get("spy", {})
    comparison = weekly.get("comparison", {})
    original_trades = original.get("trades")
    weekly_trades = weekly.get("trades")
    warnings = list((weekly.get("diagnostics", {}) or {}).get("warnings", []))
    trade_multiplier = (
        weekly_trades / original_trades
        if weekly_trades is not None and original_trades not in (None, 0)
        else None
    )
    if (
        candidate["strategy_id"] == "HYP_AUTO_TIME_SERIES_MOMENTUM_SEED"
        and weekly_trades is not None
        and original_trades is not None
        and weekly_trades > original_trades
    ):
        warnings.append(
            "AUTO_002 weekly turnover/whipsaw warning: validated near "
            "CAGR 11.32%, DD -38.65%, 8551 vs 3706 trades."
        )
    row.update(
        {
            "original_run_id": candidate.get("run_id"),
            "original_strategy_id": candidate["strategy_id"],
            "weekly_run_id": weekly_run_id,
            "weekly_strategy_id": weekly_id,
            "original_config_path": str(original_path) if original_path else "",
            "weekly_config_path": str(weekly_path),
            "source": candidate["source"],
            "original_cagr_pct": original_strategy.get("cagr_pct"),
            "weekly_cagr_pct": weekly_strategy.get("cagr_pct"),
            "spy_cagr_pct": weekly_spy.get("cagr_pct"),
            "weekly_excess_cagr_pct": delta(
                weekly_strategy.get("cagr_pct"), weekly_spy.get("cagr_pct")
            ),
            "original_max_drawdown_pct": original_strategy.get("max_drawdown_pct"),
            "weekly_max_drawdown_pct": weekly_strategy.get("max_drawdown_pct"),
            "spy_max_drawdown_pct": weekly_spy.get("max_drawdown_pct"),
            "dd_delta_vs_original": delta(
                weekly_strategy.get("max_drawdown_pct"),
                original_strategy.get("max_drawdown_pct"),
            ),
            "dd_delta_vs_spy": delta(
                weekly_strategy.get("max_drawdown_pct"),
                weekly_spy.get("max_drawdown_pct"),
            ),
            "original_total_return_pct": original_strategy.get("total_return_pct"),
            "weekly_total_return_pct": weekly_strategy.get("total_return_pct"),
            "spy_total_return_pct": weekly_spy.get("total_return_pct"),
            "original_trades": original_trades,
            "weekly_trades": weekly_trades,
            "trade_delta": (
                weekly_trades - original_trades
                if weekly_trades is not None and original_trades is not None
                else None
            ),
            "trade_multiplier": trade_multiplier,
            "years_beating_spy": comparison.get("years_beating_spy"),
            "years_losing_to_spy": comparison.get("years_losing_to_spy"),
            "months_beating_spy": comparison.get("months_beating_spy"),
            "months_losing_to_spy": comparison.get("months_losing_to_spy"),
            "recommendation_hint": comparison.get("recommendation_hint"),
            "status": status,
            "warnings": " | ".join(str(item) for item in warnings),
            "error": error,
        }
    )
    return row


def ranked_rows(
    rows: list[dict], key: str, *, reverse: bool, limit: int = 10
) -> list[dict]:
    usable = [row for row in rows if optional_float(row.get(key)) is not None]
    return sorted(
        usable, key=lambda row: optional_float(row[key]), reverse=reverse
    )[:limit]


def ranking_section(title: str, rows: list[dict], metric: str) -> list[str]:
    lines = [
        f"## {title}",
        "",
        "| strategy | weekly run | metric | CAGR | Max DD | trades |",
        "|---|---|---:|---:|---:|---:|",
    ]
    if not rows:
        lines.append("| none | | | | | |")
    for row in rows:
        lines.append(
            "| {strategy} | {run} | {metric_value} | {cagr} | {dd} | {trades} |".format(
                strategy=row["weekly_strategy_id"],
                run=row.get("weekly_run_id") or "",
                metric_value=row.get(metric),
                cagr=row.get("weekly_cagr_pct"),
                dd=row.get("weekly_max_drawdown_pct"),
                trades=row.get("weekly_trades"),
            )
        )
    lines.append("")
    return lines


def write_report(report_dir: Path, rows: list[dict]) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    rows = sorted(rows, key=lambda row: str(row["original_strategy_id"]))
    with (report_dir / "weekly_entry_exit_summary.csv").open(
        "w", newline="", encoding="utf-8"
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=REPORT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    completed = [row for row in rows if row.get("status") in {"completed", "reused"}]
    cagr_deltas = [
        {**row, "cagr_delta_vs_original": delta(row["weekly_cagr_pct"], row["original_cagr_pct"])}
        for row in completed
    ]
    lines = [
        "# Weekly entry / weekly exit experiment",
        "",
        "Frequency-only causal experiment. Ranking, top_n, exit threshold, filters, costs and universe remain inherited.",
        "",
        f"- Strategies selected: {len(rows)}",
        f"- Completed/reused weekly runs: {len(completed)}",
        f"- Skipped/failed: {len(rows) - len(completed)}",
        "- Governance: no promotion; current_parent/current_baseline untouched.",
        "- Decision must use net post-cost results; weekly frequency is not assumed better.",
        "",
    ]
    lines += ranking_section(
        "Top 10 weekly por CAGR",
        ranked_rows(completed, "weekly_cagr_pct", reverse=True),
        "weekly_cagr_pct",
    )
    lines += ranking_section(
        "Top 10 weekly por menor drawdown",
        ranked_rows(completed, "weekly_max_drawdown_pct", reverse=True),
        "weekly_max_drawdown_pct",
    )
    lines += ranking_section(
        "Top 10 mejores weekly vs original por mejora de drawdown",
        ranked_rows(completed, "dd_delta_vs_original", reverse=True),
        "dd_delta_vs_original",
    )
    lines += ranking_section(
        "Top 10 mejores weekly vs original por CAGR delta",
        ranked_rows(cagr_deltas, "cagr_delta_vs_original", reverse=True),
        "cagr_delta_vs_original",
    )
    lines += ranking_section(
        "Peores 10 por caída de CAGR",
        ranked_rows(cagr_deltas, "cagr_delta_vs_original", reverse=False),
        "cagr_delta_vs_original",
    )
    lines += ranking_section(
        "Peores 10 por aumento de trades",
        ranked_rows(completed, "trade_delta", reverse=True),
        "trade_delta",
    )
    promising = sum(
        1
        for row in cagr_deltas
        if optional_float(row.get("cagr_delta_vs_original")) is not None
        and optional_float(row["cagr_delta_vs_original"]) >= 0
        and optional_float(row.get("trade_multiplier")) is not None
        and optional_float(row["trade_multiplier"]) <= 1.5
    )
    lines += [
        "## Conclusión",
        "",
        (
            f"Weekly parece prometedor en {promising}/{len(completed)} casos con "
            "CAGR no inferior y trade multiplier <= 1.5."
            if completed
            else "Sin corridas weekly completas suficientes para concluir."
        ),
        "Turnover alto, costos acumulados y whipsaw son riesgos principales. Revisar cada fila neta post-costos antes de cualquier promoción.",
        "",
    ]
    (report_dir / "weekly_entry_exit_summary.md").write_text(
        "\n".join(lines), encoding="utf-8"
    )


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=str(ROOT))
    parser.add_argument(
        "--source", choices=("runs", "registry", "both"), default="runs"
    )
    parser.add_argument("--strategy-id", action="append", default=[])
    parser.add_argument("--max-strategies", type=int, default=0)
    parser.add_argument("--generate-only", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument(
        "--execution-backend",
        choices=("subprocess", "inprocess"),
        default="subprocess",
    )
    parser.add_argument(
        "--report-dir", default="reports/weekly_entry_exit_experiment"
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.workers < 1:
        raise ValueError("--workers must be at least 1")
    if args.execution_backend == "inprocess" and args.workers != 1:
        raise ValueError(
            "--execution-backend inprocess currently requires --workers 1"
        )
    root = Path(args.repo_root).resolve()
    report_dir = Path(args.report_dir)
    if not report_dir.is_absolute():
        report_dir = root / report_dir
    generated_dir = root / "configs" / "generated" / "weekly_entry_exit"
    generated_dir.mkdir(parents=True, exist_ok=True)
    candidates = select_candidates(root, args.source)
    if args.strategy_id:
        wanted = set(args.strategy_id)
        candidates = [row for row in candidates if row["strategy_id"] in wanted]
    if args.max_strategies:
        candidates = candidates[: args.max_strategies]
    project_path = root / "configs" / "project_config.json"
    project = read_json(project_path, {}) or {}
    weekly_file, daily_folder = resolve_data_paths(root, project)
    rows = []
    if args.execution_backend == "inprocess":
        weekly_df = load_weekly_feature_store(weekly_file)
        daily_df = load_daily_feature_store_folder(daily_folder)
        for candidate in candidates:
            rows.append(
                process_candidate(
                    root,
                    weekly_file,
                    daily_folder,
                    project_path,
                    generated_dir,
                    candidate,
                    generate_only=args.generate_only,
                    resume=args.resume,
                    force=args.force,
                    execution_backend=args.execution_backend,
                    weekly_df=weekly_df,
                    daily_df=daily_df,
                    project_config=project,
                )
            )
            if len(rows) % REPORT_CHECKPOINT_EVERY == 0:
                write_report(report_dir, rows)
    else:
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = [
                executor.submit(
                    process_candidate,
                    root,
                    weekly_file,
                    daily_folder,
                    project_path,
                    generated_dir,
                    candidate,
                    generate_only=args.generate_only,
                    resume=args.resume,
                    force=args.force,
                    execution_backend=args.execution_backend,
                )
                for candidate in candidates
            ]
            for future in as_completed(futures):
                rows.append(future.result())
                if len(rows) % REPORT_CHECKPOINT_EVERY == 0:
                    write_report(report_dir, rows)
    write_report(report_dir, rows)
    print(f"Source: {args.source}")
    print(f"Selected: {len(rows)}")
    print(f"Completed/reused: {sum(row['status'] in {'completed', 'reused'} for row in rows)}")
    print(f"Report: {report_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
