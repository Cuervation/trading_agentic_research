import json
from pathlib import Path

from scripts.research.artifact_index import rebuild_artifact_index_from_runs, find_duplicate_artifact
from scripts.research.research_ledger import append_run_to_ledger, read_ledger
from scripts.research.champion_governance import update_champion_state, load_champion_state


def _write_run(run_dir: Path, cagr=10.0, dd=-20.0, trades="a\n1\n"):
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "metrics.json").write_text(json.dumps({"strategy": {"cagr_pct": cagr, "max_drawdown_pct": dd}, "spy": {"cagr_pct": 8.0, "max_drawdown_pct": -25.0}, "diagnostics": {"warnings": []}, "costs": {"applied": True}}), encoding="utf-8")
    (run_dir / "spy_comparison_summary.json").write_text(json.dumps({"strategy_cagr_pct": cagr, "spy_cagr_pct": 8.0, "excess_cagr_pct": cagr - 8.0, "months_beating_spy": 8, "months_losing_to_spy": 4, "years_beating_spy": 2, "years_losing_to_spy": 0}), encoding="utf-8")
    (run_dir / "trades.csv").write_text(trades, encoding="utf-8")
    (run_dir / "equity_curve.csv").write_text("date,equity\n2020-01-01,100\n", encoding="utf-8")
    (run_dir / "run_manifest.json").write_text(json.dumps({"run_id": run_dir.name, "strategy_id": f"S_{run_dir.name}", "hypothesis_id": f"H_{run_dir.name}"}), encoding="utf-8")


def test_global_duplicate_detection(tmp_path):
    runs = tmp_path / "runs"
    state = tmp_path / "state"
    _write_run(runs / "AUTO_001")
    _write_run(runs / "AUTO_002")  # same artifacts as AUTO_001
    rebuild_artifact_index_from_runs(runs, state)
    duplicate = find_duplicate_artifact(runs / "AUTO_002", state)
    assert duplicate["is_duplicate"] is True
    assert duplicate["duplicate_of_run_id"] == "AUTO_001"


def test_ledger_records_value(tmp_path):
    run = tmp_path / "runs" / "AUTO_001"
    _write_run(run)
    event = append_run_to_ledger(run_dir=run, state_dir=tmp_path / "state", audit={"decision": "rejected", "flags": []})
    assert event["value_delivered"] == "rejected_with_learning"
    assert read_ledger(tmp_path / "state")


def test_champion_governance_sets_first_best(tmp_path):
    run = tmp_path / "runs" / "AUTO_001"
    _write_run(run, cagr=20.0, dd=-15.0)
    decision = update_champion_state(run_dir=run, state_dir=tmp_path / "state", audit={"decision": "promoted_candidate", "flags": []}, allow_parent_move=True)
    state = load_champion_state(tmp_path / "state")
    assert decision["champion_action"] == "new_best_champion"
    assert state["best_champion_run_id"] == "AUTO_001"
