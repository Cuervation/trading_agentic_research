import csv
import json
import threading
import time
from types import SimpleNamespace

import pandas as pd

from backtester.execution import run_strategy_backtest
from backtester.signal_builder import build_momentum_trend_signals
from scripts import run_weekly_entry_exit_experiment as weekly_runner


def _config(*, weekly=False):
    config = {
        "benchmark_ticker": "SPY",
        "ranking": {"field": "ret_52w_pct"},
        "entry_rule": {"top_n": 1},
        "exit_rule": {"rank_threshold": 2},
        "market_filter": {
            "require_positive_trend": True,
            "fallback_allow_if_missing_spy_metric": False,
        },
    }
    if weekly:
        config.update(
            {
                "decision_frequency": "weekly",
                "entry_frequency": "weekly",
                "exit_frequency": "weekly",
                "position_retention": "hold_until_exit_rank_threshold",
            }
        )
    return config


def _weekly_snapshots():
    rows = []
    ranks = {
        "2026-01-09": {"AAA": 30.0, "BBB": 20.0, "CCC": 10.0},
        "2026-01-16": {"AAA": 20.0, "BBB": 30.0, "CCC": 10.0},
        "2026-01-23": {"AAA": 10.0, "BBB": 30.0, "CCC": 20.0},
    }
    for date, values in ranks.items():
        rows.append(
            {
                "date": date,
                "ticker": "SPY",
                "ret_52w_pct": 0.0,
                "close": 500.0,
                "spy_close_vs_sma50_pct": 1.0,
            }
        )
        for ticker, value in values.items():
            rows.append(
                {
                    "date": date,
                    "ticker": ticker,
                    "ret_52w_pct": value,
                    "close": 10.0,
                    "spy_close_vs_sma50_pct": None,
                }
            )
    return pd.DataFrame(rows)


def _daily_prices():
    rows = []
    for date in ["2026-01-10", "2026-01-17", "2026-01-24"]:
        for ticker, close in [("SPY", 500.0), ("AAA", 10.0), ("BBB", 10.0), ("CCC", 10.0)]:
            rows.append({"date": date, "ticker": ticker, "close": close})
    return pd.DataFrame(rows)


def _project():
    return {
        "initial_capital": 100000,
        "cost_per_side_pct": 0.24,
        "benchmark_ticker": "SPY",
    }


def test_monthly_decision_frequency_keeps_legacy_last_snapshot():
    signals = build_momentum_trend_signals(_weekly_snapshots(), _config())

    assert set(signals["signal_date"]) == {pd.Timestamp("2026-01-23")}


def test_weekly_decision_frequency_uses_every_available_snapshot():
    signals = build_momentum_trend_signals(_weekly_snapshots(), _config(weekly=True))

    assert set(signals["signal_date"]) == {
        pd.Timestamp("2026-01-09"),
        pd.Timestamp("2026-01-16"),
        pd.Timestamp("2026-01-23"),
    }


def test_weekly_exit_holds_existing_position_inside_exit_rank_threshold():
    result = run_strategy_backtest(
        _weekly_snapshots().query("date != '2026-01-23'"),
        _daily_prices(),
        _config(weekly=True),
        _project(),
    )

    jan17 = result["equity_curve"].loc[
        result["equity_curve"]["date"].eq(pd.Timestamp("2026-01-17"))
    ].iloc[0]
    assert int(jan17["positions_count"]) == 2
    assert not (
        result["trades"]["ticker"].eq("AAA")
        & result["trades"]["exit_reason"].eq("left_exit_rank_threshold")
    ).any()


def test_weekly_exit_closes_above_threshold_after_signal_without_lookahead():
    result = run_strategy_backtest(
        _weekly_snapshots(),
        _daily_prices(),
        _config(weekly=True),
        _project(),
    )

    aaa = result["trades"].loc[
        result["trades"]["ticker"].eq("AAA")
        & result["trades"]["exit_reason"].eq("left_exit_rank_threshold")
    ].iloc[0]
    assert aaa["exit_reason"] == "left_exit_rank_threshold"
    assert aaa["exit_date"] == pd.Timestamp("2026-01-24")
    assert aaa["exit_date"] > pd.Timestamp("2026-01-23")
    assert (result["trades"]["entry_date"] > result["trades"]["signal_date"]).all()


