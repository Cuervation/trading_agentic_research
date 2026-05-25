from scripts.run_dd_first_autonomous_daemon import is_champion_candidate, select_champions


def row(strategy_id, cagr, dd, improvement, calmar):
    return {
        "run_id": f"RUN_{strategy_id}",
        "strategy_id": strategy_id,
        "strategy_cagr_pct": cagr,
        "spy_cagr_pct": 6.8,
        "excess_cagr_pct": cagr - 6.8,
        "strategy_max_drawdown_pct": dd,
        "parent_max_drawdown_pct": -54.64,
        "drawdown_improvement_vs_parent_pct": improvement,
        "calmar_ratio": calmar,
        "years_beating_spy": 20,
        "years_losing_to_spy": 8,
        "trades": 3500,
    }


def test_champion_selection_keeps_separate_objectives():
    rows = [
        row("DEF", 13, -31, 43, 0.41),
        row("BAL", 16, -36, 34, 0.44),
        row("RET", 19, -41, 25, 0.46),
    ]

    champions = select_champions(rows)

    assert is_champion_candidate(rows[0])
    assert champions["dd_min_champion"]["strategy_id"] == "DEF"
    assert champions["balanced_dd_champion"]["strategy_id"] in {"DEF", "BAL"}
    assert champions["return_with_dd_guard_champion"]["strategy_id"] == "RET"
