# Learning Progress Audit

- Runs found: 135
- Runs with audit.json: 79/135 (58.52%)
- Runs with run_manifest.json: 96/135 (71.11%)
- Indexed runs: 135
- Unique artifact signatures: 47
- Duplicate runs: 88 (65.19%)
- Ledger events: 135
- Best champion: `AUTO_002`
- Current parent: `AUTO_002`
- Aggressive champion: `EXP_030`
- Promotion/baseline candidate: `AUTO_092`

## Value delivered

- aggressive_champion: 1
- defensive_secondary_candidate: 3
- duplicate_blocked: 88
- new_champion: 5
- promotion_candidate: 4
- rejected_with_learning: 30
- secondary_candidate: 4

## Repeated hypotheses

- HYP_MIX_REGIME_TREND_FOLLOWING_V1: 43
- HYP_AUTO_TIME_SERIES_MOMENTUM_SEED: 2
- HYP_AUTO_CAN_SLIM_SEED: 2
- HYP_AUTO_TREND_VOL_TARGET_SEED: 2
- HYP_MIX_CAN_SLIM__LOCAL_RET_12W_ACCELERATION_V1: 2

## Recommendations

- Make audit.json mandatory after each backtest.
- Duplicate rate is high; block artifact signatures before follow-up decisions.
