import json
from pathlib import Path

import pandas as pd

from scripts.analyze_run import build_analysis, render_analysis_md


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_build_analysis_with_yearly_and_deltas(tmp_path):
    runs = tmp_path / "runs"
    state = tmp_path / "state"
    run_prev = runs / "EXP_099"
    run_cur = runs / "EXP_100"
    run_prev.mkdir(parents=True)
    run_cur.mkdir(parents=True)
    state.mkdir()

    _write_json(run_prev / "metrics.json", {"strategy": {"cagr_pct": 10.0, "max_drawdown_pct": -20.0}})
    pd.DataFrame({"ticker": ["A"], "net_return_pct": [1.0]}).to_csv(run_prev / "trades.csv", index=False)

    _write_json(
        run_cur / "metrics.json",
        {
            "strategy": {"total_return_pct": 50.0, "cagr_pct": 12.0, "max_drawdown_pct": -18.0},
            "spy": {"total_return_pct": 30.0, "cagr_pct": 8.0, "max_drawdown_pct": -25.0},
            "diagnostics": {"number_of_trades": 2},
        },
    )
    _write_json(run_cur / "audit.json", {"decision": "accepted_for_followup", "parent_comparison": {"parent_run_id": "EXP_080"}})
    pd.DataFrame(
        {
            "run_id": ["EXP_100"],
            "strategy_id": ["STRAT_X"],
            "year": [2025],
            "strategy_return_pct": [12.0],
            "spy_return_pct": [8.0],
            "excess_return_pct": [4.0],
            "winner": ["strategy"],
        }
    ).to_csv(run_cur / "yearly_strategy_stats.csv", index=False, sep=";", decimal=",")
    pd.DataFrame(
        {
            "ticker": ["A", "B"],
            "net_return_pct": [1.0, 2.0],
            "entry_date": ["2025-01-01", "2025-02-01"],
            "exit_date": ["2025-01-10", "2025-02-20"],
        }
    ).to_csv(run_cur / "trades.csv", index=False, sep=";", decimal=",")

    _write_json(
        state / "evidence_memory.json",
        {"runs": {"EXP_100": {"hypothesis_id": "HYP_X"}}},
    )
    _write_json(
        state / "batch_state.json",
        {"status": "stopped", "stop_reason": "max_repeats", "history": [{"run_id": "EXP_100"}]},
    )

    payload = build_analysis("EXP_100", runs, state)
    assert payload["run_id"] == "EXP_100"
    assert payload["strategy_id"] == "STRAT_X"
    assert payload["hypothesis_id"] == "HYP_X"
    assert payload["yearly"][0]["year"] == 2025
    assert payload["changes_vs_previous_run"]["previous_run_id"] == "EXP_099"
    assert payload["stop_context"]["batch_stop_reason"] == "max_repeats"

    md = render_analysis_md(payload)
    assert "## Year by year" in md
    assert "Changed vs previous run" in md