def _runner_candidate(tmp_path):
    config_path = tmp_path / "original.json"
    config_path.write_text(
        json.dumps({"strategy_id": "TEST_STRATEGY"}),
        encoding="utf-8",
    )
    return {
        "source": "runs",
        "strategy_id": "TEST_STRATEGY",
        "run_id": "ORIGINAL_RUN",
        "run_dir": tmp_path / "runs" / "ORIGINAL_RUN",
        "config_path": config_path,
        "config_hash": "original-hash",
        "parent_run_id": None,
        "strategy_family": "test",
        "manifest": {},
        "mtime_ns": 0,
    }


def _patch_runner_row(monkeypatch):
    monkeypatch.setattr(
        weekly_runner,
        "result_row",
        lambda root, candidate, original_path, weekly_path, weekly_id,
        weekly_run_id, status, error="": {
            "status": status,
            "weekly_run_id": weekly_run_id,
            "error": error,
        },
    )


def test_resume_reuses_valid_existing_weekly_run(tmp_path, monkeypatch):
    _patch_runner_row(monkeypatch)
    monkeypatch.setattr(
        weekly_runner,
        "find_existing_weekly_run",
        lambda *args: "EXISTING_WEEKLY_RUN",
    )
    monkeypatch.setattr(
        weekly_runner,
        "run_variant",
        lambda *args: (_ for _ in ()).throw(AssertionError("must reuse")),
    )

    row = weekly_runner.process_candidate(
        tmp_path,
        tmp_path / "weekly.csv",
        tmp_path / "daily",
        tmp_path / "project.json",
        tmp_path / "generated",
        _runner_candidate(tmp_path),
        generate_only=False,
        resume=True,
        force=False,
    )

    assert row["status"] == "reused"
    assert row["weekly_run_id"] == "EXISTING_WEEKLY_RUN"


def test_without_resume_does_not_reuse_existing_weekly_run(tmp_path, monkeypatch):
    _patch_runner_row(monkeypatch)
    monkeypatch.setattr(
        weekly_runner,
        "find_existing_weekly_run",
        lambda *args: (_ for _ in ()).throw(AssertionError("must not search")),
    )
    monkeypatch.setattr(
        weekly_runner, "run_variant", lambda *args: "NEW_WEEKLY_RUN"
    )

    row = weekly_runner.process_candidate(
        tmp_path,
        tmp_path / "weekly.csv",
        tmp_path / "daily",
        tmp_path / "project.json",
        tmp_path / "generated",
        _runner_candidate(tmp_path),
        generate_only=False,
        resume=False,
        force=False,
    )

    assert row["status"] == "completed"
    assert row["weekly_run_id"] == "NEW_WEEKLY_RUN"


def test_force_does_not_reuse_existing_weekly_run(tmp_path, monkeypatch):
    _patch_runner_row(monkeypatch)
    monkeypatch.setattr(
        weekly_runner,
        "find_existing_weekly_run",
        lambda *args: (_ for _ in ()).throw(AssertionError("must not search")),
    )
    monkeypatch.setattr(
        weekly_runner, "run_variant", lambda *args: "FORCED_WEEKLY_RUN"
    )

    row = weekly_runner.process_candidate(
        tmp_path,
        tmp_path / "weekly.csv",
        tmp_path / "daily",
        tmp_path / "project.json",
        tmp_path / "generated",
        _runner_candidate(tmp_path),
        generate_only=False,
        resume=True,
        force=True,
    )

    assert row["status"] == "completed"
    assert row["weekly_run_id"] == "FORCED_WEEKLY_RUN"


