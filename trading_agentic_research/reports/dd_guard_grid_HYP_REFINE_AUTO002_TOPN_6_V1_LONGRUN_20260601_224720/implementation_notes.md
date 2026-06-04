# Implementation Notes

- Engine touched: `backtester/execution.py`.
- Runner created: `scripts/run_dd_guard_grid_auto.py`.
- Original strategy config not modified: `HYP_REFINE_AUTO002_TOPN_6_V1`.
- Variants generated under `reports\dd_guard_grid_HYP_REFINE_AUTO002_TOPN_6_V1_LONGRUN_20260601_224720\generated_configs`.
- Individual backtests now persist normal artifacts under `runs/<run_id>/`.
- `reports/.../variant_runs/<run_id>/run_pointer.json` is only an index/pointer; `runs/` is the source of truth.
- Portfolio guard config: `risk_controls.portfolio_drawdown_guard`.
- Position stop config: `risk_controls.position_stop_loss.stop_loss_pct`.
- Portfolio drawdown = current equity / historical equity peak - 1, using data known up to current daily close.
- Reduced/crisis exposure: engine scales positions down at daily close when active, then caps future rebalances.
- Crisis exposure 0 means cash mode/liquidation to zero gross exposure in this daily-close model.
- Reentry filters use current/historical SPY daily close/SMA values only: SMA200, SMA50, SMA50 slope, cooldown, optional DD recovery.
- Limitation: fills are daily close; no intraday stop simulation. Esto NO es un stop intradiario.
- Screening used full-history equity then derived stress windows from the same real backtest; no invented metrics.
- Reproduce one run by reading `reports\dd_guard_grid_HYP_REFINE_AUTO002_TOPN_6_V1_LONGRUN_20260601_224720\grid_results.csv` -> `run_dir`, then inspect `metrics.json`, `summary.md`, `equity_curve.csv`, and `trades.csv`.
- Resume: rerun this script with the same `--output-dir`, `--resume`, and `--previous-report-dir` if applicable.
