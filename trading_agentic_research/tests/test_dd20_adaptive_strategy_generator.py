from scripts.dd20_adaptive_strategy_generator import classify_row, generate_next_dd20_strategies


def _frontier():
    return {
        "best_near_valid_low_trades": {
            "strategy_id": "HYP_DD20_STOP_DYN8050200_GUARD1810_SL10_V1",
            "cagr": 9.675868,
            "spy_cagr": 6.802475,
            "max_drawdown": -19.325183,
            "trades": 2345,
            "years_beating_spy": 17,
            "years_losing_to_spy": 11,
        },
        "all_rows": [],
    }


def test_generates_trade_count_repair_around_sl10_when_trades_are_short():
    specs = generate_next_dd20_strategies(_frontier(), batch_size=5)

    assert [s["strategy_id"] for s in specs] == [
        "HYP_DD20_ADAPT_SL10_GUARD18_12_V1",
        "HYP_DD20_ADAPT_SL10_REDUCED_20_V1",
        "HYP_DD20_ADAPT_SL10_REDUCED_25_V1",
        "HYP_DD20_ADAPT_SL10_COOLDOWN_3_V1",
        "HYP_DD20_ADAPT_SL10_TOPN5_WHEN_GUARD_V1",
    ]
    assert {s["generation_axis"] for s in specs} == {"trade_count_repair_around_sl10"}
    assert all("trailing_stop_pct" not in s["risk_management"] for s in specs)


def test_no_trailing_generated_when_trailing_axis_is_cooling_down():
    specs = generate_next_dd20_strategies(_frontier(), {"cooldown_axes": ["trailing"], "exhausted_axes": []}, batch_size=5)

    assert all("TRAIL" not in s["strategy_id"] for s in specs)


def test_near_valid_is_not_classified_as_valid():
    row = {
        "cagr": 9.6,
        "spy_cagr": 6.8,
        "max_drawdown": -19.3,
        "trades": 2345,
        "years_beating_spy": 17,
        "years_losing_to_spy": 11,
    }

    assert classify_row(row) == "near_valid_low_trades"


def test_generator_skips_duplicate_strategy_id_and_config_hash():
    first = generate_next_dd20_strategies(_frontier(), batch_size=1)[0]
    frontier = _frontier()
    frontier["all_rows"] = [{"strategy_id": first["strategy_id"], "config_hash": first["config_hash"]}]

    specs = generate_next_dd20_strategies(frontier, batch_size=5)

    assert first["strategy_id"] not in {s["strategy_id"] for s in specs}
    assert first["config_hash"] not in {s["config_hash"] for s in specs}