def test_workers_generate_all_rows_and_single_report(tmp_path, monkeypatch):
    candidates = [
        {"strategy_id": f"STRATEGY_{index}", "source": "runs"}
        for index in range(4)
    ]
    report_dir = tmp_path / "report"
    seen_threads = set()
    seen_threads_lock = threading.Lock()

    monkeypatch.setattr(
        weekly_runner,
        "parse_args",
        lambda: SimpleNamespace(
            repo_root=str(tmp_path),
            source="runs",
            strategy_id=[],
            max_strategies=0,
            generate_only=False,
            resume=False,
            force=False,
            workers=2,
            execution_backend="subprocess",
            report_dir=str(report_dir),
        ),
    )
    monkeypatch.setattr(
        weekly_runner, "select_candidates", lambda root, source: candidates
    )
    monkeypatch.setattr(
        weekly_runner,
        "resolve_data_paths",
        lambda root, project: (tmp_path / "weekly.csv", tmp_path / "daily"),
    )

    def fake_process(*args, **kwargs):
        candidate = args[5]
        with seen_threads_lock:
            seen_threads.add(threading.get_ident())
        time.sleep(0.03)
        row = {column: None for column in weekly_runner.REPORT_COLUMNS}
        row.update(
            {
                "original_strategy_id": candidate["strategy_id"],
                "weekly_strategy_id": (
                    f"{candidate['strategy_id']}{weekly_runner.SUFFIX}"
                ),
                "weekly_run_id": f"RUN_{candidate['strategy_id']}",
                "source": candidate["source"],
                "status": "completed",
            }
        )
        return row

    monkeypatch.setattr(weekly_runner, "process_candidate", fake_process)

    assert weekly_runner.main() == 0
    with (report_dir / "weekly_entry_exit_summary.csv").open(
        encoding="utf-8"
    ) as handle:
        rows = list(csv.DictReader(handle))

    assert len(rows) == len(candidates)
    assert (report_dir / "weekly_entry_exit_summary.md").exists()
    assert len(seen_threads) == 2


def test_inprocess_backend_loads_data_once_and_writes_completed_row(
    tmp_path, monkeypatch
):
    candidates = [
        {"strategy_id": "STRATEGY_1", "source": "runs"},
        {"strategy_id": "STRATEGY_2", "source": "runs"},
    ]
    report_dir = tmp_path / "report"
    weekly_df = object()
    daily_df = object()
    load_counts = {"weekly": 0, "daily": 0}

    monkeypatch.setattr(
        weekly_runner,
        "parse_args",
        lambda: SimpleNamespace(
            repo_root=str(tmp_path),
            source="runs",
            strategy_id=[],
            max_strategies=1,
            generate_only=False,
            resume=False,
            force=False,
            workers=1,
            execution_backend="inprocess",
            report_dir=str(report_dir),
        ),
    )
    monkeypatch.setattr(
        weekly_runner, "select_candidates", lambda root, source: candidates
    )
    monkeypatch.setattr(
        weekly_runner,
        "resolve_data_paths",
        lambda root, project: (tmp_path / "weekly.csv", tmp_path / "daily"),
    )

    def load_weekly(path):
        load_counts["weekly"] += 1
        return weekly_df

    def load_daily(path):
        load_counts["daily"] += 1
        return daily_df

    monkeypatch.setattr(weekly_runner, "load_weekly_feature_store", load_weekly)
    monkeypatch.setattr(
        weekly_runner, "load_daily_feature_store_folder", load_daily
    )

    def fake_process(*args, **kwargs):
        assert kwargs["execution_backend"] == "inprocess"
        assert kwargs["weekly_df"] is weekly_df
        assert kwargs["daily_df"] is daily_df
        row = {column: None for column in weekly_runner.REPORT_COLUMNS}
        row.update(
            {
                "original_strategy_id": args[5]["strategy_id"],
                "weekly_strategy_id": (
                    f"{args[5]['strategy_id']}{weekly_runner.SUFFIX}"
                ),
                "weekly_run_id": "INPROCESS_RUN",
                "source": "runs",
                "status": "completed",
            }
        )
        return row

    monkeypatch.setattr(weekly_runner, "process_candidate", fake_process)

    assert weekly_runner.main() == 0
    with (report_dir / "weekly_entry_exit_summary.csv").open(
        encoding="utf-8"
    ) as handle:
        rows = list(csv.DictReader(handle))

    assert len(rows) == 1
    assert rows[0]["status"] == "completed"
    assert load_counts == {"weekly": 1, "daily": 1}
