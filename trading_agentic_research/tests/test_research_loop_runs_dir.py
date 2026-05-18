import argparse
from pathlib import Path

from scripts.research_loop import LoopInputs, build_commands


def test_backtest_command_receives_runs_dir(tmp_path):
    inputs = LoopInputs(
        run_id="EXP_999",
        strategy_config_path=Path("configs/generated/CANDIDATE.json"),
        project_config_path=Path("configs/project_config.json"),
        weekly_file="weekly.csv",
        daily_folder="daily",
        hypothesis_id="HYP_TEST",
        family="test_family",
        parent_run_id="AUTO_002",
        allow_parent_update=False,
        parent_strategy_config_path=Path("configs/generated/PARENT.json"),
    )
    commands = build_commands(inputs, runs_dir="runs_test", reports_dir="reports_test")
    backtest = commands[0]
    assert "--runs-dir" in backtest
    idx = backtest.index("--runs-dir")
    assert backtest[idx + 1] == "runs_test"
