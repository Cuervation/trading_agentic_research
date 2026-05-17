import json
import subprocess
import sys
from argparse import Namespace
from pathlib import Path

import pytest

from scripts.research_loop import (
    LoopInputs,
    build_commands,
    next_run_id,
    resolve_loop_inputs,
    run_commands,
    update_research_state,
    validate_candidate_is_justified,
)


def test_next_run_id_skips_existing_runs(tmp_path):
    runs = tmp_path / "runs"
    (runs / "EXP_001").mkdir(parents=True)
    (runs / "EXP_004").mkdir()
    (runs / "OTHER").mkdir()

    assert next_run_id(runs) == "EXP_005"


def test_validate_candidate_requires_basis_before_loop():
    with pytest.raises(ValueError):
        validate_candidate_is_justified({"strategy_id": "S1"}, hypothesis=None)

    validate_candidate_is_justified(
        {"strategy_id": "S2", "bibliography_basis": ["academic_momentum_jegadeesh_titman_1993"]},
        hypothesis=None,
    )


def test_resolve_loop_inputs_uses_project_config_and_parent(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    project = tmp_path / "project.json"
    strategy = tmp_path / "strategy.json"
    project.write_text(
        json.dumps({"data_paths": {"weekly_file_path": "weekly.csv", "daily_folder_path": "daily"}}),
        encoding="utf-8",
    )
    strategy.write_text(
        json.dumps({"strategy_id": "STRAT", "strategy_family": "risk_management"}),
        encoding="utf-8",
    )
    (state / "current_parent.json").write_text(
        json.dumps({"current_parent_run_id": "EXP_003", "current_parent_strategy_id": "BASE"}),
        encoding="utf-8",
    )

    args = Namespace(
        project_config=str(project),
        strategy_config=str(strategy),
        weekly_file=None,
        daily_folder=None,
        run_id="EXP_010",
        hypothesis_id="HYP_1",
        family=None,
        parent_run_id=None,
        runs_dir=str(tmp_path / "runs"),
        state_dir=str(state),
        allow_parent_update=False,
    )

    inputs = resolve_loop_inputs(args)

    assert inputs.weekly_file == "weekly.csv"
    assert inputs.daily_folder == "daily"
    assert inputs.parent_run_id == "EXP_003"
    assert inputs.family == "risk_management"


def test_build_commands_includes_parent_and_optional_parent_update(tmp_path):
    strategy = tmp_path / "strategy.json"
    strategy.write_text(json.dumps({"strategy_id": "STRAT_NEW"}), encoding="utf-8")
    inputs = LoopInputs(
        run_id="EXP_100",
        strategy_config_path=strategy,
        project_config_path=tmp_path / "project.json",
        weekly_file="weekly.csv",
        daily_folder="daily",
        hypothesis_id="HYP_100",
        family="risk_management",
        parent_run_id="EXP_003",
        allow_parent_update=True,
    )

    commands = build_commands(inputs, runs_dir="runs", reports_dir="reports")

    assert len(commands) == 4
    assert commands[0][0] == sys.executable
    assert "--parent-run-id" in commands[1]
    assert "EXP_003" in commands[1]
    assert commands[-1][1] == "scripts/update_parent.py"


def test_run_commands_stops_on_failure():
    calls = []

    def runner(command):
        calls.append(command)
        return subprocess.CompletedProcess(command, returncode=1)

    with pytest.raises(RuntimeError):
        run_commands([["bad"], ["never"]], runner=runner)

    assert calls == [["bad"]]


def test_update_research_state_appends_note(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    (state / "research_state.json").write_text(json.dumps({"notes": []}), encoding="utf-8")

    update_research_state(state, "EXP_200", "completed", "Loop done.")

    payload = json.loads((state / "research_state.json").read_text(encoding="utf-8"))
    assert payload["loop_status"] == "completed"
    assert payload["last_run_id"] == "EXP_200"
    assert payload["mode"] == "automatic_loop"
    assert payload["notes"] == ["Loop done."]
