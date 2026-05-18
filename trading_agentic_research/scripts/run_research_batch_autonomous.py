"""Autonomous wrapper around run_research_batch.py.

Use this entrypoint for long-running autonomous research. It protects the loop
from common failure modes:
- placeholder or missing data paths;
- missing parent/champion config;
- exhausted hypothesis bank;
- local factory exhaustion;
- unsupported literature ideas due to missing features;
- silent no-op batches;
- post-batch zero-iteration false success;
- empty paper-idea library when literature fallback is needed.

Exit codes:
0 = batch launched and completed at least one iteration, or max-runs reached cleanly
2 = data preflight failed
3 = no eligible hypotheses after all fallbacks, or batch completed zero iterations
4 = parent config missing/unusable
5 = batch subprocess failed
6 = research policy violation / manual review required
"""
from __future__ import annotations

import argparse
import json
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
from scripts.research.paper_searcher import generate_paper_ideas
from scripts.research.parent_state import resolve_current_parent_config_path, sync_current_parent_state
from scripts.research.research_policy import load_research_policy, validate_autonomous_launch, validate_post_batch
from scripts.research.sync_strategy_registry import sync_strategy_registry


def read_json(path: str | Path, default: Any = None) -> Any:
    p = Path(path)
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return default


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--max-runs", type=int, default=5)
    p.add_argument("--weekly-file", default=None)
    p.add_argument("--daily-folder", default=None)
    p.add_argument("--project-config", default="configs/project_config.json")
    p.add_argument("--strategy-registry", default="configs/strategy_registry.json")
    p.add_argument("--hypothesis-bank", default="bibliography/hypothesis_bank.jsonl")
    p.add_argument("--paper-ideas", default="bibliography/paper_ideas.jsonl")
    p.add_argument("--state-dir", default="state")
    p.add_argument("--runs-dir", default="runs")
    p.add_argument("--reports-dir", default="reports")
    p.add_argument("--generated-configs-dir", default="configs/generated")
    p.add_argument("--generation-families", default="time_series_momentum_refinement,risk_control_refinement,quality_momentum,trend_following,can_slim,paper_time_series_momentum,paper_quality_momentum,paper_regime_filter")
    p.add_argument("--max-value-hypotheses", type=int, default=8)
    p.add_argument("--max-literature-hypotheses", type=int, default=8)
    p.add_argument("--max-paper-ideas", type=int, default=5)
    p.add_argument("--max-repeats-per-hypothesis", type=int, default=1)
    p.add_argument("--allow-parent-update", action="store_true")
    p.add_argument("--no-literature-fallback", action="store_true")
    p.add_argument("--no-paper-searcher-fallback", action="store_true")
    p.add_argument("--online-paper-search", action="store_true", help="Optional best-effort Semantic Scholar search when offline paper ideas are exhausted.")
    p.add_argument("--policy", default="governance/research_policy.json")
    p.add_argument("--allow-zero-iterations", action="store_true", help="Development-only escape hatch; production autonomous runs should not use this.")
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


def _load_batch_state(state_dir: str | Path) -> dict[str, Any]:
    return read_json(Path(state_dir) / "batch_state.json", {}) or {}


def _paper_ideas_nonempty(path: str | Path) -> bool:
    p = Path(path)
    if not p.is_absolute():
        p = ROOT / p
    return p.exists() and p.stat().st_size > 0


def _mine_literature(args: argparse.Namespace, parent_config: str) -> dict[str, Any]:
    return mine_literature_hypotheses(
        parent_strategy_config_path=parent_config,
        hypothesis_bank_path=args.hypothesis_bank,
        state_dir=args.state_dir,
        max_new=args.max_literature_hypotheses,
        paper_ideas_path=args.paper_ideas,
    )


def main() -> int:
    args = parse_args()
    policy = load_research_policy(args.policy, repo_root=ROOT)

    launch_policy = validate_autonomous_launch(
        policy=policy,
        allow_parent_update=bool(args.allow_parent_update),
        max_runs=int(args.max_runs),
    )
    if not launch_policy["ok"]:
        write_autonomy_blocker(
            state_dir=args.state_dir,
            reason="research_policy_violation",
            errors=launch_policy["errors"],
            warnings=launch_policy.get("warnings", []),
            next_action=launch_policy.get("next_action", "Review governance/research_policy.json or run with a safer configuration."),
            context=launch_policy,
        )
        print("Research policy blocked autonomous launch:")
        for error in launch_policy["errors"]:
            print(f"- {error}")
        return 6

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
    paper_search = {"rows_written": 0, "reason": "not_needed_existing_eligible"}

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
        literature = _mine_literature(args, parent_config)
        print(f"Literature-hypothesis fallback preflight: {literature}")

    eligibility_after_literature = _eligibility(args)
    print(f"Eligibility after literature fallback: {eligibility_after_literature}")

    if (
        not eligibility_after_literature.get("eligible")
        and not args.no_literature_fallback
        and not args.no_paper_searcher_fallback
    ):
        paper_search = generate_paper_ideas(
            output=args.paper_ideas,
            online=bool(args.online_paper_search),
            limit=int(args.max_paper_ideas),
        )
        print(f"Paper-searcher fallback: {paper_search}")

        literature = _mine_literature(args, parent_config)
        print(f"Literature-hypothesis fallback after paper search: {literature}")

    final_eligibility = _eligibility(args)
    print(f"Final hypothesis eligibility preflight: {final_eligibility}")

    if not final_eligibility.get("eligible"):
        write_autonomy_blocker(
            state_dir=args.state_dir,
            reason="no_eligible_hypotheses_after_fallbacks",
            errors=[str(final_eligibility.get("reason"))],
            warnings=[],
            next_action="Review state/missing_feature_tasks.jsonl, run feature_engineering_agent.py, add new paper ideas, or broaden literature templates.",
            context={
                "eligibility_before": eligibility_before,
                "value_factory": generated,
                "literature_miner": literature,
                "paper_searcher": paper_search,
                "final_eligibility": final_eligibility,
                "paper_ideas_nonempty": _paper_ideas_nonempty(args.paper_ideas),
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

    batch_state = _load_batch_state(args.state_dir)
    post = validate_post_batch(
        policy=policy,
        batch_state=batch_state,
        allow_zero_iterations=bool(args.allow_zero_iterations),
        requested_max_runs=int(args.max_runs),
    )
    if not post["ok"]:
        write_autonomy_blocker(
            state_dir=args.state_dir,
            reason=post.get("reason", "post_batch_validation_failed"),
            errors=post.get("errors", []),
            warnings=post.get("warnings", []),
            next_action=post.get("next_action", "Inspect state/batch_state.json and hypothesis eligibility."),
            context={"batch_state": batch_state, "post_batch_validation": post},
        )
        print("Post-batch validation failed:")
        for error in post.get("errors", []):
            print(f"- {error}")
        return 3

    clear_autonomy_blocker(state_dir=args.state_dir, reason="batch_completed_with_value")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
