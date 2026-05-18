import json

from scripts.research.autonomy_readiness import compute_readiness


def test_readiness_resolves_repo_root_paths(tmp_path):
    repo = tmp_path / "repo"
    (repo / "state").mkdir(parents=True)
    (repo / "configs" / "generated").mkdir(parents=True)
    (repo / "configs").mkdir(exist_ok=True)
    (repo / "bibliography").mkdir()
    (repo / "reports").mkdir()

    (repo / "configs" / "generated" / "PARENT.json").write_text("{}", encoding="utf-8")
    (repo / "state" / "current_parent.json").write_text(json.dumps({
        "current_parent_run_id": "AUTO_002",
        "current_parent_strategy_id": "PARENT",
        "current_parent_config_path": "configs/generated/PARENT.json",
    }), encoding="utf-8")
    (repo / "configs" / "strategy_registry.json").write_text(json.dumps({"strategies": [{"strategy_id": "PARENT"}]}), encoding="utf-8")
    (repo / "state" / "data_paths_resolved.json").write_text(json.dumps({"can_run": True, "source": "test"}), encoding="utf-8")
    (repo / "state" / "research_ledger.jsonl").write_text("{}\n", encoding="utf-8")
    (repo / "state" / "artifact_hash_index.json").write_text(json.dumps({"x": 1}), encoding="utf-8")
    (repo / "bibliography" / "hypothesis_bank.jsonl").write_text("{}\n", encoding="utf-8")
    (repo / "bibliography" / "paper_ideas.jsonl").write_text("{}\n", encoding="utf-8")

    result = compute_readiness(state_dir="state", registry_path="configs/strategy_registry.json", repo_root=repo)
    assert result["readiness_pct"] >= 85
