# Execution timing audit

- Rebalance: signals are mapped to first daily close strictly after signal_date (next available close).
- market_filter_failed / left_top_n: rebalance exits execute on that mapped rebalance close; signal source is prior weekly signal.
- portfolio_drawdown_guard / reduced exposure / crisis / reentry: previous engine evaluated and scaled on same daily close; strict mode evaluates prior close and executes current close.
- position_stop_loss: previous engine detected and exited on same daily close; strict mode detects prior close and exits current close.
- Default behavior: unchanged unless config execution_timing.enabled=true and mode=strict_next_close.