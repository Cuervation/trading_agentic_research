import json
from pathlib import Path

import pandas as pd


def write_dd_run(run_dir: Path, *, cagr=12.0, spy_cagr=8.0, dd=-15.0, trades=80):
    run_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({'date': pd.date_range('2020-01-31', periods=6, freq='ME'), 'equity': [100, 106, 104, 115, 117, 100 + cagr]}).to_csv(run_dir / 'equity_curve.csv', index=False, sep=';', decimal=',')
    pd.DataFrame({'ticker': [f'T{i}' for i in range(trades)], 'gross_return_pct': [2.0] * trades, 'net_return_pct': [1.52] * trades}).to_csv(run_dir / 'trades.csv', index=False, sep=';', decimal=',')
    (run_dir / 'metrics.json').write_text(json.dumps({'strategy': {'cagr_pct': cagr, 'max_drawdown_pct': dd}, 'spy': {'cagr_pct': spy_cagr, 'max_drawdown_pct': -25.0}, 'diagnostics': {'warnings': []}, 'costs': {'applied': True, 'cost_per_side_pct': 0.24}}), encoding='utf-8')
    for name in ['spy_comparison_daily.csv', 'spy_comparison_monthly.csv', 'spy_comparison_yearly.csv']:
        pd.DataFrame({'winner': ['strategy', 'spy']}).to_csv(run_dir / name, index=False, sep=';', decimal=',')
    (run_dir / 'spy_comparison_summary.json').write_text(json.dumps({'strategy_cagr_pct': cagr, 'spy_cagr_pct': spy_cagr, 'excess_cagr_pct': cagr - spy_cagr, 'months_beating_spy': 15, 'months_losing_to_spy': 7, 'years_beating_spy': 4, 'years_losing_to_spy': 2}), encoding='utf-8')
    (run_dir / 'run_manifest.json').write_text(json.dumps({'run_id': run_dir.name, 'strategy_id': 'DD_TEST', 'parent_run_id': 'PARENT', 'parent_strategy_id': 'BASE'}), encoding='utf-8')


def test_dd_first_does_not_move_parent(tmp_path):
    from backtester.validation import audit_run_folder_dd_first

    parent = tmp_path / 'PARENT'
    child = tmp_path / 'CHILD'
    write_dd_run(parent, cagr=10.0, dd=-30.0, trades=100)
    write_dd_run(child, cagr=12.0, dd=-15.0, trades=100)

    audit = audit_run_folder_dd_first(child, parent_run_dir=parent, min_trades=50)

    assert audit['dd_first_decision'] in {'accepted_for_followup', 'promoted_candidate'}
    assert audit['can_move_parent'] is False
    assert audit['can_promote_baseline'] is False
