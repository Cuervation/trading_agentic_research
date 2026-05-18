import json
from scripts.research.autonomy_readiness import compute_readiness


def test_autonomy_readiness_reports_failed_checks(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    state = tmp_path / "state"; state.mkdir()
    (state / "current_parent.json").write_text(json.dumps({"current_parent_run_id": "AUTO_002", "current_parent_strategy_id": "PARENT", "current_parent_config_path": "configs/generated/PARENT.json"}), encoding="utf-8")
    (state / "autonomy_blocker.json").write_text(json.dumps({"status": "clear"}), encoding="utf-8")
    (state / "data_paths_resolved.json").write_text(json.dumps({"can_run": True, "source": "test"}), encoding="utf-8")
    (state / "research_ledger.jsonl").write_text(json.dumps({"run_id": "AUTO_001"}) + "\n", encoding="utf-8")
    (state / "artifact_hash_index.json").write_text(json.dumps({"signatures": {"x": {}}}), encoding="utf-8")
    (tmp_path / "bibliography").mkdir(); (tmp_path / "bibliography" / "hypothesis_bank.jsonl").write_text(json.dumps({"hypothesis_id": "H"}) + "\n", encoding="utf-8")
    (tmp_path / "configs").mkdir(); (tmp_path / "configs" / "strategy_registry.json").write_text(json.dumps({"strategies": []}), encoding="utf-8")
    result = compute_readiness(state_dir=state, registry_path=tmp_path / "configs" / "strategy_registry.json")
    assert result["readiness_pct"] < 100
    assert result["failed_checks"]
