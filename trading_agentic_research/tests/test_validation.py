import json
from pathlib import Path

import pandas as pd

from backtester.validation import audit_run_folder


def _write_valid_run(
    run_dir: Path,
    *,
    strategy_cagr=12.0,
    spy_cagr=10.0,
    strategy_dd=-18.0,
    spy_dd=-20.0,
    years_win=2,
    years_loss=1,
    trades=12,
    equity_values=None,
):
    run_dir.mkdir(parents=True)
    equity_values = equity_values or [100000, 105000, 112000]
    pd.DataFrame(
        {
            "date": pd.date_range("2026-01-01", periods=len(equity_values), freq="ME"),
            "equity": equity_values,
        }
    ).to_csv(run_dir / "equity_curve.csv", index=False)
    pd.DataFrame(
        {
            "ticker": [f"T{i}" for i in range(trades)],
            "gross_return_pct": [5.0] * trades,
            "net_return_pct": [4.52] * trades,
        }
    ).to_csv(run_dir / "trades.csv", index=False)
    (run_dir / "metrics.json").write_text(
        json.dumps(
            {
                "strategy": {"cagr_pct": strategy_cagr, "max_drawdown_pct": strategy_dd},
                "spy": {"cagr_pct": spy_cagr, "max_drawdown_pct": spy_dd},
                "diagnostics": {"warnings": []},
                "costs": {"applied": True, "cost_per_side_pct": 0.24},
            }
        ),
        encoding="utf-8",
    )
    pd.DataFrame({"winner": ["strategy", "spy"]}).to_csv(run_dir / "spy_comparison_monthly.csv", index=False)
    pd.DataFrame({"winner": ["strategy", "spy"]}).to_csv(run_dir / "spy_comparison_yearly.csv", index=False)
    (run_dir / "spy_comparison_summary.json").write_text(
        json.dumps(
            {
                "strategy_cagr_pct": strategy_cagr,
                "spy_cagr_pct": spy_cagr,
                "excess_cagr_pct": strategy_cagr - spy_cagr,
                "months_beating_spy": 6,
                "months_losing_to_spy": 4,
                "years_beating_spy": years_win,
                "years_losing_to_spy": years_loss,
            }
        ),
        encoding="utf-8",
    )


def test_audit_run_folder_promoted_candidate_never_baseline(tmp_path):
    run_dir = tmp_path / "EXP_001"
    _write_valid_run(run_dir)

    audit = audit_run_folder(run_dir, min_trades=10)

    assert audit["audit_status"] == "completed"
    assert audit["decision"] == "promoted_candidate"
    assert audit["can_move_parent"] is True
    assert audit["can_promote_baseline"] is False
    assert audit["blocking_issues"] == []


def test_audit_run_folder_rejects_missing_files(tmp_path):
    run_dir = tmp_path / "EXP_002"
    run_dir.mkdir()

    audit = audit_run_folder(run_dir, min_trades=10)

    assert audit["decision"] == "rejected"
    assert audit["can_promote_baseline"] is False
    assert audit["blocking_issues"]


def test_audit_run_folder_rejects_underperform_without_drawdown_improvement(tmp_path):
    run_dir = tmp_path / "EXP_003"
    _write_valid_run(run_dir, strategy_cagr=8.0, spy_cagr=10.0, strategy_dd=-30.0, spy_dd=-20.0)

    audit = audit_run_folder(run_dir, min_trades=10)

    assert audit["decision"] == "rejected"
    assert any("below SPY" in reason for reason in audit["reasons"])


def test_audit_run_folder_rejects_insufficient_trades(tmp_path):
    run_dir = tmp_path / "EXP_004"
    _write_valid_run(run_dir, trades=3)

    audit = audit_run_folder(run_dir, min_trades=10)

    assert audit["decision"] == "rejected"
    assert any("Insufficient trades" in reason for reason in audit["reasons"])


def test_audit_run_folder_accepts_followup_for_drawdown_improvement(tmp_path):
    run_dir = tmp_path / "EXP_005"
    _write_valid_run(
        run_dir,
        strategy_cagr=9.0,
        spy_cagr=10.0,
        strategy_dd=-10.0,
        spy_dd=-20.0,
        years_win=2,
        years_loss=1,
    )

    audit = audit_run_folder(run_dir, min_trades=10)

    assert audit["decision"] == "accepted_for_followup"
    assert audit["can_move_parent"] is True
    assert audit["can_promote_baseline"] is False


def test_audit_run_folder_rejects_missing_costs(tmp_path):
    run_dir = tmp_path / "EXP_006"
    _write_valid_run(run_dir)
    metrics_path = run_dir / "metrics.json"
    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    metrics.pop("costs")
    metrics_path.write_text(json.dumps(metrics), encoding="utf-8")
    trades = pd.read_csv(run_dir / "trades.csv")
    trades["net_return_pct"] = trades["gross_return_pct"]
    trades.to_csv(run_dir / "trades.csv", index=False)

    audit = audit_run_folder(run_dir, min_trades=10)

    assert audit["decision"] == "rejected"
    assert any("costs" in issue.lower() for issue in audit["blocking_issues"])


def test_audit_run_folder_rejects_candidate_that_loses_to_parent(tmp_path):
    parent_dir = tmp_path / "EXP_PARENT"
    run_dir = tmp_path / "EXP_CHILD"
    _write_valid_run(
        parent_dir,
        strategy_cagr=30.0,
        strategy_dd=-20.0,
        equity_values=[100000, 120000, 140000],
    )
    _write_valid_run(
        run_dir,
        strategy_cagr=20.0,
        spy_cagr=10.0,
        strategy_dd=-30.0,
        spy_dd=-35.0,
        equity_values=[100000, 110000, 115000],
    )

    audit = audit_run_folder(run_dir, min_trades=10, parent_run_dir=parent_dir)

    assert audit["decision"] == "rejected"
    assert audit["can_move_parent"] is False
    assert audit["parent_comparison"]["excess_cagr_vs_parent_pct"] == -10.0
    assert audit["parent_comparison"]["drawdown_delta_vs_parent_pct"] == -10.0


def test_audit_run_folder_parent_comparison_blocks_parent_move_without_promotion(tmp_path):
    parent_dir = tmp_path / "EXP_PARENT"
    run_dir = tmp_path / "EXP_CHILD"
    _write_valid_run(
        parent_dir,
        strategy_cagr=20.0,
        strategy_dd=-20.0,
        equity_values=[100000, 103000, 120000],
    )
    _write_valid_run(
        run_dir,
        strategy_cagr=21.0,
        spy_cagr=10.0,
        strategy_dd=-27.0,
        spy_dd=-35.0,
        equity_values=[100000, 105000, 121000],
    )

    audit = audit_run_folder(run_dir, min_trades=10, parent_run_dir=parent_dir)

    assert audit["decision"] == "accepted_for_followup"
    assert audit["can_move_parent"] is False
    assert audit["parent_comparison"]["parent_available"] is True
