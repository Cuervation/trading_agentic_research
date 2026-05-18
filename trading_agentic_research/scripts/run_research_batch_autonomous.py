"""Autonomous wrapper around run_research_batch.py.

Use this entrypoint for long-running autonomous research. It protects the loop
from common failure modes:
- placeholder or missing data paths;
- missing parent/champion config;
- exhausted hypothesis bank;
- local factory exhaustion;
- unsupported literature ideas due to missing features;
- silent no-op batches.

Exit codes:
0 = batch launched and finished according to run_research_batch.py
2 = data preflight failed
3 = no eligible hypotheses after all fallbacks
4 = parent config missing/unusable
5 = batch subprocess failed
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.research.autonomy_blocker import clear_autonomy_blocker, write_autonomy_blocker
from scripts.research.autonomous_hypothesis_factory import generate_value_hypotheses
from scripts.research.data_path_resolver import resolve_data_paths
from scripts.research.hypothesis_eligibility import eligible_hypothesis_preflight
from scripts.research.literature_hypothesis_miner import mine_literature_hypotheses
from scripts.research.parent_state import resolve_current_parent_config_path, sync_current_parent_state
from scripts.research.sync_strategy_registry import sync_strategy_registry


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--max-runs", type=int, default=5)
    p.add_argument("--weekly-file", default=None)
    p.add_argument("--daily-folder", default=None)
    p.add_argument("--project-config", default="configs/project_config.json")
    p.add_argument("--strategy-registry", default="configs/strategy_registry.json")
    p.add_argument("--hypothesis-bank", default="bibliography/hypothesis_bank.jsonl")
    p.add_argument("--state-dir", default="state")
    p.add_argument("--runs-dir", default="runs")
    p.add_argument("--reports-dir", default="reports")
    p.add_argument("--generated-configs-dir", default="configs/generated")
    p.add_argument("--generation-families", default="time_series_momentum_refinement,risk_control_refinement,quality_momentum,trend_following,can_slim,paper_time_series_momentum,paper_quality_momentum,paper_regime_filter")
    p.add_argument("--max-value-hypotheses", type=int, default=8)
    p.add_argument("--max-literature-hypotheses", type=int, default=8)
    p.add_argument("--max-repeats-per-hypothesis", type=int, default=1)
    p.add_argument("--allow-parent-update", action="store_true")
    p.add_argument("--no-literature-fallback", action="store_true")
    return p.parse_args()


def _print_candidates(label: str, values: list[str]) -> None:
    if not values:
        return
    print(label)
    for item in values[:5]:
        print(f"  - {item}")


def _eligibility(args: argparse.Namespace) -> dict[str, Any]:
    return eligible_hypothesis_preflight(
        hypothesis_bank=args.hypothesis_bank,
        state_dir=args.state_dir,
        prefer_unseen=True,
        max_repeats_per_hypothesis=args.max_repeats_per_hypothesis,
    )


def main() -> int:
    args = parse_args()

    data = resolve_data_paths(
        weekly_file=args.weekly_file,
        daily_folder=args.daily_folder,
        project_config=args.project_config,
        repo_root=ROOT,
        state_dir=args.state_dir,
        persist=True,
    )
    for warning in data.warnings:
        print(f"Data preflight warning: {warning}")
    if not data.can_run:
        print("Data preflight failed; no backtest will be launched.")
        for error in data.errors:
            print(f"- {error}")
        _print_candidates("Weekly candidates:", data.candidates.get("weekly_files", []))
        _print_candidates("Daily folder candidates:", data.candidates.get("daily_folders", []))
        write_autonomy_blocker(
            state_dir=args.state_dir,
            reason="missing_or_invalid_data_paths",
            errors=data.errors,
            warnings=data.warnings,
            next_action="Set configs/local_data_paths.json, env vars TRADING_WEEKLY_FILE/TRADING_DAILY_FOLDER, or pass --weekly-file/--daily-folder.",
            context=data.to_dict(),
        )
        return 2

    sync_current_parent_state(
        state_dir=args.state_dir,
        strategy_registry_path=args.strategy_registry,
        generated_configs_dir=args.generated_configs_dir,
        prefer_best_champion=True,
        repo_root=ROOT,
    )
    sync_strategy_registry(registry_path=args.strategy_registry, state_dir=args.state_dir, repo_root=ROOT)

    parent_config = resolve_current_parent_config_path(
        state_dir=args.state_dir,
        strategy_registry_path=args.strategy_registry,
        generated_configs_dir=args.generated_configs_dir,
        explicit_parent_strategy_config=None,
        fallback="configs/baseline_momentum_trend_v1.json",
        repo_root=ROOT,
    )
    if not parent_config or not (ROOT / parent_config).exists():
        write_autonomy_blocker(
            state_dir=args.state_dir,
            reason="missing_parent_config",
            errors=[f"Resolved parent config is missing: {parent_config}"],
            next_action="Restore or commit the current parent config, then rerun sync_parent_state.py.",
            context={"parent_config": parent_config},
        )
        print(f"Parent config preflight failed: {parent_config}")
        return 4

    eligibility_before = _eligibility(args)
    print(f"Hypothesis eligibility preflight: {eligibility_before}")

    generated = {"generated": 0, "reason": "not_needed_existing_eligible"}
    literature = {"generated": 0, "reason": "not_needed_existing_eligible"}

    if not eligibility_before.get("eligible"):
        generated = generate_value_hypotheses(
            parent_strategy_config_path=parent_config,
            hypothesis_bank_path=args.hypothesis_bank,
            state_dir=args.state_dir,
            max_new=args.max_value_hypotheses,
            reason="autonomous_batch_preflight_no_eligible",
        )
        print(f"Value-hypothesis fallback preflight: {generated}")

    eligibility_after_value = _eligibility(args)
    print(f"Eligibility after value fallback: {eligibility_after_value}")

    if not eligibility_after_value.get("eligible") and not args.no_literature_fallback:
        literature = mine_literature_hypotheses(
            parent_strategy_config_path=parent_config,
            hypothesis_bank_path=args.hypothesis_bank,
            state_dir=args.state_dir,
            max_new=args.max_literature_hypotheses,
        )
        print(f"Literature-hypothesis fallback preflight: {literature}")

    final_eligibility = _eligibility(args)
    print(f"Final hypothesis eligibility preflight: {final_eligibility}")

    if not final_eligibility.get("eligible"):
        write_autonomy_blocker(
            state_dir=args.state_dir,
            reason="no_eligible_hypotheses_after_fallbacks",
            errors=[str(final_eligibility.get("reason"))],
            warnings=[],
            next_action="Review state/missing_feature_tasks.jsonl, add new feature engineering tasks, or broaden literature templates.",
            context={
                "eligibility_before": eligibility_before,
                "value_factory": generated,
                "literature_miner": literature,
                "final_eligibility": final_eligibility,
            },
        )
        print("No eligible hypotheses after all fallbacks; no batch will be launched.")
        return 3

    clear_autonomy_blocker(state_dir=args.state_dir, reason="autonomous_preflight_passed")

    cmd = [
        sys.executable,
        "scripts/run_research_batch.py",
        "--max-runs", str(args.max_runs),
        "--weekly-file", str(data.weekly_file),
        "--daily-folder", str(data.daily_folder),
        "--project-config", args.project_config,
        "--strategy-registry", args.strategy_registry,
        "--hypothesis-bank", args.hypothesis_bank,
        "--state-dir", args.state_dir,
        "--runs-dir", args.runs_dir,
        "--reports-dir", args.reports_dir,
        "--prefer-unseen",
        "--auto-generate-missing-configs",
        "--auto-generate-hypotheses-on-block",
        "--generation-families", args.generation_families,
        "--max-generation-attempts", "3",
        "--max-repeats-per-hypothesis", str(args.max_repeats_per_hypothesis),
        "--parent-strategy-config", parent_config,
    ]
    if args.allow_parent_update:
        cmd.append("--allow-parent-update")
    print("Launching:", " ".join(cmd))
    result = subprocess.run(cmd, cwd=ROOT, check=False)
    if result.returncode != 0:
        write_autonomy_blocker(
            state_dir=args.state_dir,
            reason="research_batch_failed",
            errors=[f"run_research_batch.py exited with code {result.returncode}"],
            next_action="Inspect state/research_state.json and the latest run folder; fix operational issue before continuing.",
            context={"command": cmd, "returncode": result.returncode},
        )
        return 5
    clear_autonomy_blocker(state_dir=args.state_dir, reason="batch_completed_or_stopped_cleanly")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
