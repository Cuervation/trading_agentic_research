from scripts.dd20_adaptive_strategy_generator import expand_generation_space, generate_next_dd20_strategies


def _frontier():
    return {
        "best_valid_by_cagr": {"strategy_id": "HYP_DD20_EXP_SL11_TOPN8_WHEN_GUARD_V1", "cagr": 10.5412, "spy_cagr": 6.8, "max_drawdown": -19.6588, "trades": 2354, "years_beating_spy": 16, "years_losing_to_spy": 12},
        "all_rows": [
            {"strategy_id": "HYP_DD20_ADAPT_SL10_GUARD18_12_V1"},
            {"strategy_id": "HYP_DD20_ADAPT_SL10_REDUCED_20_V1"},
            {"strategy_id": "HYP_DD20_ADAPT_SL10_REDUCED_25_V1"},
            {"strategy_id": "HYP_DD20_ADAPT_SL10_COOLDOWN_3_V1"},
            {"strategy_id": "HYP_DD20_ADAPT_SL10_TOPN5_WHEN_GUARD_V1"},
        ],
    }


def test_expand_generation_space_adds_non_duplicate_causal_specs():
    axis_memory = expand_generation_space(_frontier(), {"cooldown_axes": ["trailing"], "exhausted_axes": []})

    specs = generate_next_dd20_strategies(_frontier(), axis_memory, batch_size=5)

    assert specs
    assert all(s["strategy_id"].startswith("HYP_DD20_CAGR_") for s in specs)
    assert len({s["strategy_id"] for s in specs}) == len(specs)
    assert all("trailing_stop_pct" not in s["risk_management"] for s in specs)


def test_expand_generation_space_includes_expected_topn_and_guard_families():
    axis_memory = expand_generation_space(_frontier(), {})
    ids = {s["strategy_id"] for s in axis_memory["expanded_specs"]}

    assert "HYP_DD20_CAGR_SL11_TOPN10_GUARD18_10_V1" in ids
    assert "HYP_DD20_CAGR_SL12_TOPN8_GUARD18_10_V1" in ids
    assert "HYP_DD20_CAGR_SL10P5_TOPN8_GUARD18_10_V1" in ids
    assert "HYP_DD20_CAGR_DYN8550200_SL11_TOPN8_V1" in ids
    assert "HYP_DD20_CAGR_SL12_TOPN12_GUARD18_12_V1" in ids
