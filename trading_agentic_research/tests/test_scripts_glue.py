import json
import time
from pathlib import Path

import pandas as pd

from scripts.audit_last_run import find_latest_run
from scripts.compare_to_spy import rebuild_spy_outputs
from scripts.run_backtest import build_summary_markdown, build_yearly_strategy_stats
from scripts.summarize_runs import build_runs_summary, build_yearly_runs_summary


def _write_run(run_dir: Path, cagr: float, dd: float, decision: str = "pending") -> None:
    run_dir.mkdir(parents=True)
    (run_dir / "metrics.json").write_text(
        json.dumps(
            {
                "strategy": {"cagr_pct": cagr, "max_drawdown_pct": dd},
                "spy": {"cagr_pct": 10.0, "max_drawdown_pct": -30.0},
                "diagnostics": {"number_of_trades": 20},
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "audit.json").write_text(
        json.dumps({"decision": decision, "can_move_parent": decision != "rejected"}),
        encoding="utf-8",
    )
    (run_dir / "spy_comparison_summary.json").write_text(
        json.dumps(
            {
                "spy_cagr_pct": 10.0,
                "excess_cagr_pct": cagr - 10.0,
                "years_beating_spy": 3,
                "years_losing_to_spy": 1,
            }
        ),
        encoding="utf-8",
    )
    pd.DataFrame(
        {
            "run_id": [run_dir.name, run_dir.name],
            "strategy_id": ["STRAT_A", "STRAT_A"],
            "year": [2024, 2025],
            "strategy_return_pct": [20.0, 10.0],
            "spy_return_pct": [15.0, 12.0],
            "excess_return_pct": [5.0, -2.0],
            "winner": ["strategy", "spy"],
        }
    ).to_csv(run_dir / "yearly_strategy_stats.csv", index=False, sep=";", decimal=",")


def test_find_latest_run(tmp_path):
    runs = tmp_path / "runs"
    a = runs / "EXP_001"
    b = runs / "EXP_002"
    a.mkdir(parents=True)
    time.sleep(0.01)
    b.mkdir(parents=True)

    latest = find_latest_run(runs)
    assert latest.name == "EXP_002"


def test_build_runs_summary(tmp_path):
    runs = tmp_path / "runs"
    _write_run(runs / "EXP_010", cagr=12.0, dd=-20.0, decision="accepted_for_followup")
    _write_run(runs / "EXP_011", cagr=15.0, dd=-25.0, decision="promoted_candidate")

    df = build_runs_summary(runs)

    assert len(df) == 2
    assert set(["run_id", "decision", "excess_cagr_pct"]).issubset(df.columns)

    yearly = build_yearly_runs_summary(runs)
    assert len(yearly) == 4
    assert set(["run_id", "strategy_id", "year", "strategy_return_pct"]).issubset(yearly.columns)


def test_rebuild_spy_outputs(tmp_path):
    run_dir = tmp_path / "runs" / "EXP_001"
    run_dir.mkdir(parents=True)

    pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-01-02", "2024-01-31", "2024-02-29"]),
            "strategy_equity": [100000, 102000, 104000],
            "spy_equity": [100000, 101000, 103000],
        }
    ).to_csv(run_dir / "spy_comparison_daily.csv", index=False, sep=";", decimal=",")

    (run_dir / "metrics.json").write_text(
        json.dumps(
            {
                "strategy": {"cagr_pct": 12.0, "max_drawdown_pct": -20.0},
                "spy": {"cagr_pct": 10.0, "max_drawdown_pct": -25.0},
            }
        ),
        encoding="utf-8",
    )

    summary = rebuild_spy_outputs(run_dir)

    assert (run_dir / "spy_comparison_monthly.csv").exists()
    assert (run_dir / "spy_comparison_yearly.csv").exists()
    assert (run_dir / "spy_comparison_summary.json").exists()
    assert summary["strategy_cagr_pct"] == 12.0


def test_build_yearly_strategy_stats_and_summary_markdown():
    yearly_cmp = pd.DataFrame(
        {
            "year": [2024, 2025],
            "strategy_return_pct": [20.0, 10.0],
            "spy_return_pct": [15.0, 12.0],
            "excess_return_pct": [5.0, -2.0],
            "winner": ["strategy", "spy"],
        }
    )
    yearly_stats = build_yearly_strategy_stats(
        run_id="EXP_999",
        strategy_id="STRAT_TEST",
        comparison_yearly=yearly_cmp,
    )

    assert list(yearly_stats.columns) == [
        "run_id",
        "strategy_id",
        "year",
        "strategy_return_pct",
        "spy_return_pct",
        "excess_return_pct",
        "winner",
    ]
    assert (yearly_stats["run_id"] == "EXP_999").all()

    summary = build_summary_markdown(
        run_id="EXP_999",
        strategy_id="STRAT_TEST",
        strategy_metrics={"total_return_pct": 50.0, "cagr_pct": 12.0, "max_drawdown_pct": -20.0, "start_date": "2024-01-01", "end_date": "2025-12-31"},
        spy_metrics={"total_return_pct": 40.0, "cagr_pct": 10.0, "max_drawdown_pct": -25.0},
        comparison_summary={"months_beating_spy": 12, "months_losing_to_spy": 8, "years_beating_spy": 1, "years_losing_to_spy": 1, "recommendation_hint": "review"},
        yearly_stats_df=yearly_stats,
        number_of_trades=42,
        warnings=[],
    )
    assert "## Yearly Strategy Stats" in summary
    assert "| 2024 | 20.00% | 15.00% | 5.00% | strategy |" in summary
