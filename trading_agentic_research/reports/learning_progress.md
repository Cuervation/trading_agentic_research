# Learning Progress Audit

- Runs found: 142
- Runs with audit.json: 86/142 (60.56%)
- Runs with run_manifest.json: 103/142 (72.54%)
- Indexed runs: 142
- Unique artifact signatures: 51
- Duplicate runs: 91 (64.08%)
- Ledger events: 142
- Best champion: `AUTO_002`
- Current parent: `AUTO_002`
- Aggressive champion: `EXP_030`
- Promotion/baseline candidate: `EXP_044`

## Value delivered

- aggressive_champion: 1
- defensive_secondary_candidate: 3
- duplicate_blocked: 91
- new_champion: 5
- promotion_candidate: 5
- rejected_with_learning: 32
- secondary_candidate: 5

## Repeated hypotheses

- HYP_MIX_REGIME_TREND_FOLLOWING_V1: 43
- HYP_AUTO_TIME_SERIES_MOMENTUM_SEED: 2
- HYP_AUTO_CAN_SLIM_SEED: 2
- HYP_AUTO_TREND_VOL_TARGET_SEED: 2
- HYP_MIX_CAN_SLIM__LOCAL_RET_12W_ACCELERATION_V1: 2
- HYP_REFINE_AUTO002_TOPN_10_V1: 2

## Recommendations

- Make audit.json mandatory after each backtest.
- Duplicate rate is high; block artifact signatures before follow-up decisions.
