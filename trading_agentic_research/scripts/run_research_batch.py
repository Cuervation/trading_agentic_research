"""Run multiple research-loop iterations with safe stop rules."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.select_next_hypothesis import choose_next_hypothesis, load_hypothesis_bank, read_json, read_jsonl
from scripts.generate_strategy_config import generate_strategy_config_from_hypothesis, upsert_strategy_registry
from scripts.parameter_effect_memory import load_parameter_effect_memory
from scripts.research.consumed_hypotheses import consumed_hypothesis_ids
from scripts.research.feature_space_expansion_factory import generate_feature_space_hypotheses
from scripts.research.generation_feedback import maybe_mark_candidate_review_exhausted
from scripts.research.generation_selection_feedback import (
    diagnose_generated_hypotheses,
    record_generation_selection_feedback,
)
from scripts.research.parent_state import resolve_current_parent_config_path, sync_current_parent_state
from scripts.research.cooldown_governance import hard_active_cooldown_family_names


def resolve_strategy_config_for_hypothesis(hypothesis: dict, strategy_registry_path: str | Path) -> str:
    """Resolve strategy config path for a selected hypothesis with strict 1:1 mapping."""
    registry = read_json(strategy_registry_path)
    strategies = registry.get("strategies", [])
    hypothesis_id = hypothesis.get("hypothesis_id")

    matches: list[str] = []
    for row in strategies:
        config_path = row.get("config_path")
        if not config_path:
            continue
        p = Path(config_path)
        if not p.is_absolute():
            p = ROOT / p
        if not p.exists():
            continue

        cfg = read_json(p)
        if str(cfg.get("hypothesis_id", "")) == str(hypothesis_id):
            matches.append(str(p))

    if not matches:
        raise ValueError(f"No strict strategy config mapping found for hypothesis_id={hypothesis_id}.")
    if len(matches) > 1:
        raise ValueError(f"Multiple configs mapped to hypothesis_id={hypothesis_id}: {matches}")
    return matches[0]


def generate_missing_strategy_config(
    *,
    hypothesis: dict,
    parent_strategy_config_path: str | Path,
    output_config_path: str | Path,
    strategy_registry_path: str | Path,
    notes: str,
) -> str:
    parent_cfg = read_json(parent_strategy_config_path)
    generated = generate_strategy_config_from_hypothesis(hypothesis=hypothesis, parent_strategy_config=parent_cfg)
    Path(output_config_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_config_path).write_text(
        json.dumps(generated, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    upsert_strategy_registry(
        registry_path=strategy_registry_path,
        strategy_id=str(generated.get("strategy_id")),
        config_path=str(Path(output_config_path).as_posix()),
        strategy_family=str(generated.get("strategy_family")),
        status="candidate",
        notes=notes,
    )
    return str(Path(output_config_path))


def get_latest_run_id(runs_dir: str | Path = "runs") -> str | None:
    run_paths = [p for p in Path(runs_dir).glob("EXP_*") if p.is_dir()]
    run_paths.extend([p for p in Path(runs_dir).glob("AUTO_*") if p.is_dir()])
    if not run_paths:
        return None
    run_paths.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return run_paths[0].name


def _run_command(command: list[str]) -> int:
    result = subprocess.run(command, cwd=ROOT, check=False)
    return int(result.returncode)


def _run_generation_command(command: list[str]) -> int:
    result = subprocess.run(command, cwd=ROOT, check=False)
    return int(result.returncode)


def _generated_count(result: dict[str, Any] | bool | None) -> int:
    if isinstance(result, bool):
        return 1 if result else 0
    if not isinstance(result, dict):
        return 0
    for key in ("generated", "rows_written"):
        if key in result:
            try:
                return int(result.get(key) or 0)
            except (TypeError, ValueError):
                return 0
    return 0


def run_candidate_generation(
    *,
    family: str,
    families: str | None,
    args: argparse.Namespace,
    parent_strategy_config: str,
    reason: str,
    runner=_run_generation_command,
) -> bool:
    """Run legacy generator and return True only if the bank actually grew."""
    before_count = len(read_jsonl(args.hypothesis_bank))
    command = [
        sys.executable,
        "scripts/generate_candidates_from_parent.py",
        "--state-dir",
        args.state_dir,
        "--strategy-registry",
        args.strategy_registry,
        "--parent-strategy-config",
        parent_strategy_config,
        "--evidence-memory",
        str(Path(args.state_dir) / "evidence_memory.json"),
        "--hypothesis-bank",
        args.hypothesis_bank,
        "--cooldowns",
        str(Path(args.state_dir) / "subspace_cooldowns.json"),
        "--family",
        family,
    ]
    if families:
        command.extend(["--families", families])
    code = runner(command)
    after_count = len(read_jsonl(args.hypothesis_bank))
    if code == 0 and after_count > before_count:
        print(f"Generated {after_count - before_count} new hypotheses for family={family} (reason={reason}, parent_config={parent_strategy_config}).")
        return True
    if code == 0:
        print(f"Hypothesis generator produced no new rows for family={family} (reason={reason}, parent_config={parent_strategy_config}).")
        return False
    print(f"Hypothesis generation failed for family={family} (reason={reason}, parent_config={parent_strategy_config}).")
    return False


def run_feature_space_generation(
    *,
    args: argparse.Namespace,
    parent_strategy_config: str,
    reason: str,
) -> dict[str, Any]:
    result = generate_feature_space_hypotheses(
        parent_strategy_config_path=parent_strategy_config,
        hypothesis_bank_path=args.hypothesis_bank,
        state_dir=args.state_dir,
        max_new=5,
        reason=reason,
    )
    print(f"In-batch feature-space fallback: {result}")
    _record_generation_selection_feedback_if_any(
        args=args,
        phase=f"feature_space:{reason}",
        generation_result=result,
        context={"parent_strategy_config": parent_strategy_config},
    )
    return result


def _record_generation_selection_feedback_if_any(
    *,
    args: argparse.Namespace,
    phase: str,
    generation_result: dict[str, Any],
    context: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    ids = [str(x) for x in (generation_result.get("hypotheses") or []) if x]
    if not ids:
        return None
    diagnosis = diagnose_generated_hypotheses(
        hypothesis_bank_path=args.hypothesis_bank,
        state_dir=args.state_dir,
        hypothesis_ids=ids,
        max_repeats_per_hypothesis=args.max_repeats_per_hypothesis,
    )
    event = record_generation_selection_feedback(
        state_dir=args.state_dir,
        reports_dir=args.reports_dir,
        phase=phase,
        generation_result=generation_result,
        diagnosis=diagnosis,
        context=context or {},
    )
    print(
        "Generation-selection feedback:",
        f"phase={phase}",
        f"generated={event.get('generated')}",
        f"selectable={event.get('selectable_count')}",
        f"reasons={event.get('summary_by_reason')}",
    )
    return event


def _batch_state_path(state_dir: str | Path) -> Path:
    return Path(state_dir) / "batch_state.json"


def _load_batch_state(state_dir: str | Path, max_runs: int) -> dict:
    path = _batch_state_path(state_dir)
    if not path.exists():
        return {
            "version": 1,
            "status": "initialized",
            "max_runs": max_runs,
            "completed": 0,
            "consecutive_rejections": 0,
            "history": [],
            "recovery_cycles": 0,
            "recovery_history": [],
            "last_updated_at": datetime.now(timezone.utc).isoformat(),
        }
    return read_json(path)


def _save_batch_state(state_dir: str | Path, state: dict) -> None:
    state["last_updated_at"] = datetime.now(timezone.utc).isoformat()
    _batch_state_path(state_dir).parent.mkdir(parents=True, exist_ok=True)
    _batch_state_path(state_dir).write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def _latest_learning_flags(state_dir: str | Path) -> list[str]:
    learning = read_json(Path(state_dir) / "learning_memory.json")
    events = learning.get("learning_events", []) if isinstance(learning, dict) else []
    if not events:
        return []
    last = events[-1]
    flags = last.get("flags", [])
    return [str(x) for x in flags] if isinstance(flags, list) else []


def _cooldown_families(cooldowns: dict) -> set[str]:
    """Return only hard-active cooldown families from an already-loaded cooldown payload.

    Soft/legacy cooldowns are advisory. They should influence diagnostics and
    learning, but they must not make the batch think every candidate family is
    blocked.
    """
    return hard_active_cooldown_family_names(cooldowns)


def add_family_cooldown(
    *,
    state_dir: str | Path,
    family: str,
    reason: str,
    hypothesis_id: str | None = None,
    days: int = 7,
) -> dict:
    path = Path(state_dir) / "subspace_cooldowns.json"
    cooldowns = read_json(path) if path.exists() else {"version": 1, "cooldowns": {}, "default_failure_threshold": 3}
    now = datetime.now(timezone.utc)
    cooldowns.setdefault("cooldowns", {})[family] = {
        "reason": reason,
        "hypothesis_id": hypothesis_id,
        "cooldown_started_at": now.isoformat(),
        "cooldown_until": (now + timedelta(days=days)).isoformat(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cooldowns, indent=2, ensure_ascii=False), encoding="utf-8")
    return cooldowns


def _repeat_blocked_hypothesis_ids(history: list[dict], max_repeats_per_hypothesis: int) -> set[str]:
    counts = Counter(str(item.get("hypothesis_id")) for item in history if item.get("hypothesis_id"))
    return {hypothesis_id for hypothesis_id, count in counts.items() if count >= max_repeats_per_hypothesis}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a batch of research-loop iterations.")
    parser.add_argument("--max-runs", type=int, default=20)
    parser.add_argument("--weekly-file", required=True)
    parser.add_argument("--daily-folder", required=True)
    parser.add_argument("--project-config", default="configs/project_config.json")
    parser.add_argument("--strategy-registry", default="configs/strategy_registry.json")
    parser.add_argument("--hypothesis-bank", default="bibliography/hypothesis_bank.jsonl")
    parser.add_argument("--state-dir", default="state")
    parser.add_argument("--runs-dir", default="runs")
    parser.add_argument("--reports-dir", default="reports")
    parser.add_argument("--prefer-unseen", action="store_true")
    parser.add_argument("--allow-parent-update", action="store_true")
    parser.add_argument(
        "--evaluation-mode",
        choices=["standard", "dd_first"],
        default="standard",
        help="Use standard candidate governance or DD_FIRST drawdown-first reporting.",
    )
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--stop-after-consecutive-rejections", type=int, default=2)
    parser.add_argument("--stop-on-metric-no-effect", action="store_true")
    parser.add_argument("--max-repeats-per-hypothesis", type=int, default=1)
    parser.add_argument(
        "--parent-strategy-config",
        default=None,
        help="Parent strategy config for auto-generated candidates. If omitted, uses state/current_parent.json, then falls back to baseline.",
    )
    parser.add_argument(
        "--auto-generate-missing-configs",
        action="store_true",
        help="When no config exists for a hypothesis, generate one from parent + hypothesis.strategy_overrides.",
    )
    parser.add_argument(
        "--generated-configs-dir",
        default="configs/generated",
        help="Where to write auto-generated candidate configs.",
    )
    parser.add_argument(
        "--auto-generate-hypotheses-on-block",
        action="store_true",
        help="When selector gets blocked (no eligible or repetition), generate new hypotheses and retry.",
    )
    parser.add_argument(
        "--generation-family",
        default="cross_sectional_momentum",
        help="Family used by automatic hypothesis generation when blocked.",
    )
    parser.add_argument(
        "--generation-families",
        default="",
        help="Comma-separated families for hypothesis generation (overrides --generation-family when set).",
    )
    parser.add_argument(
        "--max-generation-attempts",
        type=int,
        default=1,
        help="Maximum generation retries per blocked selection point.",
    )
    parser.add_argument(
        "--no-continue-after-recovery-generation",
        action="store_true",
        help="Disable long-run recovery continuation after consecutive rejections generate selectable hypotheses.",
    )
    parser.add_argument(
        "--max-recovery-cycles",
        type=int,
        default=3,
        help="Maximum times a batch may continue after consecutive rejections if recovery generation creates selectable work.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    # Never let the inner batch silently promote the best champion. Parent lock
    # must be enforced both in the autonomous wrapper and here.
    sync_current_parent_state(
        state_dir=args.state_dir,
        strategy_registry_path=args.strategy_registry,
        generated_configs_dir=args.generated_configs_dir,
        prefer_best_champion=False,
        repo_root=ROOT,
    )

    state = _load_batch_state(args.state_dir, args.max_runs)
    if not args.resume:
        state.update(
            {
                "status": "running",
                "max_runs": args.max_runs,
                "completed": 0,
                "consecutive_rejections": 0,
                "history": [],
                "recovery_cycles": 0,
                "recovery_history": [],
                "stop_reason": None,
            }
        )
    else:
        state["status"] = "running"
        state.setdefault("recovery_cycles", 0)
        state.setdefault("recovery_history", [])

    _save_batch_state(args.state_dir, state)

    while state["completed"] < args.max_runs:
        # Close exhausted candidate-review state dynamically before every selection.
        close_result = maybe_mark_candidate_review_exhausted(
            state_dir=args.state_dir,
            hypothesis_bank=args.hypothesis_bank,
            generation_result={"generated": 0, "reason": "batch_selection_preflight"},
        )
        if close_result.get("candidate_review_status") == "review_exhausted":
            print(f"Candidate-under-review exhausted during batch selection: {close_result.get('candidate_review_exhaustion_reason')}")

        learning = read_json(Path(args.state_dir) / "learning_memory.json")
        cooldowns = read_json(Path(args.state_dir) / "subspace_cooldowns.json")
        current_parent = read_json(Path(args.state_dir) / "current_parent.json")
        parameter_effect_memory = load_parameter_effect_memory(Path(args.state_dir) / "parameter_effect_memory.json")
        rejected_ids = {row.get("hypothesis_id") for row in read_jsonl(Path(args.state_dir) / "rejected_hypotheses.jsonl")}
        accepted_ids = {row.get("hypothesis_id") for row in read_jsonl(Path(args.state_dir) / "accepted_hypotheses.jsonl")}
        consumed_ids = consumed_hypothesis_ids(args.state_dir)
        repeat_blocked_ids = _repeat_blocked_hypothesis_ids(state.get("history", []), args.max_repeats_per_hypothesis)

        effective_parent_strategy_config = resolve_current_parent_config_path(
            state_dir=args.state_dir,
            strategy_registry_path=args.strategy_registry,
            generated_configs_dir=args.generated_configs_dir,
            explicit_parent_strategy_config=args.parent_strategy_config,
            fallback="configs/baseline_momentum_trend_v1.json",
            repo_root=ROOT,
        )
        state["effective_parent_strategy_config"] = effective_parent_strategy_config

        families_in_cooldown = _cooldown_families(cooldowns)
        bank = load_hypothesis_bank(args.hypothesis_bank)
        eligible_families = {h.get("family") for h in bank if str(h.get("status", "candidate")) in {"candidate", "seeded"}}
        if eligible_families and eligible_families.issubset(families_in_cooldown):
            generation_result = run_feature_space_generation(
                args=args,
                parent_strategy_config=effective_parent_strategy_config,
                reason="all_candidate_families_in_cooldown",
            )
            if _generated_count(generation_result) > 0:
                bank = load_hypothesis_bank(args.hypothesis_bank)
            else:
                state["status"] = "stopped"
                state["stop_reason"] = "all_candidate_families_in_cooldown"
                _save_batch_state(args.state_dir, state)
                print("Stopping: all candidate families are in cooldown.")
                break

        hypothesis = None
        selection_error = None
        for attempt in range(args.max_generation_attempts + 1):
            try:
                hypothesis = choose_next_hypothesis(
                    hypothesis_bank=bank,
                    learning_memory=learning,
                    cooldowns=cooldowns,
                    rejected_ids={str(x) for x in rejected_ids if x}.union(repeat_blocked_ids),
                    accepted_ids={str(x) for x in accepted_ids if x},
                    consumed_ids=consumed_ids,
                    parameter_effect_memory=parameter_effect_memory,
                    current_parent_hypothesis_id=str(current_parent.get("current_parent_hypothesis_id") or current_parent.get("current_parent_strategy_id")) if (current_parent.get("current_parent_hypothesis_id") or current_parent.get("current_parent_strategy_id")) else None,
                    prefer_unseen=bool(args.prefer_unseen),
                    state_dir=args.state_dir,
                )
                selection_error = None
                break
            except ValueError as exc:
                selection_error = str(exc)
                if not args.auto_generate_hypotheses_on_block or attempt >= args.max_generation_attempts:
                    break

                generated = run_candidate_generation(
                    family=args.generation_family,
                    families=str(args.generation_families) if args.generation_families else None,
                    args=args,
                    parent_strategy_config=effective_parent_strategy_config,
                    reason="no_eligible_hypothesis",
                )
                if not generated:
                    generation_result = run_feature_space_generation(
                        args=args,
                        parent_strategy_config=effective_parent_strategy_config,
                        reason="no_eligible_hypothesis_after_standard_generation",
                    )
                    generated = _generated_count(generation_result) > 0
                if not generated:
                    break
                bank = load_hypothesis_bank(args.hypothesis_bank)

        if hypothesis is None:
            state["status"] = "stopped"
            state["stop_reason"] = selection_error or "unknown_selection_error"
            _save_batch_state(args.state_dir, state)
            print(f"Stopping: {state['stop_reason']}")
            break

        hypothesis_id = str(hypothesis.get("hypothesis_id"))
        seen_counts = Counter(item.get("hypothesis_id") for item in state.get("history", []))
        if seen_counts[hypothesis_id] >= args.max_repeats_per_hypothesis:
            family = str(hypothesis.get("family"))
            reason = f"max_repeats_reached:{hypothesis_id}"
            add_family_cooldown(
                state_dir=args.state_dir,
                family=family,
                reason=reason,
                hypothesis_id=hypothesis_id,
            )
            state["status"] = "stopped"
            state["stop_reason"] = reason
            _save_batch_state(args.state_dir, state)
            print(f"Stopping: hypothesis repeated too many times ({hypothesis_id}); family cooldown added: {family}.")
            break

        try:
            strategy_config = resolve_strategy_config_for_hypothesis(hypothesis, args.strategy_registry)
        except ValueError:
            if not args.auto_generate_missing_configs:
                raise
            output_path = Path(args.generated_configs_dir) / f"{hypothesis_id}.json"
            strategy_config = generate_missing_strategy_config(
                hypothesis=hypothesis,
                parent_strategy_config_path=effective_parent_strategy_config,
                output_config_path=output_path,
                strategy_registry_path=args.strategy_registry,
                notes=f"Auto-generated from {Path(effective_parent_strategy_config).name} via hypothesis {hypothesis_id}.",
            )
        cmd = [
            sys.executable,
            "scripts/research_loop.py",
            "--strategy-config",
            strategy_config,
            "--weekly-file",
            args.weekly_file,
            "--daily-folder",
            args.daily_folder,
            "--project-config",
            args.project_config,
            "--hypothesis-id",
            hypothesis_id,
            "--family",
            str(hypothesis.get("family")),
            "--runs-dir",
            args.runs_dir,
            "--reports-dir",
            args.reports_dir,
            "--state-dir",
            args.state_dir,
            "--strategy-registry",
            args.strategy_registry,
            "--parent-strategy-config",
            effective_parent_strategy_config,
            "--evaluation-mode",
            args.evaluation_mode,
        ]
        if args.allow_parent_update:
            cmd.append("--allow-parent-update")

        print(f"Batch iteration {state['completed'] + 1}/{args.max_runs}: {hypothesis_id}")
        print(f"Using parent strategy config: {effective_parent_strategy_config}")
        code = _run_command(cmd)
        if code != 0:
            state["status"] = "failed"
            state["stop_reason"] = f"research_loop_exit_code:{code}"
            _save_batch_state(args.state_dir, state)
            print(f"Stopping: research_loop failed with code {code}")
            break

        latest_run = get_latest_run_id(args.runs_dir)
        if latest_run is None:
            state["status"] = "failed"
            state["stop_reason"] = "missing_run_folder"
            _save_batch_state(args.state_dir, state)
            print("Stopping: no run folder found after iteration.")
            break

        audit_path = Path(args.runs_dir) / latest_run / "audit.json"
        if not audit_path.exists():
            state["status"] = "failed"
            state["stop_reason"] = "missing_audit_json"
            _save_batch_state(args.state_dir, state)
            print("Stopping: missing audit.json after iteration.")
            break
        audit = read_json(audit_path)

        # PRE_RUN_GUARD_SKIP_DIRECT_PATCH
        # Pre-run guard blocks are useful learning/cleanup events, but they are
        # not real backtests. Do not count them as completed strategy runs and
        # do not increment consecutive_rejections, otherwise a batch can stop
        # after cleaning only 2 exhausted/duplicate hypotheses.
        pre_run_blocked = bool(
            audit.get("pre_run_duplicate_guard")
            or audit.get("pre_run_blocked")
            or audit.get("audit_status") == "completed_preflight_block"
            or "duplicate_preflight_blocked" in set(audit.get("flags") or [])
        )
        if pre_run_blocked:
            state["pre_run_guard_blocks"] = int(state.get("pre_run_guard_blocks", 0) or 0) + 1
            state.setdefault("history", []).append(
                {
                    "iteration": state["completed"] + 1,
                    "run_id": latest_run,
                    "hypothesis_id": hypothesis_id,
                    "family": str(hypothesis.get("family")),
                    "decision": "pre_run_guard_blocked",
                    "reason": (
                        (audit.get("pre_run_duplicate_guard") or {}).get("reason")
                        or audit.get("audit_status")
                    ),
                    "parent_strategy_config": effective_parent_strategy_config,
                    "pre_run_blocked": True,
                }
            )
            _save_batch_state(args.state_dir, state)
            print(
                f"Skipping completed-run counter for pre-run guard block: "
                f"{latest_run} / {hypothesis_id}"
            )
            max_pre_run_blocks = max(20, int(args.max_runs) * 10)
            if int(state.get("pre_run_guard_blocks", 0) or 0) >= max_pre_run_blocks:
                state["status"] = "stopped"
                state["stop_reason"] = f"too_many_pre_run_guard_blocks:{max_pre_run_blocks}"
                _save_batch_state(args.state_dir, state)
                print(f"Stopping: too many pre-run guard blocks ({max_pre_run_blocks}).")
                break
            continue

        state["completed"] += 1
        decision = str(audit.get("decision"))
        if decision == "rejected":
            state["consecutive_rejections"] += 1
        else:
            state["consecutive_rejections"] = 0

        state.setdefault("history", []).append(
            {
                "iteration": state["completed"],
                "run_id": latest_run,
                "hypothesis_id": hypothesis_id,
                "family": str(hypothesis.get("family")),
                "decision": decision,
                "parent_strategy_config": effective_parent_strategy_config,
            }
        )

        if args.stop_on_metric_no_effect:
            flags = _latest_learning_flags(args.state_dir)
            if "metric_no_effect" in flags:
                state["status"] = "stopped"
                state["stop_reason"] = "metric_no_effect"
                _save_batch_state(args.state_dir, state)
                print("Stopping: metric_no_effect detected.")
                break

        if state["consecutive_rejections"] >= args.stop_after_consecutive_rejections:
            generation_result = run_feature_space_generation(
                args=args,
                parent_strategy_config=effective_parent_strategy_config,
                reason="consecutive_rejections_pre_stop",
            )
            generated_ids = [str(x) for x in (generation_result.get("hypotheses") or []) if x]
            diagnosis = None
            selectable_count = 0
            if generated_ids:
                diagnosis = diagnose_generated_hypotheses(
                    hypothesis_bank_path=args.hypothesis_bank,
                    state_dir=args.state_dir,
                    hypothesis_ids=generated_ids,
                    max_repeats_per_hypothesis=args.max_repeats_per_hypothesis,
                )
                selectable_count = int(diagnosis.get("selectable_count", 0) or 0)

            can_recover = (
                not bool(args.no_continue_after_recovery_generation)
                and int(state.get("recovery_cycles", 0) or 0) < int(args.max_recovery_cycles)
                and _generated_count(generation_result) > 0
                and selectable_count > 0
            )
            if can_recover:
                state["recovery_cycles"] = int(state.get("recovery_cycles", 0) or 0) + 1
                state["consecutive_rejections"] = 0
                state.setdefault("recovery_history", []).append({
                    "cycle": state["recovery_cycles"],
                    "trigger": "consecutive_rejections",
                    "after_iteration": state["completed"],
                    "generated": _generated_count(generation_result),
                    "selectable": selectable_count,
                    "selectable_hypotheses": (diagnosis or {}).get("selectable", []),
                    "generated_hypotheses": generated_ids,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
                _save_batch_state(args.state_dir, state)
                print(
                    "Continuing after recovery generation:",
                    f"cycle={state['recovery_cycles']}/{args.max_recovery_cycles}",
                    f"generated={_generated_count(generation_result)}",
                    f"selectable={selectable_count}",
                )
                continue

            state["status"] = "stopped"
            state["stop_reason"] = f"consecutive_rejections:{state['consecutive_rejections']}"
            # FEATURE_SPACE_EXHAUSTED_MODE_DIRECT_PATCH
            generated_n = _generated_count(generation_result)
            if generated_n > 0 and selectable_count == 0:
                state["stop_reason"] += ":recovery_generated_but_not_selectable"
            elif generated_n == 0 and str((generation_result or {}).get("reason")) == "no_new_feature_space_hypotheses":
                state["stop_reason"] += ":feature_space_exhausted_needs_literature_mode"
                state["recommended_mode"] = "literature_or_new_family"
            elif int(state.get("recovery_cycles", 0) or 0) >= int(args.max_recovery_cycles):
                state["stop_reason"] += ":max_recovery_cycles_reached"
            _save_batch_state(args.state_dir, state)
            print(f"Stopping: {state['stop_reason']}")
            break

        _save_batch_state(args.state_dir, state)

    if state["completed"] >= args.max_runs:
        state["status"] = "completed"
        state["stop_reason"] = "max_runs_reached"
        _save_batch_state(args.state_dir, state)

    print(f"Batch finished. Completed iterations: {state['completed']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
