import json

from scripts.generate_candidates_from_parent import main as generate_main


def test_generator_returns_family_in_cooldown(tmp_path, monkeypatch, capsys):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / "current_parent.json").write_text(
        json.dumps({"current_parent_run_id": "EXP_007", "current_parent_strategy_id": "S1"}),
        encoding="utf-8",
    )
    (state_dir / "evidence_memory.json").write_text(json.dumps({"runs": {}}), encoding="utf-8")

    registry = tmp_path / "configs" / "strategy_registry.json"
    registry.parent.mkdir()
    registry.write_text(json.dumps({"strategies": []}), encoding="utf-8")

    bank = tmp_path / "bibliography" / "hypothesis_bank.jsonl"
    bank.parent.mkdir()
    bank.write_text("", encoding="utf-8")

    cooldowns = state_dir / "subspace_cooldowns.json"
    cooldowns.write_text(json.dumps({"cooldowns": {"cross_sectional_momentum": {"reason": "test"}}}), encoding="utf-8")

    argv = [
        "generate_candidates_from_parent.py",
        "--state-dir",
        str(state_dir),
        "--strategy-registry",
        str(registry),
        "--parent-strategy-config",
        str(tmp_path / "configs" / "parent.json"),
        "--evidence-memory",
        str(state_dir / "evidence_memory.json"),
        "--hypothesis-bank",
        str(bank),
        "--cooldowns",
        str(cooldowns),
        "--family",
        "cross_sectional_momentum",
        "--dry-run",
    ]
    (tmp_path / "configs" / "parent.json").write_text(json.dumps({"strategy_id": "PARENT"}), encoding="utf-8")

    monkeypatch.setattr("sys.argv", argv)
    code = generate_main()
    captured = capsys.readouterr().out

    assert code == 0
    payload = json.loads(captured)
    assert payload["reason"] == "family_in_cooldown"
