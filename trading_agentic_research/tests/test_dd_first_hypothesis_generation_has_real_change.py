import json
from pathlib import Path

from scripts.governance import has_real_strategy_change
from scripts.run_dd_first_autofix_loop import ensure_initial_hypotheses, read_json


def test_dd_first_hypothesis_generation_has_real_change(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    parent = {
        "strategy_id": "HYP_AUTO_TIME_SERIES_MOMENTUM_SEED",
        "hypothesis_id": "HYP_AUTO_TIME_SERIES_MOMENTUM_SEED",
        "strategy_family": "trend_following",
        "bibliography_basis": [{"source_id": "SRC_TIME_SERIES_MOMENTUM_SEED"}],
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

    ids = ensure_initial_hypotheses(
        parent_config_path=str(parent_path),
        registry_path=str(registry_path),
        hypothesis_bank_path=str(bank_path),
        weekly_columns={"ret_52w_pct", "close", "channel_r2", "daily_range_pct", "close_vs_sma52w_pct"},
    )

    assert len(ids) == 3
    for strategy_id in ids:
        cfg = read_json(Path("configs/generated") / f"{strategy_id}.json")
        assert cfg["strategy_family"] == "dd_first_drawdown_control"
        assert cfg["changed_parameters"]
        assert has_real_strategy_change(parent, cfg)
