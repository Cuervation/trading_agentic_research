import json
from pathlib import Path

from scripts.governance import has_real_strategy_change
from scripts.run_dd_first_long_research_loop import (
    AXIS_PRIORITY,
    generate_next_causal_hypothesis,
    load_axis_memory,
    read_json,
    useful_candidate,
    write_axis_summary,
)


def test_long_loop_generation_has_single_axis_real_change(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    parent = {
        "strategy_id": "HYP_AUTO_TIME_SERIES_MOMENTUM_SEED",
        "hypothesis_id": "HYP_AUTO_TIME_SERIES_MOMENTUM_SEED",
        "strategy_family": "trend_following",
        "ranking": {"field": "close_vs_sma52w_pct", "order": "desc"},
        "entry_rule": {"type": "top_n", "top_n": 15, "by": "ret_52w_pct"},
        "exit_rule": {"type": "drop_below_rank", "rank_threshold": 20},
        "market_filter": {"require_positive_trend": True},
        "risk_filters": {"require_non_null_fields": ["ret_52w_pct", "close"]},
        "costs": {"entry_cost_pct": 0.24, "exit_cost_pct": 0.24},
    }
    parent_path = tmp_path / "parent.json"
    registry_path = tmp_path / "registry.json"
    bank_path = tmp_path / "hypothesis_bank.jsonl"
    parent_path.write_text(json.dumps(parent), encoding="utf-8")
    registry_path.write_text(json.dumps({"strategies": []}), encoding="utf-8")
    axis_memory = load_axis_memory(str(tmp_path / "state"))

    strategy_id = generate_next_causal_hypothesis(
        parent_config_path=str(parent_path),
        registry_path=str(registry_path),
        hypothesis_bank_path=str(bank_path),
        weekly_columns={"ret_52w_pct", "close", "close_vs_sma52w_pct", "daily_range_pct"},
        axis_memory=axis_memory,
    )

    assert strategy_id == "HYP_DD_FIRST_AUTO002_EXPOSURE_75_V1"
    cfg = read_json(Path("configs/generated") / f"{strategy_id}.json")
    assert cfg["generation_axis"] == "exposure_reduction_partial"
    assert cfg["changed_parameters"] == ["risk_management.max_gross_exposure_pct"]
    assert cfg["strategy_overrides"]
    assert has_real_strategy_change(parent, cfg)


def test_useful_candidate_rejects_zero_trades_and_worse_drawdown():
    base = {
        "trades": 100,
        "drawdown_improvement_vs_parent_pct": 12,
        "excess_cagr_pct": 1,
        "calmar_ratio": 1,
        "parent_calmar_ratio": 0.5,
        "years_beating_spy": 5,
        "years_losing_to_spy": 4,
    }

    assert useful_candidate(base)
    assert not useful_candidate({**base, "trades": 0, "drawdown_improvement_vs_parent_pct": 100})
    assert not useful_candidate({**base, "drawdown_improvement_vs_parent_pct": -20})


def test_axis_summary_writes_expected_columns(tmp_path):
    axis_memory = load_axis_memory(str(tmp_path / "state"))
    write_axis_summary(str(tmp_path / "reports"), axis_memory)

    header = (tmp_path / "reports" / "dd_first_axis_summary.csv").read_text(encoding="utf-8").splitlines()[0].split(";")

    assert header[:4] == ["axis", "attempts", "completed_runs", "useful_candidates"]
    assert "best_drawdown" in header
    assert set(AXIS_PRIORITY).issubset({line.split(";")[0] for line in (tmp_path / "reports" / "dd_first_axis_summary.csv").read_text(encoding="utf-8").splitlines()[1:]})
