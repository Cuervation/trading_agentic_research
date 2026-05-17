import json
from pathlib import Path

import pandas as pd

from scripts.analyze_all_runs import main as analyze_all_main


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_analyze_all_runs_generates_outputs(tmp_path, monkeypatch):
    runs = tmp_path / "runs"
    state = tmp_path / "state"
    run = runs / "EXP_001"
    run.mkdir(parents=True)
    state.mkdir()

    _write_json(run / "metrics.json", {"strategy": {"cagr_pct": 10.0, "max_drawdown_pct": -20.0}, "spy": {"cagr_pct": 8.0}})
    _write_json(run / "audit.json", {"decision": "accepted_for_followup"})
    pd.DataFrame(
        {
            "run_id": ["EXP_001"],
            "strategy_id": ["S1"],
            "year": [2025],
            "strategy_return_pct": [11.0],
            "spy_return_pct": [8.0],
            "excess_return_pct": [3.0],
            "winner": ["strategy"],
        }
    ).to_csv(run / "yearly_strategy_stats.csv", index=False, sep=";", decimal=",")
    pd.DataFrame({"ticker": ["A"], "net_return_pct": [1.0]}).to_csv(run / "trades.csv", index=False, sep=";", decimal=",")

    _write_json(state / "evidence_memory.json", {"runs": {"EXP_001": {"hypothesis_id": "H1"}}})
    _write_json(state / "batch_state.json", {"status": "stopped", "stop_reason": "x", "history": [{"run_id": "EXP_001"}]})

    monkeypatch.setattr(
        "sys.argv",
        ["analyze_all_runs.py", "--runs-dir", str(runs), "--state-dir", str(state)],
    )
    code = analyze_all_main()
    assert code == 0
    assert (run / "analysis.json").exists()
    assert (run / "analysis.md").exists()

