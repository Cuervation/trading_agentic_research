# DD20 Pipeline Support Audit

No backtests were run. This is preflight only.

## Summary
- total_hypotheses: 12
- runnable_hypotheses: 3
- requires_engine_support: 6
- blocked_hypotheses: 9

## Families
- dd_compression: 3
- guardrail_dynamic: 3
- spy_fallback_partial: 3
- topn_dynamic: 3

## Why spy_fallback_partial did not run
- HYP_DD20_CTRL_SPY_FALLBACK_25_V1: blocked — spy_fallback_partial_pct is not supported by the current backtester; requested value=None.
- HYP_DD20_CTRL_SPY_FALLBACK_50_V1: blocked — spy_fallback_partial_pct is not supported by the current backtester; requested value=None.
- HYP_DD20_CTRL_SPY_FALLBACK_75_V1: blocked — spy_fallback_partial_pct is not supported by the current backtester; requested value=None.

## Next engine file for SPY fallback
- `backtester/execution.py` is the likely implementation point because cash/exposure allocation happens there.
- `backtester/signal_builder.py` may also need signal-level support if fallback is regime-gated by SPY features.
