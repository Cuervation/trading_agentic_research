import json
from pathlib import Path

import pandas as pd

from backtester.dd_first import DD_FIRST_COLUMNS
from scripts.summarize_dd_first import main as summarize_main


def write_audited_run(run_dir: Path):
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / 'metrics.json').write_text(json.dumps({'strategy': {'cagr_pct': 12, 'max_drawdown_pct': -18}, 'spy': {'cagr_pct': 8, 'max_drawdown_pct': -25}, 'costs': {'applied': True, 'cost_per_side_pct': 0.24}, 'diagnostics': {'warnings': []}}), encoding='utf-8')
    (run_dir / 'spy_comparison_summary.json').write_text(json.dumps({'strategy_cagr_pct': 12, 'spy_cagr_pct': 8, 'excess_cagr_pct': 4, 'months_beating_spy': 10, 'months_losing_to_spy': 5, 'years_beating_spy': 3, 'years_losing_to_spy': 1}), encoding='utf-8')
    pd.DataFrame({'ticker': ['A'] * 60, 'gross_return_pct': [2.0] * 60, 'net_return_pct': [1.52] * 60}).to_csv(run_dir / 'trades.csv', index=False, sep=';', decimal=',')
    (run_dir / 'audit.json').write_text(json.dumps({'dd_first': {column: '' for column in DD_FIRST_COLUMNS} | {'run_id': run_dir.name, 'strategy_id': 'DD_TEST', 'dd_first_decision': 'accepted_for_followup'}}), encoding='utf-8')


def test_dd_first_summary_writes_expected_columns(tmp_path, monkeypatch):
    runs = tmp_path / 'runs'
    output = tmp_path / 'reports' / 'dd_first_summary.csv'
    write_audited_run(runs / 'DD_RUN')
    monkeypatch.setattr('sys.argv', ['summarize_dd_first.py', '--runs-dir', str(runs), '--output', str(output)])

    assert summarize_main() == 0

    header = output.read_text(encoding='utf-8-sig').splitlines()[0].split(';')
    assert header == DD_FIRST_COLUMNS
