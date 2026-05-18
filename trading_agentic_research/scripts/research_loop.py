"""Orchestrate one safe research-loop iteration."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.generate_hypotheses_from_bibliography import validate_candidate_basis
from scripts.governance import changed_parameters_between, has_real_strategy_change
from scripts.score_hypothesis_against_memory import score_hypothesis_against_memory

CommandRunner = Callable[[list[str]], subprocess.CompletedProcess]


@dataclass(frozen=True)
class LoopInputs:
    run_id: str
    strategy_config_path: Path
    project_config_path: Path
    weekly_file: str
    daily_folder: str
    hypothesis_id: str
    family: str
    parent_run_id: str | None
    allow_parent_update: bool
    parent_strategy_config_path: Path | None = None


def read_json(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write_json(path: str | Path, payload: dict) -> None:
    Path(path).write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def read_jsonl(path: str | Path) -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    rows = []
    for line in p.read_text(encoding="utf-8-sig").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def find_hypothesis(hypothesis_id: str, hypothesis_bank_path: str | Path = "bibliography/hypothesis_bank.jsonl") -> dict | None:
    for row in read_jsonl(hypothesis_bank_path):
        if row.get("hypothesis_id") == hypothesis_id:
            return row
    return None


def next_run_id(runs_dir: str | Path = "runs", prefix: str = "EXP") -> str:
    max_number = 0
    for path in Path(runs_dir).glob(f"{prefix}_*"):
        suffix = path.name.removeprefix(f"{prefix}_")
        if suffix.isdigit():
            max_number = max(max_number, int(suffix))
    return f"{prefix}_{max_number + 1:03d}"


def resolve_loop_inputs(args: argparse.Namespace) -> LoopInputs:
    project_config = read_json(args.project_config)
    strategy_config = read_json(args.strategy_config)
    current_parent = read_json(Path(args.state_dir) / "current_parent.json") if (Path(args.state_dir) / "current_parent.json").exists() else {}

    weekly_file = args.weekly_file or project_config.get("data_paths", {}).get("weekly_file_path")
    daily_folder = args.daily_folder or project_config.get("data_paths", {}).get("daily_folder_path")
    if not weekly_file:
        raise ValueError("weekly file is required. Use --weekly-file or project_config.data_paths.weekly_file_path.")
    if not daily_folder:
        raise ValueError("daily folder is required. Use --daily-folder or project_config.data_paths.daily_folder_path.")

    run_id = args.run_id or next_run_id(args.runs_dir)
    hypothesis_id = args.hypothesis_id or strategy_config.get("hypothesis_id") or strategy_config.get("strategy_id")
    family = args.family or strategy_config.get("strategy_family") or current_parent.get("current_parent_strategy_id")
    parent_run_id = args.parent_run_id if args.parent_run_id is not None else current_parent.get("current_parent_run_id")

    return LoopInputs(
        run_id=run_id,
        strategy_config_path=Path(args.strategy_config),
        project_config_path=Path(args.project_config),
        weekly_file=str(weekly_file),
        daily_folder=str(daily_folder),
        hypothesis_id=str(hypothesis_id),
        family=str(family),
        parent_run_id=str(parent_run_id) if parent_run_id else None,
        allow_parent_update=bool(args.allow_parent_update),
        parent_strategy_config_path=resolve_parent_strategy_config_path(
            state_dir=args.state_dir,
            strategy_registry_path=getattr(args, "strategy_registry", "configs/strategy_registry.json"),
            explicit_parent_strategy_config=getattr(args, "parent_strategy_config", None),
            current_parent=current_parent,
        ),
    )


def resolve_parent_strategy_config_path(
    *,
    state_dir: str | Path,
    strategy_registry_path: str | Path,
    explicit_parent_strategy_config: str | None,
    current_parent: dict | None = None,
) -> Path | None:
    if explicit_parent_strategy_config:
        p = Path(explicit_parent_strategy_config)
        return p if p.exists() else None

    parent = current_parent if current_parent is not None else (read_json(Path(state_dir) / "current_parent.json") if (Path(state_dir) / "current_parent.json").exists() else {})
    direct_path = parent.get("current_parent_config_path")
    if direct_path:
        p = Path(direct_path)
        if not p.is_absolute():
            p = ROOT / p
        if p.exists():
            return p

    parent_strategy_id = parent.get("current_parent_strategy_id")
    if not parent_strategy_id or not Path(strategy_registry_path).exists():
        return None

    registry = read_json(strategy_registry_path)
    for row in registry.get("strategies", []):
        if row.get("strategy_id") == parent_strategy_id and row.get("config_path"):
            p = Path(row["config_path"])
            if not p.is_absolute():
                p = ROOT / p
            return p if p.exists() else None
    return None


def validate_candidate_has_real_change(strategy_config: dict, parent_strategy_config: dict | None) -> list[str]:
    """Block no-op candidates before expensive backtests."""
    if not has_real_strategy_change(parent_strategy_config, strategy_config):
        raise ValueError("blocked_no_op: candidate does not change any real strategy parameter versus parent config.")
    return changed_parameters_between(parent_strategy_config, strategy_config) if parent_strategy_config else list(strategy_config.get("changed_parameters", []) or [])


def validate_candidate_is_justified(strategy_config: dict, hypothesis: dict | None) -> None:
    """Require bibliography or empirical basis before any backtest is launched."""
    basis_payload = hypothesis or {
        "hypothesis_id": strategy_config.get("hypothesis_id") or strategy_config.get("strategy_id"),
        "bibliography_basis": _normalize_basis(strategy_config.get("bibliography_basis", []), "source_id"),
        "empirical_basis": strategy_config.get("empirical_basis", []),
    }
    validate_candidate_basis(basis_payload)


def _normalize_basis(items: list | str, key: str) -> list[dict]:
    if isinstance(items, str):
        items = [items]
    normalized = []
    for item in items or []:
        if isinstance(item, dict):
            normalized.append(item)
        else:
            normalized.append({key: str(item)})
    return normalized


def preflight_score(inputs: LoopInputs, state_dir: str | Path = "state") -> dict:
    learning_path = Path(state_dir) / "learning_memory.json"
    cooldowns_path = Path(state_dir) / "subspace_cooldowns.json"
    learning_memory = read_json(learning_path) if learning_path.exists() else {"family_summaries": {}}
    cooldowns = read_json(cooldowns_path) if cooldowns_path.exists() else {"cooldowns": {}}
    hypothesis = find_hypothesis(inputs.hypothesis_id) or {"hypothesis_id": inputs.hypothesis_id, "family": inputs.family}
    return score_hypothesis_against_memory(hypothesis, learning_memory, cooldowns)


def build_commands(inputs: LoopInputs, runs_dir: str | Path = "runs", reports_dir: str | Path = "reports") -> list[list[str]]:
    backtest_command = [
        sys.executable,
        "scripts/run_backtest.py",
        "--weekly-file",
        inputs.weekly_file,
        "--daily-folder",
        inputs.daily_folder,
        "--strategy-config",
        str(inputs.strategy_config_path),
        "--project-config",
        str(inputs.project_config_path),
        "--run-id",
        inputs.run_id,
        "--runs-dir",
        str(runs_dir),
    ]
    if inputs.parent_run_id:
        backtest_command.extend(["--parent-run-id", inputs.parent_run_id])
    if inputs.parent_strategy_config_path:
        backtest_command.extend(["--parent-strategy-config", str(inputs.parent_strategy_config_path)])

    commands = [
        backtest_command,
        [
            sys.executable,
            "scripts/evaluate_candidate.py",
            "--run-id",
            inputs.run_id,
            "--runs-dir",
            str(runs_dir),
            "--hypothesis-id",
            inputs.hypothesis_id,
            "--family",
            inputs.family,
        ],
        [
            sys.executable,
            "scripts/summarize_runs.py",
            "--runs-dir",
            str(runs_dir),
            "--output",
            str(Path(reports_dir) / "runs_summary.csv"),
        ],
    ]
    if inputs.parent_run_id:
        commands[1].extend(["--parent-run-id", inputs.parent_run_id])
    if inputs.allow_parent_update:
        strategy_id = read_json(inputs.strategy_config_path).get("strategy_id")
        commands.append(
            [
                sys.executable,
                "scripts/update_parent.py",
                "--run-id",
                inputs.run_id,
                "--runs-dir",
                str(runs_dir),
                "--strategy-id",
                str(strategy_id),
            ]
        )
    return commands


def run_commands(commands: list[list[str]], runner: CommandRunner | None = None) -> None:
    runner = runner or _default_runner
    for command in commands:
        result = runner(command)
        if result.returncode != 0:
            raise RuntimeError(f"Command failed ({result.returncode}): {' '.join(command)}")


def _default_runner(command: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(command, cwd=ROOT, check=False)


def update_research_state(state_dir: str | Path, run_id: str, status: str, note: str) -> None:
    path = Path(state_dir) / "research_state.json"
    state = read_json(path) if path.exists() else {"notes": []}
    state["loop_status"] = status
    state["last_run_id"] = run_id
    state["mode"] = "automatic_loop"
    state.setdefault("notes", []).append(note)
    write_json(path, state)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one controlled research-loop iteration.")
    parser.add_argument("--strategy-config", required=True)
    parser.add_argument("--project-config", default="configs/project_config.json")
    parser.add_argument("--weekly-file", default=None)
    parser.add_argument("--daily-folder", default=None)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--hypothesis-id", default=None)
    parser.add_argument("--family", default=None)
    parser.add_argument("--parent-run-id", default=None)
    parser.add_argument("--runs-dir", default="runs")
    parser.add_argument("--reports-dir", default="reports")
    parser.add_argument("--state-dir", default="state")
    parser.add_argument("--strategy-registry", default="configs/strategy_registry.json")
    parser.add_argument("--parent-strategy-config", default=None)
    parser.add_argument("--allow-parent-update", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    inputs = resolve_loop_inputs(args)
    strategy_config = read_json(inputs.strategy_config_path)
    hypothesis = find_hypothesis(inputs.hypothesis_id)
    validate_candidate_is_justified(strategy_config, hypothesis)
    parent_strategy_config = read_json(inputs.parent_strategy_config_path) if inputs.parent_strategy_config_path else None
    try:
        changed_parameters = validate_candidate_has_real_change(strategy_config, parent_strategy_config)
    except ValueError as exc:
        update_research_state(args.state_dir, inputs.run_id, "blocked_no_op", str(exc))
        print(str(exc))
        return 2
    if changed_parameters and not strategy_config.get("changed_parameters"):
        strategy_config["changed_parameters"] = changed_parameters

    score = preflight_score(inputs, state_dir=args.state_dir)
    if score.get("decision") == "rejected":
        update_research_state(args.state_dir, inputs.run_id, "blocked", f"Preflight rejected: {score.get('reason')}")
        print(f"Research loop blocked before backtest: {score.get('reason')}")
        return 2

    commands = build_commands(inputs, runs_dir=args.runs_dir, reports_dir=args.reports_dir)
    print(f"Research loop plan for {inputs.run_id}: {len(commands)} commands")
    if args.dry_run:
        for command in commands:
            print(" ".join(command))
        return 0

    update_research_state(args.state_dir, inputs.run_id, "running", "Loop iteration started.")
    try:
        run_commands(commands)
    except Exception as exc:
        update_research_state(args.state_dir, inputs.run_id, "failed", str(exc))
        raise
    update_research_state(args.state_dir, inputs.run_id, "completed", "Loop iteration completed.")
    print(f"Research loop completed: {inputs.run_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
