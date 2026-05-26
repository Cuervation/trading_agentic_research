from backtester.dd20_spy_beater import build_dd20_summary_markdown, ranked_rows


def test_dd20_report_ranks_only_valid_candidates():
    rows = [
        {"run_id": "bad", "strategy_id": "BAD", "cagr": 20, "spy_cagr": 8, "excess_cagr": 12, "max_drawdown": -25, "dd_limit": -20, "passes_dd20": False, "beats_spy_cagr": True, "years_beating_spy": 20, "years_losing_to_spy": 8, "months_beating_spy": 1, "months_losing_to_spy": 1, "calmar": 0.8, "trades": 4000, "decision": "rejected", "rejection_reason": "max_drawdown_breaches_dd20"},
        {"run_id": "good", "strategy_id": "GOOD", "cagr": 10, "spy_cagr": 8, "excess_cagr": 2, "max_drawdown": -19, "dd_limit": -20, "passes_dd20": True, "beats_spy_cagr": True, "years_beating_spy": 16, "years_losing_to_spy": 12, "months_beating_spy": 1, "months_losing_to_spy": 1, "calmar": 0.52, "trades": 3000, "decision": "excellent_candidate", "rejection_reason": ""},
    ]

    ranked = ranked_rows(rows)
    good = next(r for r in ranked if r["strategy_id"] == "GOOD")
    bad = next(r for r in ranked if r["strategy_id"] == "BAD")
    md = build_dd20_summary_markdown(rows)

    assert good["rank_under_constraint"] == 1
    assert bad["rank_under_constraint"] == ""
    assert "GOOD" in md
