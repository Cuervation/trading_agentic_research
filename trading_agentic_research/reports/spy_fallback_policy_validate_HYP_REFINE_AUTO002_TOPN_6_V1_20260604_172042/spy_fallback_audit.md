# SPY fallback audit

Warning source: `backtester/signal_builder.py::_evaluate_market_filter`.
Trigger: benchmark row missing or SPY trend metrics missing/NaN.
Current `fallback=True`: allows market filter pass using `fallback_allow_if_missing_spy_metric`.
Effect: affects selection/rebalance path; false can block targets and existing engine may exit via market_filter_failed.
Current fallback total: 10.
Current outside warmup: 10.
