import json
from pathlib import Path

import pytest

from scripts.generate_strategy_config import generate_strategy_config_from_hypothesis
from scripts.run_research_batch import generate_missing_strategy_config


def test_generate_strategy_config_requires_overrides():
    hypothesis = {
        "hypothesis_id": "H1",
        "family": "academic_momentum",
        "claim": "x",
        "bibliography_basis": [{"source_id": "s1"}],
        "empirical_basis": [],
        "status": "candidate",
        "required_spy_comparison": "monthly_and_yearly",
    }
    parent = {"strategy_id": "PARENT", "strategy_family": "cross_sectional_momentum"}

    with pytest.raises(ValueError):
        generate_strategy_config_from_hypothesis(hypothesis=hypothesis, parent_strategy_config=parent)


def test_generate_strategy_config_applies_patch():
    hypothesis = {
        "hypothesis_id": "H2",
        "family": "academic_momentum",
        "claim": "x",
        "bibliography_basis": [{"source_id": "s1"}],
        "empirical_basis": [],
        "status": "candidate",
        "required_spy_comparison": "monthly_and_yearly",
        "strategy_overrides": {"entry_rule": {"top_n": 10}, "exit_rule": {"rank_threshold": 20}},
    }
    parent = {
        "strategy_id": "BASE",
        "strategy_family": "cross_sectional_momentum",
        "entry_rule": {"top_n": 15},
        "exit_rule": {"rank_threshold": 30},
    }

    generated = generate_strategy_config_from_hypothesis(hypothesis=hypothesis, parent_strategy_config=parent)

    assert generated["parent_strategy_id"] == "BASE"
    assert generated["entry_rule"]["top_n"] == 10
    assert generated["exit_rule"]["rank_threshold"] == 20
    assert generated["hypothesis_id"] == "H2"


def test_generate_missing_strategy_config_writes_file_and_registry(tmp_path):
    parent_path = tmp_path / "parent.json"
    parent_path.write_text(json.dumps({"strategy_id": "BASE", "strategy_family": "x"}), encoding="utf-8")

    hypothesis = {
        "hypothesis_id": "H3",
        "family": "x",
        "claim": "x",
        "bibliography_basis": [{"source_id": "s1"}],
        "empirical_basis": [],
        "status": "candidate",
        "required_spy_comparison": "monthly_and_yearly",
        "strategy_overrides": {"entry_rule": {"top_n": 9}},
    }

    out_cfg = tmp_path / "generated" / "H3.json"
    registry = tmp_path / "registry.json"

    resolved = generate_missing_strategy_config(
        hypothesis=hypothesis,
        parent_strategy_config_path=parent_path,
        output_config_path=out_cfg,
        strategy_registry_path=registry,
        notes="auto",
    )

    assert Path(resolved).exists()
    payload = json.loads(Path(resolved).read_text(encoding="utf-8"))
    assert payload["entry_rule"]["top_n"] == 9

    reg = json.loads(registry.read_text(encoding="utf-8"))
    assert any(row["strategy_id"] == "H3" for row in reg["strategies"])
