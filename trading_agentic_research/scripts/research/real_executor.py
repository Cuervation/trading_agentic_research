"""Real execution bridge from autonomous research to the existing backtester."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[2]
CommandRunner = Callable[[list[str]], subprocess.CompletedProcess]


def run_real_backtest_iteration(
    *,
    run_id: str,
    strategy_config_path: str | Path,
    weekly_file: str | Path,
    daily_folder: str | Path,
    project_config: str | Path = "configs/project_config.json",
    runs_dir: str | Path = "runs",
    parent_run_id: str | None = None,
    parent_strategy_config: str | Path | None = None,
    runner: CommandRunner | None = None,
) -> dict:
    """Invoke scripts/run_backtest.py and return generated artifact paths."""
    command = [
        sys.executable,
        "scripts/run_backtest.py",
        "--weekly-file",
        str(weekly_file),
        "--daily-folder",
        str(daily_folder),
        "--strategy-config",
        str(strategy_config_path),
        "--project-config",
        str(project_config),
        "--run-id",
        run_id,
        "--runs-dir",
        str(runs_dir),
    ]
    if parent_run_id:
        command.extend(["--parent-run-id", parent_run_id])
    if parent_strategy_config:
        command.extend(["--parent-strategy-config", str(parent_strategy_config)])

    runner = runner or _default_runner
    result = runner(command)
    if result.returncode != 0:
        raise RuntimeError(f"Backtest failed ({result.returncode}): {' '.join(command)}")

    run_dir = Path(runs_dir) / run_id
    artifacts = {
        name: str(run_dir / name)
        for name in [
            "metrics.json",
            "trades.csv",
            "equity_curve.csv",
            "spy_comparison_monthly.csv",
            "spy_comparison_yearly.csv",
            "spy_comparison_summary.json",
            "run_manifest.json",
        ]
    }
    return {"run_id": run_id, "run_dir": str(run_dir), "artifacts": artifacts, "command": command}


def run_evaluate_candidate(
    *,
    run_id: str,
    runs_dir: str | Path = "runs",
    parent_run_id: str | None = None,
    hypothesis_id: str | None = None,
    family: str | None = None,
    state_dir: str | Path = "state",
    runner: CommandRunner | None = None,
) -> dict:
    """Invoke scripts/evaluate_candidate.py and require audit.json."""
    command = [
        sys.executable,
        "scripts/evaluate_candidate.py",
        "--run-id",
        run_id,
        "--runs-dir",
        str(runs_dir),
        "--state-dir",
        str(state_dir),
    ]
    if parent_run_id:
        command.extend(["--parent-run-id", parent_run_id])
    if hypothesis_id:
        command.extend(["--hypothesis-id", hypothesis_id])
    if family:
        command.extend(["--family", family])

    runner = runner or _default_runner
    result = runner(command)
    if result.returncode != 0:
        raise RuntimeError(f"Candidate audit failed ({result.returncode}): {' '.join(command)}")
    audit_path = Path(runs_dir) / run_id / "audit.json"
    if not audit_path.exists():
        raise FileNotFoundError(f"evaluate_candidate.py did not create {audit_path}")
    return {"audit_path": str(audit_path), "command": command}


def _default_runner(command: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(command, cwd=ROOT, check=False)


__all__ = ["run_real_backtest_iteration", "run_evaluate_candidate"]
