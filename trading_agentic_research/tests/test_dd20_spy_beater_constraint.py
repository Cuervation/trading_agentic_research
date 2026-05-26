import json
from pathlib import Path

import pandas as pd

from backtester.dd20_spy_beater import evaluate_dd20_spy_beater_run, valid_dd20_rows


def _write_run(root: Path, run_id: str, *, cagr: float, spy_cagr: float, dd: float, trades: int, years_w: int = 15, years_l: int = 10):
    run = root / run_id
    run.mkdir(parents=True)
    (run / "run_manifest.json").write_text(json.dumps({"strategy_id": run_id}), encoding="utf-8")
    (run / "metrics.json").write_text(json.dumps({"strategy": {"cagr_pct": cagr, "max_drawdown_pct": dd}, "spy": {"cagr_pct": spy_cagr, "max_drawdown_pct": -50}, "costs": {"applied": True, "cost_per_side_pct": 0.24}}), encoding="utf-8")
    (run / "spy_comparison_summary.json").write_text(json.dumps({"strategy_cagr_pct": cagr, "spy_cagr_pct": spy_cagr, "excess_cagr_pct": cagr - spy_cagr, "years_beating_spy": years_w, "years_losing_to_spy": years_l, "months_beating_spy": 180, "months_losing_to_spy": 120}), encoding="utf-8")
    pd.DataFrame({"date": ["2020-01-01"], "equity": [100]}).to_csv(run / "equity_curve.csv", index=False)
    pd.DataFrame({"x": [1]}).to_csv(run / "spy_comparison_daily.csv", index=False)
    pd.DataFrame({"x": [1]}).to_csv(run / "spy_comparison_monthly.csv", index=False)
    pd.DataFrame({"x": [1]}).to_csv(run / "spy_comparison_yearly.csv", index=False)
    pd.DataFrame({"gross_return_pct": [1.0] * trades, "net_return_pct": [0.5] * trades}).to_csv(run / "trades.csv", index=False)
    return run


def test_dd20_rejects_high_cagr_when_drawdown_breaches_limit(tmp_path):
    run = _write_run(tmp_path, "BAD_DD", cagr=30, spy_cagr=8, dd=-21, trades=3000)

    audit = evaluate_dd20_spy_beater_run(run)

    assert audit["decision"] == "rejected"
    assert audit["dd20_spy_beater"]["passes_dd20"] is False
    assert "max_drawdown_breaches_dd20" in audit["dd20_spy_beater"]["rejection_reason"]


def test_dd20_valid_candidate_requires_spy_and_trade_constraints(tmp_path):
    run = _write_run(tmp_path, "GOOD", cagr=11, spy_cagr=8, dd=-19.5, trades=3000, years_w=16, years_l=10)

    audit = evaluate_dd20_spy_beater_run(run)

    assert audit["decision"] in {"valid_candidate", "strong_candidate", "excellent_candidate"}
    assert valid_dd20_rows([audit["dd20_spy_beater"]])
