# DD20 Controlled Batch

Batch de evaluación controlada para hipótesis DD20. El runner no tocó current_parent, current_baseline ni backtester.

## Resumen
- Configs corridas: 0
- Accepted candidates: 0
- Rejected candidates: 0
- No effect: 0
- Requires engine support: 12

## Hipótesis por familia
- dd_compression: 3
- guardrail_dynamic: 3
- spy_fallback_partial: 3
- topn_dynamic: 3

## Top 5 por CAGR con DD <= 20%
- HYP_DD20_CTRL_DD_COMPRESS_15_35_V1: CAGR 0.00% | DD 0.00% | status 
- HYP_DD20_CTRL_DD_COMPRESS_16_40_V1: CAGR 0.00% | DD 0.00% | status 
- HYP_DD20_CTRL_DD_COMPRESS_17_45_V1: CAGR 0.00% | DD 0.00% | status 
- HYP_DD20_CTRL_GUARD_DYNAMIC_12_20_V1: CAGR 0.00% | DD 0.00% | status 
- HYP_DD20_CTRL_GUARD_DYNAMIC_13_25_V1: CAGR 0.00% | DD 0.00% | status 

## Top 5 por menor drawdown
- HYP_DD20_CTRL_DD_COMPRESS_15_35_V1: DD 0.00% | CAGR 0.00% | status 
- HYP_DD20_CTRL_DD_COMPRESS_16_40_V1: DD 0.00% | CAGR 0.00% | status 
- HYP_DD20_CTRL_DD_COMPRESS_17_45_V1: DD 0.00% | CAGR 0.00% | status 
- HYP_DD20_CTRL_GUARD_DYNAMIC_12_20_V1: DD 0.00% | CAGR 0.00% | status 
- HYP_DD20_CTRL_GUARD_DYNAMIC_13_25_V1: DD 0.00% | CAGR 0.00% | status 

## Top 5 por años ganados vs SPY
- HYP_DD20_CTRL_DD_COMPRESS_15_35_V1: years won 0 | CAGR 0.00% | status 
- HYP_DD20_CTRL_DD_COMPRESS_16_40_V1: years won 0 | CAGR 0.00% | status 
- HYP_DD20_CTRL_DD_COMPRESS_17_45_V1: years won 0 | CAGR 0.00% | status 
- HYP_DD20_CTRL_GUARD_DYNAMIC_12_20_V1: years won 0 | CAGR 0.00% | status 
- HYP_DD20_CTRL_GUARD_DYNAMIC_13_25_V1: years won 0 | CAGR 0.00% | status 

## Recommendation
All candidate families need engine support or translation follow-up before meaningful batch evaluation.

## Notes
- `requires_engine_support` is used when a hypothesis depends on a field the current engine does not implement.
- This batch still compares every executed candidate against SPY and against its DD20 parent run.
- No promotion of baseline was performed.

