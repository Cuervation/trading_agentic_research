"""Run multiple research-loop iterations with safe stop rules."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.select_next_hypothesis import choose_next_hypothesis, load_hypothesis_bank, read_json, read_jsonl
from scripts.generate_strategy_config import generate_strategy_config_from_hypothesis, upsert_strategy_registry
from scripts.parameter_effect_memory import load_parameter_effect_memory


def resolve_strategy_config_for_hypothesis(hypothesis: dict, strategy_registry_path: str | Path) -> str:
    """Resolve strategy config path for a selected hypothesis with strict 1:1 mapping.

    Rules:
    - Must match `config.hypothesis_id == hypothesis.hypothesis_id`.
    - No fallback by family/bibliography to avoid accidental no-op reruns.
    """
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


def run_candidate_generation(
    *,
    family: str,
    families: str | None,
    args: argparse.Namespace,
    reason: str,
    runner=_run_generation_command,
) -> bool:
    command = [
        sys.executable,
        "scripts/generate_candidates_from_parent.py",
        "--state-dir",
        args.state_dir,
        "--strategy-registry",
        args.strategy_registry,
        "--parent-strategy-config",
        args.parent_strategy_config,
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
    if code == 0:
        print(f"Generated new hypotheses for family={family} (reason={reason}).")
        return True
    print(f"Hypothesis generation failed for family={family} (reason={reason}).")
    return False


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
            "last_updated_at": datetime.now(timezone.utc).isoformat(),
        }
    return read_json(path)


def _save_batch_state(state_dir: str | Path, state: dict) -> None:
    state["last_updated_at"] = datetime.now(timezone.utc).isoformat()
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
    return set((cooldowns or {}).get("cooldowns", {}).keys())


def add_family_cooldown(
    *,
    state_dir: str | Path,
    family: str,
    reason: str,
    hypothesis_id: str | None = None,
    days: int = 7,
) -> dict:
    """Persist a family cooldown after repeat/no-effect governance blocks."""
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
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--stop-after-consecutive-rejections", type=int, default=2)
    parser.add_argument("--stop-on-metric-no-effect", action="store_true")
    parser.add_argument("--max-repeats-per-hypothesis", type=int, default=1)
    parser.add_argument(
        "--parent-strategy-config",
        default="configs/baseline_momentum_trend_v1.json",
        help="Parent strategy config used when auto-generating a missing candidate config.",
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
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    state = _load_batch_state(args.state_dir, args.max_runs)
    if not args.resume:
        state.update(
            {
                "status": "running",
                "max_runs": args.max_runs,
                "completed": 0,
                "consecutive_rejections": 0,
                "history": [],
                "stop_reason": None,
            }
        )
    else:
        state["status"] = "running"

    _save_batch_state(args.state_dir, state)

    while state["completed"] < args.max_runs:
        learning = read_json(Path(args.state_dir) / "learning_memory.json")
        cooldowns = read_json(Path(args.state_dir) / "subspace_cooldowns.json")
        current_parent = read_json(Path(args.state_dir) / "current_parent.json")
        parameter_effect_memory = load_parameter_effect_memory(Path(args.state_dir) / "parameter_effect_memory.json")
        rejected_ids = {row.get("hypothesis_id") for row in read_jsonl(Path(args.state_dir) / "rejected_hypotheses.jsonl")}
        accepted_ids = {row.get("hypothesis_id") for row in read_jsonl(Path(args.state_dir) / "accepted_hypotheses.jsonl")}
        repeat_blocked_ids = _repeat_blocked_hypothesis_ids(state.get("history", []), args.max_repeats_per_hypothesis)

        families_in_cooldown = _cooldown_families(cooldowns)
        bank = load_hypothesis_bank(args.hypothesis_bank)
        eligible_families = {h.get("family") for h in bank if str(h.get("status", "candidate")) in {"candidate", "seeded"}}
        if eligible_families and eligible_families.issubset(families_in_cooldown):
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
                    parameter_effect_memory=parameter_effect_memory,
                    current_parent_hypothesis_id=str(current_parent.get("current_parent_strategy_id")) if current_parent.get("current_parent_strategy_id") else None,
                    prefer_unseen=bool(args.prefer_unseen),
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
                    reason="no_eligible_hypothesis",
                )
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
                parent_strategy_config_path=args.parent_strategy_config,
                output_config_path=output_path,
                strategy_registry_path=args.strategy_registry,
                notes=f"Auto-generated from {Path(args.parent_strategy_config).name} via hypothesis {hypothesis_id}.",
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
        ]
        if args.allow_parent_update:
            cmd.append("--allow-parent-update")

        print(f"Batch iteration {state['completed'] + 1}/{args.max_runs}: {hypothesis_id}")
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
            state["status"] = "stopped"
            state["stop_reason"] = f"consecutive_rejections:{state['consecutive_rejections']}"
            _save_batch_state(args.state_dir, state)
            print(f"Stopping: {state['consecutive_rejections']} consecutive rejections.")
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
