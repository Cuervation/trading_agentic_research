import json
from argparse import Namespace
from pathlib import Path

import pytest

from scripts.run_research_batch import (
    _cooldown_families,
    _latest_learning_flags,
    _load_batch_state,
    _save_batch_state,
    run_candidate_generation,
    resolve_strategy_config_for_hypothesis,
)


def _write_json(path: Path, payload: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_resolve_strategy_config_prefers_hypothesis_id_match(tmp_path, monkeypatch):
    project_root = tmp_path / "proj"
    (project_root / "configs").mkdir(parents=True)

    cfg_a = project_root / "configs" / "a.json"
    cfg_b = project_root / "configs" / "b.json"
    _write_json(cfg_a, {"strategy_family": "cross_sectional_momentum", "hypothesis_id": "H_A"})
    _write_json(cfg_b, {"strategy_family": "cross_sectional_momentum", "hypothesis_id": "H_B"})

    registry = project_root / "configs" / "strategy_registry.json"
    _write_json(
        registry,
        {
            "strategies": [
                {"status": "candidate", "config_path": str(cfg_a)},
                {"status": "candidate", "config_path": str(cfg_b)},
            ]
        },
    )

    hypothesis = {"hypothesis_id": "H_B", "family": "cross_sectional_momentum", "bibliography_basis": []}
    resolved = resolve_strategy_config_for_hypothesis(hypothesis, registry)
    assert resolved.endswith("b.json")


def test_resolve_strategy_config_raises_when_no_match(tmp_path):
    registry = tmp_path / "strategy_registry.json"
    _write_json(registry, {"strategies": []})

    with pytest.raises(ValueError):
        resolve_strategy_config_for_hypothesis({"hypothesis_id": "H_X", "family": "x", "bibliography_basis": []}, registry)


def test_batch_state_roundtrip(tmp_path):
    state = _load_batch_state(tmp_path, max_runs=20)
    assert state["status"] == "initialized"
    assert state["completed"] == 0

    state["status"] = "running"
    state["completed"] = 3
    _save_batch_state(tmp_path, state)

    loaded = _load_batch_state(tmp_path, max_runs=20)
    assert loaded["status"] == "running"
    assert loaded["completed"] == 3
    assert "last_updated_at" in loaded


def test_latest_learning_flags_and_cooldown_helpers(tmp_path):
    learning_path = tmp_path / "learning_memory.json"
    learning_path.write_text(
        json.dumps(
            {
                "learning_events": [
                    {"learning_id": "L1", "flags": []},
                    {"learning_id": "L2", "flags": ["metric_no_effect"]},
                ]
            }
        ),
        encoding="utf-8",
    )
    flags = _latest_learning_flags(tmp_path)
    assert "metric_no_effect" in flags

    cooldowns = {"cooldowns": {"risk_management": {"reason": "repeated_failed_hypotheses"}}}
    assert _cooldown_families(cooldowns) == {"risk_management"}


def test_run_candidate_generation_command_success():
    captured = {}

    def fake_runner(command):
        captured["command"] = command
        return 0

    args = Namespace(
        state_dir="state",
        strategy_registry="configs/strategy_registry.json",
        hypothesis_bank="bibliography/hypothesis_bank.jsonl",
    )

    ok = run_candidate_generation(
        family="cross_sectional_momentum",
        args=args,
        reason="test",
        runner=fake_runner,
    )

    assert ok is True
    assert "scripts/generate_candidates_from_parent.py" in " ".join(captured["command"])
