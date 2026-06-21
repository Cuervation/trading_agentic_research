import json
import subprocess
import sys
from pathlib import Path

import pandas as pd

from backtester.data_loader import (
    load_daily_feature_store_folder,
    load_weekly_feature_store,
)
from scripts.run_backtest import run_backtest_and_write_artifacts
from scripts.governance import build_run_manifest


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_ARTIFACTS = {
    "equity_curve.csv",
    "trades.csv",
    "metrics.json",
    "spy_comparison_daily.csv",
    "spy_comparison_monthly.csv",
    "spy_comparison_yearly.csv",
    "yearly_strategy_stats.csv",
    "spy_comparison_summary.json",
    "summary.md",
    "run_manifest.json",
}


def test_run_manifest_required_fields(tmp_path):
    strategy_path = tmp_path / "strategy.json"
    weekly_path = tmp_path / "weekly.csv"
    daily_dir = tmp_path / "daily"
    daily_file = daily_dir / "daily.csv"
    daily_dir.mkdir()
    strategy = {
        "strategy_id": "STRAT",
        "strategy_version": "2",
        "hypothesis_id": "HYP",
        "strategy_family": "cross_sectional_momentum",
        "bibliography_basis": [{"source_id": "academic_momentum_jegadeesh_titman_1993"}],
        "empirical_basis": [{"run_id": "EXP_001"}],
        "entry_rule": {"top_n": 8},
    }
    parent = {"entry_rule": {"top_n": 15}}
    strategy_path.write_text(json.dumps(strategy), encoding="utf-8")
    weekly_path.write_text("x", encoding="utf-8")
    daily_file.write_text("x", encoding="utf-8")

    manifest = build_run_manifest(
        run_id="EXP_100",
        parent_run_id="EXP_099",
        strategy_config=strategy,
        strategy_config_path=strategy_path,
        project_config={"initial_capital": 12345},
        weekly_file=weekly_path,
        daily_folder=daily_dir,
        parent_strategy_config=parent,
    )

    required = {
        "run_id",
        "parent_run_id",
        "strategy_id",
        "strategy_version",
        "hypothesis_id",
        "hypothesis_family",
        "bibliography_basis",
        "empirical_basis",
        "changed_parameters",
        "config_hash",
        "code_hash",
        "data_hash",
        "initial_capital",
        "generated_at",
    }
    assert required.issubset(manifest)
    assert manifest["changed_parameters"] == ["entry_rule.top_n"]


def _write_small_backtest_fixture(tmp_path):
    weekly_path = tmp_path / "weekly.csv"
    daily_dir = tmp_path / "daily"
    daily_dir.mkdir()
    daily_path = daily_dir / "sp500_feature_store_daily_master_test.csv"
    strategy_path = tmp_path / "strategy.json"
    project_path = tmp_path / "project.json"

    weekly_rows = []
    ranks = {
        "2026-01-09": {"AAA": 30.0, "BBB": 20.0},
        "2026-01-16": {"AAA": 20.0, "BBB": 30.0},
        "2026-01-23": {"AAA": 10.0, "BBB": 30.0},
    }
    for date, values in ranks.items():
        weekly_rows.append(
            {
                "date": date,
                "ticker": "SPY",
                "ret_52w_pct": 0.0,
                "close": 500.0,
                "spy_close_vs_sma50_pct": 1.0,
            }
        )
        for ticker, value in values.items():
            weekly_rows.append(
                {
                    "date": date,
                    "ticker": ticker,
                    "ret_52w_pct": value,
                    "close": 10.0,
                    "spy_close_vs_sma50_pct": None,
                }
            )
    daily_rows = []
    for date in ["2026-01-10", "2026-01-17", "2026-01-24"]:
        for ticker, close in [
            ("SPY", 500.0),
            ("AAA", 10.0),
            ("BBB", 10.0),
        ]:
            daily_rows.append(
                {"date": date, "ticker": ticker, "close": close}
            )

    strategy = {
        "strategy_id": "TEST_WEEKLY",
        "hypothesis_id": "TEST_WEEKLY",
        "benchmark_ticker": "SPY",
        "ranking": {"field": "ret_52w_pct"},
        "entry_rule": {"top_n": 1},
        "exit_rule": {"rank_threshold": 2},
        "market_filter": {
            "require_positive_trend": True,
            "fallback_allow_if_missing_spy_metric": False,
        },
        "decision_frequency": "weekly",
        "entry_frequency": "weekly",
        "exit_frequency": "weekly",
        "position_retention": "hold_until_exit_rank_threshold",
    }
    project = {
        "initial_capital": 100000,
        "cost_per_side_pct": 0.24,
        "benchmark_ticker": "SPY",
    }
    pd.DataFrame(weekly_rows).to_csv(weekly_path, index=False)
    pd.DataFrame(daily_rows).to_csv(daily_path, index=False)
    strategy_path.write_text(json.dumps(strategy), encoding="utf-8")
    project_path.write_text(json.dumps(project), encoding="utf-8")
    return weekly_path, daily_dir, strategy_path, project_path, strategy, project


def test_reusable_backtest_writes_expected_artifacts_and_matches_cli(tmp_path):
    (
        weekly_path,
        daily_dir,
        strategy_path,
        project_path,
        strategy,
        project,
    ) = _write_small_backtest_fixture(tmp_path)
    weekly_df = load_weekly_feature_store(weekly_path)
    daily_df = load_daily_feature_store_folder(daily_dir)
    inprocess_runs = tmp_path / "inprocess_runs"
    cli_runs = tmp_path / "cli_runs"

    run_backtest_and_write_artifacts(
        weekly_df=weekly_df,
        daily_df=daily_df,
        strategy_config=strategy,
        project_config=project,
        run_id="INPROCESS_RUN",
        runs_dir=inprocess_runs,
        strategy_config_path=strategy_path,
        weekly_file=weekly_path,
        daily_folder=daily_dir,
    )
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "run_backtest.py"),
            "--weekly-file",
            str(weekly_path),
            "--daily-folder",
            str(daily_dir),
            "--strategy-config",
            str(strategy_path),
            "--project-config",
            str(project_path),
            "--run-id",
            "CLI_RUN",
            "--runs-dir",
            str(cli_runs),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    inprocess_dir = inprocess_runs / "INPROCESS_RUN"
    cli_dir = cli_runs / "CLI_RUN"
    assert EXPECTED_ARTIFACTS.issubset(
        {path.name for path in inprocess_dir.iterdir()}
    )
    assert EXPECTED_ARTIFACTS.issubset(
        {path.name for path in cli_dir.iterdir()}
    )

    inprocess_metrics = json.loads(
        (inprocess_dir / "metrics.json").read_text(encoding="utf-8")
    )
    cli_metrics = json.loads(
        (cli_dir / "metrics.json").read_text(encoding="utf-8")
    )
    assert inprocess_metrics == cli_metrics
