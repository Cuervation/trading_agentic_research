import json
from pathlib import Path

import pandas as pd

from backtester.signal_builder import build_momentum_trend_signals
from scripts.research.feature_space_expansion_factory import generate_feature_space_hypotheses


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def append_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


def minimal_hypothesis(hid: str, overrides: dict) -> dict:
    return {
        "hypothesis_id": hid,
        "family": "feature_space_momentum",
        "claim": "existing",
        "causal_mechanism": "existing",
        "bibliography_basis": [{"source_id": "test", "title": "test"}],
        "empirical_basis": [{"run_id": "AUTO_002", "reason": "test"}],
        "features_required": ["close"],
        "status": "candidate",
        "required_spy_comparison": "monthly_and_yearly",
        "axis": "feature_space_ranking",
        "falsification_rule": "test",
        "strategy_overrides": overrides,
    }


def setup_feature_state(tmp_path: Path) -> tuple[Path, Path, Path]:
    state = tmp_path / "state"
    bank = tmp_path / "bibliography" / "hypothesis_bank.jsonl"
    parent = tmp_path / "configs" / "generated" / "parent.json"
    weekly = tmp_path / "data" / "weekly.csv"
    write_json(state / "current_parent.json", {
        "current_parent_run_id": "AUTO_002",
        "current_parent_hypothesis_id": "HYP_AUTO_TIME_SERIES_MOMENTUM_SEED",
    })
    write_json(parent, {
        "strategy_id": "HYP_AUTO_TIME_SERIES_MOMENTUM_SEED",
        "ranking": {"field": "close_vs_sma52w_pct", "order": "desc"},
        "entry_rule": {"top_n": 8},
        "exit_rule": {"rank_threshold": 20},
    })
    weekly.parent.mkdir(parents=True, exist_ok=True)
    weekly.write_text(
        "date,ticker,close,ret_13w_pct,ret_26w_pct,ret_52w_pct,channel_r2,channel_slope_pct,close_vs_sma20w_pct,close_vs_sma52w_pct,close_sma_50_slope_5d_pct,distance_to_channel_lower_pct\n",
        encoding="utf-8",
    )
    write_json(state / "data_paths_resolved.json", {"weekly_file": str(weekly)})
    bank.parent.mkdir(parents=True, exist_ok=True)
    bank.write_text("", encoding="utf-8")
    return state, bank, parent


def test_signal_builder_respects_ascending_ranking_order():
    df = pd.DataFrame([
        {"date": "2026-01-31", "ticker": "SPY", "close": 1, "distance_to_channel_lower_pct": 0, "spy_close_vs_sma50_pct": 1},
        {"date": "2026-01-31", "ticker": "AAA", "close": 1, "distance_to_channel_lower_pct": 2, "spy_close_vs_sma50_pct": 1},
        {"date": "2026-01-31", "ticker": "BBB", "close": 1, "distance_to_channel_lower_pct": 10, "spy_close_vs_sma50_pct": 1},
    ])
    signals = build_momentum_trend_signals(df, {
        "ranking": {"field": "distance_to_channel_lower_pct", "order": "asc"},
        "entry_rule": {"top_n": 1},
        "exit_rule": {"rank_threshold": 2},
        "market_filter": {"require_positive_trend": True},
    })
    selected = signals[signals["selected_top_n"]]
    assert selected.iloc[0]["ticker"] == "AAA"


def test_signal_builder_applies_risk_filter_conditions_before_ranking():
    df = pd.DataFrame([
        {"date": "2026-01-31", "ticker": "SPY", "close": 1, "ret_26w_pct": 0, "close_vs_sma20w_pct": 0, "spy_close_vs_sma50_pct": 1},
        {"date": "2026-01-31", "ticker": "AAA", "close": 1, "ret_26w_pct": 50, "close_vs_sma20w_pct": -1, "spy_close_vs_sma50_pct": 1},
        {"date": "2026-01-31", "ticker": "BBB", "close": 1, "ret_26w_pct": 20, "close_vs_sma20w_pct": 5, "spy_close_vs_sma50_pct": 1},
    ])
    signals = build_momentum_trend_signals(df, {
        "ranking": {"field": "ret_26w_pct", "order": "desc"},
        "entry_rule": {"top_n": 1},
        "exit_rule": {"rank_threshold": 2},
        "risk_filters": {
            "require_non_null_fields": ["ret_26w_pct", "close_vs_sma20w_pct", "close"],
            "conditions": [{"field": "close_vs_sma20w_pct", "operator": ">", "value": 0, "enabled_if_field_exists": True}],
        },
        "market_filter": {"require_positive_trend": True},
    })
    assert set(signals["ticker"]) == {"BBB"}
    assert signals.iloc[0]["selected_top_n"] is True or bool(signals.iloc[0]["selected_top_n"])


def test_feature_space_v2_generates_composite_when_pure_rank_ids_exist(tmp_path):
    state, bank, parent = setup_feature_state(tmp_path)
    # Simulate the current exhaustion mode: all pure ranking ids already exist.
    pure_ids = [
        "HYP_FSPACE_AUTO_002_RANK_CHANNEL_R2_V1",
        "HYP_FSPACE_AUTO_002_RANK_CHANNEL_SLOPE_PCT_V1",
        "HYP_FSPACE_AUTO_002_RANK_CLOSE_SMA_50_SLOPE_5D_PCT_V1",
        "HYP_FSPACE_AUTO_002_RANK_CLOSE_VS_SMA20W_PCT_V1",
        "HYP_FSPACE_AUTO_002_RANK_DISTANCE_TO_CHANNEL_LOWER_PCT_V1",
        "HYP_FSPACE_AUTO_002_RANK_RET_26W_PCT_V1",
        "HYP_FSPACE_AUTO_002_RANK_RET_52W_PCT_V1",
    ]
    rows = []
    for hid in pure_ids:
        field = hid.replace("HYP_FSPACE_AUTO_002_RANK_", "").replace("_V1", "").lower()
        # exact field mapping is not important here; these rows only reserve ids
        rows.append(minimal_hypothesis(hid, {"ranking": {"field": field, "order": "desc"}}))
    append_jsonl(bank, rows)

    result = generate_feature_space_hypotheses(
        parent_strategy_config_path=parent,
        hypothesis_bank_path=bank,
        state_dir=state,
        max_new=5,
        reason="test_exhausted_simple_rankings",
    )

    assert result["generated"] >= 1
    assert any(layer in {"rank_confirmation", "rank_market_filter", "rank_topn", "rank_exit"} for layer in result["generation_layers"])
    generated_rows = [json.loads(line) for line in bank.read_text(encoding="utf-8").splitlines() if line.strip()]
    new_rows = [row for row in generated_rows if row["hypothesis_id"] in result["hypotheses"]]
    assert new_rows
    assert any("risk_filters" in row["strategy_overrides"] and row["strategy_overrides"]["risk_filters"].get("conditions") for row in new_rows)
