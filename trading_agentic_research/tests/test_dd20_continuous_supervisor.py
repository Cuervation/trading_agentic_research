from argparse import Namespace

from scripts.run_dd20_continuous_supervisor import should_stop_after_cycle, write_supervisor_reports


def _args(tmp_path):
    return Namespace(
        continue_after_first_valid=True,
        stop_after_excellent=False,
        target_excellent_strategies=1,
        reports_dir=str(tmp_path / "reports"),
        state_dir=str(tmp_path / "state"),
        runs_dir=str(tmp_path / "runs"),
        parent_run_id="PARENT",
    )


def test_supervisor_continues_after_cycle_limits_and_valid_when_configured(tmp_path):
    args = _args(tmp_path)
    frontier = {"valid_candidate": [{"strategy_id": "VALID", "cagr": 10, "spy_cagr": 7, "max_drawdown": -19, "trades": 3000, "years_beating_spy": 15, "years_losing_to_spy": 13}]}

    assert not should_stop_after_cycle("max_batches_reached", args, frontier)
    assert not should_stop_after_cycle("max_total_attempts_reached", args, frontier)
    assert not should_stop_after_cycle("target_valid_strategies_reached", args, frontier)


def test_supervisor_does_not_stop_for_near_valid(tmp_path):
    args = _args(tmp_path)
    frontier = {"near_valid_low_trades": [{"strategy_id": "NEAR", "cagr": 10, "spy_cagr": 7, "max_drawdown": -19, "trades": 2400, "years_beating_spy": 17, "years_losing_to_spy": 11}]}

    assert not should_stop_after_cycle("max_batches_reached", args, frontier)


def test_supervisor_writes_summary_and_cycles_without_parent_baseline_changes(tmp_path):
    args = _args(tmp_path)
    state = {"status": "running", "cycle": 1, "last_stop_reason": "max_batches_reached", "next_action": "continue_next_cycle"}
    cycle = {"cycle": 1, "started_at": "a", "ended_at": "b", "daemon_stop_reason": "max_batches_reached"}

    write_supervisor_reports(args, state, [cycle])

    assert (tmp_path / "reports/dd20_supervisor_summary.md").exists()
    assert (tmp_path / "reports/dd20_supervisor_cycles.csv").exists()
    assert not (tmp_path / "state/current_parent.json").exists()
    assert not (tmp_path / "state/current_baseline.json").exists()
