from scripts.dd20_adaptive_strategy_generator import classify_row, generate_next_dd20_strategies


def _frontier():
    return {
        "best_valid_by_cagr": {
            "strategy_id": "HYP_DD20_EXP_SL11_TOPN8_WHEN_GUARD_V1",
            "cagr": 10.5412,
            "spy_cagr": 6.802475,
            "max_drawdown": -19.6588,
            "trades": 2354,
            "years_beating_spy": 16,
            "years_losing_to_spy": 12,
        },
        "all_rows": [],
    }


def _low_trade_frontier():
    return {
        "best_near_valid_low_trades": {
            "strategy_id": "LOW_TRADES",
            "cagr": 9.6,
            "spy_cagr": 6.8,
            "max_drawdown": -19.3,
            "trades": 900,
            "years_beating_spy": 17,
            "years_losing_to_spy": 11,
        },
        "all_rows": [],
    }


def test_generates_cagr_repair_when_valid_candidate_exists():
    specs = generate_next_dd20_strategies(_frontier(), batch_size=5)

    assert [s["strategy_id"] for s in specs] == [
        "HYP_DD20_CAGR_SL11_TOPN8_GUARD18_10_V1",
        "HYP_DD20_CAGR_SL11_TOPN10_GUARD18_10_V1",
        "HYP_DD20_CAGR_SL12_TOPN8_GUARD18_10_V1",
        "HYP_DD20_CAGR_SL12_TOPN10_GUARD18_10_V1",
        "HYP_DD20_CAGR_SL10P5_TOPN8_GUARD18_10_V1",
    ]
    assert {s["generation_axis"] for s in specs} == {"cagr_repair_under_dd20"}
    assert all("trailing_stop_pct" not in s["risk_management"] for s in specs)


def test_generates_trade_count_repair_only_when_trades_are_below_1000():
    specs = generate_next_dd20_strategies(_low_trade_frontier(), batch_size=5)

    assert {s["generation_axis"] for s in specs} == {"trade_count_repair_around_sl10"}


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

    row["trades"] = 999

    assert classify_row(row) == "near_valid_low_trades"


def test_generator_skips_duplicate_strategy_id_and_config_hash():
    first = generate_next_dd20_strategies(_frontier(), batch_size=1)[0]
    frontier = _frontier()
    frontier["all_rows"] = [{"strategy_id": first["strategy_id"], "config_hash": first["config_hash"]}]

    specs = generate_next_dd20_strategies(frontier, batch_size=5)

    assert first["strategy_id"] not in {s["strategy_id"] for s in specs}
    assert first["config_hash"] not in {s["config_hash"] for s in specs}
