import csv

from scripts.dd20_adaptive_strategy_generator import build_frontier_memory


def test_detects_sl10_as_best_near_valid_low_trades(tmp_path):
    reports = tmp_path / "reports"
    state = tmp_path / "state"
    runs = tmp_path / "runs"
    reports.mkdir()
    rows = [
        {
            "run_id": "r1",
            "strategy_id": "HYP_DD20_STOP_DYN8050200_GUARD1810_SL10_V1",
            "cagr": "9.675868",
            "spy_cagr": "6.802475",
            "max_drawdown": "-19.325183",
            "calmar": "0.50",
            "trades": "2345",
            "years_beating_spy": "17",
            "years_losing_to_spy": "11",
        },
        {
            "run_id": "r2",
            "strategy_id": "OTHER",
            "cagr": "7",
            "spy_cagr": "6.8",
            "max_drawdown": "-19",
            "calmar": "0.36",
            "trades": "1200",
            "years_beating_spy": "14",
            "years_losing_to_spy": "14",
        },
    ]
    with (reports / "dd20_stop_trailing_repair_summary.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=rows[0].keys(), delimiter=";")
        writer.writeheader()
        writer.writerows(rows)

    memory = build_frontier_memory(reports_dir=reports, runs_dir=runs, state_dir=state)

    assert memory["best_near_valid_low_trades"]["strategy_id"] == "HYP_DD20_STOP_DYN8050200_GUARD1810_SL10_V1"
    assert memory["next_axis_recommendation"] == "trade_count_repair_around_sl10"
