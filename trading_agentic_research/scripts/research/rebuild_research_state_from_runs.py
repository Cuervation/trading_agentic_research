"""Rebuild continuous-learning state from existing EXP_*/AUTO_* runs.

Run from repo root:
  python scripts/research/rebuild_research_state_from_runs.py --runs-dir runs --state-dir state --reports-dir reports

It reconstructs:
- state/artifact_hash_index.json
- state/duplicate_runs.json
- state/research_ledger.jsonl
- state/champion_runs.json
- state/current_parent.json
- reports/rebuilt_research_state.md
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.research.artifact_index import (
    apply_duplicate_to_audit,
    iter_run_dirs,
    rebuild_artifact_index_from_runs,
    read_json,
    write_json,
)
from scripts.research.champion_governance import update_champion_state, load_champion_state
from scripts.research.parent_state import sync_current_parent_state
from scripts.research.research_ledger import append_run_to_ledger, read_ledger

try:
    from backtester.validation import audit_run_folder
except Exception:  # pragma: no cover - keep script usable for partial repos
    audit_run_folder = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Rebuild research-learning state from run artifacts.")
    parser.add_argument("--runs-dir", default="runs")
    parser.add_argument("--state-dir", default="state")
    parser.add_argument("--reports-dir", default="reports")
    parser.add_argument("--strategy-registry", default="configs/strategy_registry.json")
    parser.add_argument("--generated-configs-dir", default="configs/generated")
    parser.add_argument("--write-audits", action="store_true", help="Write missing/rebuilt audit.json files into run folders.")
    parser.add_argument(
        "--preserve-current-parent",
        action="store_true",
        help="Keep existing champion_runs.current_parent_run_id instead of resetting it to best_champion_run_id after rebuild.",
    )
    return parser.parse_args()


def _audit_for_run(run_dir: Path, runs_dir: Path) -> dict[str, Any]:
    audit_path = run_dir / "audit.json"
    if audit_path.exists():
        return read_json(audit_path, {}) or {}
    if audit_run_folder is None:
        return {"decision": "review", "reasons": ["audit_missing_and_validation_unavailable"], "flags": []}

    manifest = read_json(run_dir / "run_manifest.json", {}) or {}
    parent_run_id = manifest.get("parent_run_id")
    parent_dir = runs_dir / str(parent_run_id) if parent_run_id else None
    try:
        return audit_run_folder(run_dir, parent_run_dir=parent_dir if parent_dir and parent_dir.exists() else None)
    except Exception as exc:
        return {"decision": "review", "reasons": [f"audit_rebuild_failed:{exc}"], "flags": []}


def _reset_state_files(state_dir: Path) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "research_ledger.jsonl").write_text("", encoding="utf-8")
    write_json(
        state_dir / "champion_runs.json",
        {
            "version": 2,
            "best_champion_run_id": None,
            "current_parent_run_id": None,
            "current_parent_strategy_id": None,
            "current_parent_hypothesis_id": None,
            "current_parent_config_path": None,
            "aggressive_champion_run_id": None,
            "baseline_candidate_run_id": None,
            "promotion_candidates": [],
            "secondary_candidates": [],
            "defensive_secondary_candidates": [],
            "champion_runs": [],
        },
    )


def _index_duplicate_map(state_dir: Path) -> dict[str, dict[str, Any]]:
    index = read_json(state_dir / "artifact_hash_index.json", {}) or {}
    return index.get("runs", {}) or {}


def _build_report(*, runs: list[Path], state_dir: Path, duplicates: list[dict[str, Any]]) -> str:
    ledger = read_ledger(state_dir)
    champion = load_champion_state(state_dir)
    current_parent = read_json(state_dir / "current_parent.json", {}) or {}
    unique = len({row.get("artifact_signature") for row in ledger if row.get("artifact_signature")})
    value_counts: dict[str, int] = {}
    for row in ledger:
        value_counts[str(row.get("value_delivered"))] = value_counts.get(str(row.get("value_delivered")), 0) + 1

    top_rows = sorted(
        [row for row in ledger if row.get("metrics")],
        key=lambda row: float((row.get("metrics") or {}).get("strategy_cagr_pct", 0.0)),
        reverse=True,
    )[:15]

    lines = [
        "# Rebuilt Research State",
        "",
        f"- Runs scanned: {len(runs)}",
        f"- Unique artifact signatures in ledger: {unique}",
        f"- Duplicate runs detected: {len(duplicates)}",
        f"- Best champion: `{champion.get('best_champion_run_id')}`",
        f"- Current parent: `{champion.get('current_parent_run_id')}`",
        f"- Current parent strategy: `{current_parent.get('current_parent_strategy_id')}`",
        f"- Current parent config: `{current_parent.get('current_parent_config_path')}`",
        f"- Aggressive champion: `{champion.get('aggressive_champion_run_id')}`",
        f"- Baseline/promotion candidate: `{champion.get('baseline_candidate_run_id')}`",
        "",
        "## Value delivered counts",
        "",
    ]
    for key, count in sorted(value_counts.items()):
        lines.append(f"- {key}: {count}")

    lines.extend(["", "## Top CAGR runs", "", "| run | value | CAGR | DD | years SPY | months SPY | trades |", "|---|---|---:|---:|---:|---:|---:|"])
    for row in top_rows:
        m = row.get("metrics") or {}
        lines.append(
            f"| {row.get('run_id')} | {row.get('value_delivered')} | {float(m.get('strategy_cagr_pct', 0.0)):.2f}% | "
            f"{float(m.get('strategy_max_drawdown_pct', 0.0)):.2f}% | {m.get('years_beating_spy')}/{m.get('years_losing_to_spy')} | "
            f"{m.get('months_beating_spy')}/{m.get('months_losing_to_spy')} | {m.get('trades')} |"
        )

    lines.extend(["", "## Duplicate examples", "", "| run | duplicate_of |", "|---|---|"])
    for row in duplicates[:50]:
        lines.append(f"| {row.get('run_id')} | {row.get('duplicate_of_run_id')} |")
    return "\n".join(lines) + "\n"


def main() -> int:
    args = parse_args()
    runs_dir = Path(args.runs_dir)
    state_dir = Path(args.state_dir)
    reports_dir = Path(args.reports_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)

    runs = iter_run_dirs(runs_dir)
    _reset_state_files(state_dir)

    rebuild = rebuild_artifact_index_from_runs(runs_dir, state_dir)
    duplicates = rebuild["duplicates"]
    duplicate_by_run = _index_duplicate_map(state_dir)

    for run_dir in runs:
        audit = _audit_for_run(run_dir, runs_dir)
        duplicate_record = duplicate_by_run.get(run_dir.name, {})
        duplicate_info = {
            "is_duplicate": bool(duplicate_record.get("is_duplicate")),
            "duplicate_of_run_id": duplicate_record.get("duplicate_of_run_id"),
            "duplicate_signature": duplicate_record.get("artifact_signature"),
        }
        if duplicate_info["is_duplicate"]:
            audit = apply_duplicate_to_audit(audit, duplicate_info)
        if args.write_audits:
            write_json(run_dir / "audit.json", audit)

        champion_decision = update_champion_state(
            run_dir=run_dir,
            state_dir=state_dir,
            audit=audit,
            duplicate_info=duplicate_info,
            allow_parent_move=False,
        )
        append_run_to_ledger(
            run_dir=run_dir,
            state_dir=state_dir,
            audit=audit,
            duplicate_info=duplicate_info,
            champion_decision=champion_decision,
        )

    parent_payload = sync_current_parent_state(
        state_dir=state_dir,
        strategy_registry_path=args.strategy_registry,
        generated_configs_dir=args.generated_configs_dir,
        prefer_best_champion=not bool(args.preserve_current_parent),
        repo_root=ROOT,
    )

    report = _build_report(runs=runs, state_dir=state_dir, duplicates=duplicates)
    report_path = reports_dir / "rebuilt_research_state.md"
    report_path.write_text(report, encoding="utf-8")

    print(f"Runs scanned: {len(runs)}")
    print(f"Duplicates: {len(duplicates)}")
    print(f"Current parent: {parent_payload.get('current_parent_run_id')}")
    print(f"Parent config: {parent_payload.get('current_parent_config_path')}")
    print(f"Report: {report_path}")
    print(f"Artifact index: {state_dir / 'artifact_hash_index.json'}")
    print(f"Ledger: {state_dir / 'research_ledger.jsonl'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
