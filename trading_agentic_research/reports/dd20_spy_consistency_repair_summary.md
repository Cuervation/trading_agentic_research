# DD20 SPY Consistency Repair Summary

## Valid candidates

- none

## Best near-candidate

- `HYP_DD20_SPY_DYN_80_50_20_0_EQUITY_GUARD_18_10_V1`: CAGR 8.2043%, DD -19.9052%, years W/L 14/14, gap 0.4337.

## Comparison against `HYP_DD20_SPY_DYN_65_45_25_0_V1`

- Best repair: CAGR 8.2043%, DD -19.9052%, years W/L 14/14.

## All repair strategies

| strategy_id | CAGR | SPY CAGR | DD | years W/L | decision | gap | reason |
|:---|---:|---:|---:|:---|:---|---:|:---|
| `HYP_DD20_SPY_DYN_80_50_20_0_EQUITY_GUARD_18_10_V1` | 8.2043% | 6.8025% | -19.9052% | 14/14 | rejected | 0.4337 | insufficient_trades:1699<3000 |
| `HYP_DD20_SPY_DYN_75_50_25_0_EQUITY_GUARD_18_10_V1` | 7.7560% | 6.8025% | -18.6770% | 13/15 | rejected | 2.4303 | insufficient_trades:1709<3000; loses_more_years_than_beats:13<15 |
| `HYP_DD20_SPY_DYN_65_50_25_0_V1` | 10.4264% | 6.8025% | -24.5345% | 16/12 | rejected | 45.5527 | insufficient_trades:2377<3000; max_drawdown_breaches_dd20:-24.534503<-20.000000 |
| `HYP_DD20_SPY_DYN_70_45_25_0_PARTIAL_25_33_V1` | 10.7075% | 6.8025% | -24.8247% | 16/12 | rejected | 48.4163 | insufficient_trades:2492<3000; max_drawdown_breaches_dd20:-24.824700<-20.000000 |
| `HYP_DD20_SPY_DYN_70_45_25_0_V1` | 10.7954% | 6.8025% | -24.8247% | 16/12 | rejected | 48.4597 | insufficient_trades:2362<3000; max_drawdown_breaches_dd20:-24.824700<-20.000000 |
| `HYP_DD20_SPY_DYN_70_50_25_0_V1` | 11.0358% | 6.8025% | -25.6445% | 16/12 | rejected | 56.6570 | insufficient_trades:2363<3000; max_drawdown_breaches_dd20:-25.644466<-20.000000 |
| `HYP_DD20_SPY_DYN_70_50_20_0_V1` | 11.0784% | 6.8025% | -25.6445% | 16/12 | rejected | 56.6573 | insufficient_trades:2362<3000; max_drawdown_breaches_dd20:-25.644466<-20.000000 |
| `HYP_DD20_SPY_DYN_75_45_25_0_PARTIAL_25_33_V1` | 11.3037% | 6.8025% | -25.9450% | 16/12 | rejected | 59.6232 | insufficient_trades:2480<3000; max_drawdown_breaches_dd20:-25.944991<-20.000000 |
| `HYP_DD20_SPY_DYN_75_45_25_0_V1` | 11.3996% | 6.8025% | -25.9450% | 16/12 | rejected | 59.6656 | insufficient_trades:2353<3000; max_drawdown_breaches_dd20:-25.944991<-20.000000 |
| `HYP_DD20_SPY_DYN_80_45_25_0_V1` | 11.9974% | 6.8025% | -27.0634% | 17/11 | rejected | 70.8528 | insufficient_trades:2343<3000; max_drawdown_breaches_dd20:-27.063377<-20.000000 |
