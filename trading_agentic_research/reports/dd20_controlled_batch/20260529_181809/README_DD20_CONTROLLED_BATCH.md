# DD20 Controlled Batch

Batch de evaluación controlada para hipótesis DD20. El runner no tocó current_parent, current_baseline ni backtester.

## Resumen
- Configs corridas: 2
- Accepted candidates: 0
- Rejected candidates: 1
- No effect: 1
- Requires engine support: 1

## Hipótesis por familia
- guardrail_dynamic: 1
- spy_fallback_partial: 1
- topn_dynamic: 1

## Top 5 por CAGR con DD <= 20%
- HYP_DD20_CTRL_GUARD_DYNAMIC_12_20_V1: CAGR 9.10% | DD -19.33% | status no_effect

## Top 5 por menor drawdown
- HYP_DD20_CTRL_GUARD_DYNAMIC_12_20_V1: DD -19.33% | CAGR 9.10% | status no_effect
- HYP_DD20_CTRL_TOPN_DYNAMIC_16_8_V1: DD -23.78% | CAGR -0.09% | status rejected

## Top 5 por años ganados vs SPY
- HYP_DD20_CTRL_GUARD_DYNAMIC_12_20_V1: years won 16 | CAGR 9.10% | status no_effect
- HYP_DD20_CTRL_TOPN_DYNAMIC_16_8_V1: years won 8 | CAGR -0.09% | status rejected

## Batch Status
- batch_invalid_translation_collapse: false

## Recommendation
No accepted candidates yet. Manual review should start with the least-bad supported candidate `HYP_DD20_CTRL_GUARD_DYNAMIC_12_20_V1` and with the engine-support blockers.

## Notes
- `requires_engine_support` is used when a hypothesis depends on a field the current engine does not implement.
- This batch still compares every executed candidate against SPY and against its DD20 parent run.
- If translation collapse is detected, no candidate is recommended regardless of raw metrics.
- No promotion of baseline was performed.

