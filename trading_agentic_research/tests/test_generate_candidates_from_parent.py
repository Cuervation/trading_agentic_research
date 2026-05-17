import json
from pathlib import Path

import pytest

from scripts.generate_candidates_from_parent import build_parent_mutation_hypotheses
from scripts.generate_candidates_from_parent import main as generate_main


def test_build_parent_mutation_hypotheses_has_overrides_and_basis():
    candidates = build_parent_mutation_hypotheses(
        parent_run_id="EXP_PARENT",
        parent_learning_id="LEARN_EXP_PARENT",
        family="cross_sectional_momentum",
        version_suffix="V1",
    )

    assert len(candidates) >= 3
    for h in candidates:
        assert h["bibliography_basis"]
        assert h["empirical_basis"]
        assert h["strategy_overrides"]
        assert "strategy_id" in h["strategy_overrides"]


def test_generator_respects_cooldown(tmp_path, monkeypatch, capsys):
    # Arrange minimal files
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / "current_parent.json").write_text(
        json.dumps({"current_parent_run_id": "EXP_007", "current_parent_strategy_id": "S1"}),
        encoding="utf-8",
    )
    (state_dir / "evidence_memory.json").write_text(
        json.dumps({"runs": {"EXP_007": {"learning_id": "LEARN_EXP_007", "family": "cross_sectional_momentum"}}}),
        encoding="utf-8",
    )
    registry = tmp_path / "configs" / "strategy_registry.json"
    registry.parent.mkdir()
    registry.write_text(
        json.dumps({"strategies": [{"strategy_id": "S1", "config_path": "configs/s1.json"}]}),
        encoding="utf-8",
    )
    (tmp_path / "configs" / "s1.json").write_text(json.dumps({"strategy_id": "S1"}), encoding="utf-8")
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
        "--evidence-memory",
        str(state_dir / "evidence_memory.json"),
        "--hypothesis-bank",
        str(bank),
        "--cooldowns",
        str(cooldowns),
        "--family",
        "cross_sectional_momentum",
    ]
    monkeypatch.setenv("PYTHONIOENCODING", "utf-8")
    monkeypatch.setattr("sys.argv", argv)

    # Act
    code = generate_main()
    captured = capsys.readouterr().out

    # Assert
    assert code == 0
    payload = json.loads(captured)
    assert payload["reason"] == "family_in_cooldown"
