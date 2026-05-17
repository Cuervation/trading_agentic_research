import json

from scripts.governance import build_run_manifest


def test_run_manifest_required_fields(tmp_path):
    strategy_path = tmp_path / "strategy.json"
    weekly_path = tmp_path / "weekly.csv"
    daily_dir = tmp_path / "daily"
    daily_file = daily_dir / "daily.csv"
    daily_dir.mkdir()
    strategy = {
        "strategy_id": "STRAT",
        "strategy_version": "2",
        "hypothesis_id": "HYP",
        "strategy_family": "cross_sectional_momentum",
        "bibliography_basis": [{"source_id": "academic_momentum_jegadeesh_titman_1993"}],
        "empirical_basis": [{"run_id": "EXP_001"}],
        "entry_rule": {"top_n": 8},
    }
    parent = {"entry_rule": {"top_n": 15}}
    strategy_path.write_text(json.dumps(strategy), encoding="utf-8")
    weekly_path.write_text("x", encoding="utf-8")
    daily_file.write_text("x", encoding="utf-8")

    manifest = build_run_manifest(
        run_id="EXP_100",
        parent_run_id="EXP_099",
        strategy_config=strategy,
        strategy_config_path=strategy_path,
        project_config={"initial_capital": 12345},
        weekly_file=weekly_path,
        daily_folder=daily_dir,
        parent_strategy_config=parent,
    )

    required = {
        "run_id",
        "parent_run_id",
        "strategy_id",
        "strategy_version",
        "hypothesis_id",
        "hypothesis_family",
        "bibliography_basis",
        "empirical_basis",
        "changed_parameters",
        "config_hash",
        "code_hash",
        "data_hash",
        "initial_capital",
        "generated_at",
    }
    assert required.issubset(manifest)
    assert manifest["changed_parameters"] == ["entry_rule.top_n"]
