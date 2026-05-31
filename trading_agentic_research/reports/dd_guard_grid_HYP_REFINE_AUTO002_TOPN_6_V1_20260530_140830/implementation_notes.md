# Implementation Notes

- Engine touched: `backtester/execution.py`.
- Runner created: `scripts/run_dd_guard_grid_auto.py`.
- Original strategy config not modified: `HYP_REFINE_AUTO002_TOPN_6_V1`.
- Variants generated only under `reports\dd_guard_grid_HYP_REFINE_AUTO002_TOPN_6_V1_20260530_140830\generated_configs`.
- Portfolio guard config: `risk_controls.portfolio_drawdown_guard`.
- Position stop config: `risk_controls.position_stop_loss.stop_loss_pct`.
- Portfolio drawdown = current equity / historical equity peak - 1, using data known up to current daily close.
- Reduced/crisis exposure: engine scales positions down at daily close when active, then caps future rebalances.
- Crisis exposure 0 means cash mode/liquidation to zero gross exposure in this daily-close model.
- Reentry filters use current/historical SPY daily close/SMA values only: SMA200, SMA50, SMA50 slope, cooldown, optional DD recovery.
- Limitation: fills are daily close; no intraday stop simulation. Esto NO es un stop intradiario.
- Screening used full-history equity then derived stress windows from the same real backtest; no invented metrics.
