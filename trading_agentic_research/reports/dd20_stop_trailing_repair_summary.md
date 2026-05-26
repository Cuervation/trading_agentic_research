# DD20 Stop/Trailing Repair Summary

## Valid candidates

- none

## Best near-valid

`HYP_DD20_STOP_DYN8050200_GUARD1810_SL10_V1` CAGR 9.6759%, DD -19.3252%, trades 2345, years 17/11, decision near_valid_useful

## Best with DD < 20

- Highest CAGR under DD20: `HYP_DD20_STOP_DYN8050200_GUARD1810_SL10_V1` CAGR 9.6759%, DD -19.3252%, trades 2345, years 17/11, decision near_valid_useful
- Best trade count under DD20: `HYP_DD20_STOP_DYN8050200_GUARD1810_SL10_V1` CAGR 9.6759%, DD -19.3252%, trades 2345, years 17/11, decision near_valid_useful

## Comparison vs `HYP_DD20_SPY_DYN_80_50_20_0_EQUITY_GUARD_18_10_V1`

- Base reference is the prior near-valid: CAGR 8.2043%, DD -19.9052%, years W/L 14/14, trades 1699.
- Best stop/trailing repair: `HYP_DD20_STOP_DYN8050200_GUARD1810_SL10_V1` CAGR 9.6759%, DD -19.3252%, trades 2345, years 17/11, decision near_valid_useful

## Exit mechanism readout

- Stop loss: best `HYP_DD20_STOP_DYN8050200_GUARD1810_SL10_V1` CAGR 9.6759%, DD -19.3252%, trades 2345, years 17/11, decision near_valid_useful.
- Trailing: best `HYP_DD20_TRAIL_DYN8050200_GUARD1810_TR15_ACT10_V1` CAGR 5.7845%, DD -18.6688%, trades 1757, years 12/16, decision rejected.

## All strategies

| strategy_id | CAGR | DD | trades | years W/L | stop/trail/act | exits SL/TR/BE/PL/PT/RK | decision |
|:---|---:|---:|---:|:---|:---|:---|:---|
| `HYP_DD20_STOP_DYN8050200_GUARD1810_SL10_V1` | 9.6759% | -19.3252% | 2345 | 17/11 | 10// | 423/0/0/0/0/0 | near_valid_useful |
| `HYP_DD20_STOP_DYN8050200_GUARD1810_SL12_V1` | 6.9185% | -19.5405% | 1729 | 12/16 | 12// | 250/0/0/0/0/0 | rejected |
| `HYP_DD20_STOP_DYN8050200_GUARD1810_SL15_V1` | 7.2005% | -20.7733% | 1725 | 14/14 | 15// | 175/0/0/0/0/0 | rejected |
| `HYP_DD20_TRAIL_DYN8050200_GUARD1810_TR15_ACT10_V1` | 5.7845% | -18.6688% | 1757 | 12/16 | /15/10 | 0/287/0/0/0/0 | rejected |
| `HYP_DD20_TRAIL_DYN8050200_GUARD1810_TR20_ACT15_V1` | 1.9163% | -18.9319% | 308 | 9/19 | /20/15 | 0/63/0/0/0/0 | rejected |
| `HYP_DD20_STOPTRAIL_DYN8050200_NO_GUARD_SL12_TR18_ACT10_V1` | 8.1420% | -22.9276% | 2469 | 13/15 | 12/18/10 | 324/303/0/0/0/0 | rejected |
| `HYP_DD20_TRAIL_DYN8050200_GUARD1810_TR18_ACT10_V1` | 1.5915% | -19.8860% | 313 | 9/19 | /18/10 | 0/77/0/0/0/0 | rejected |
| `HYP_DD20_STOPTRAIL_DYN8050200_GUARD1810_SL15_TR18_ACT10_V1` | 0.1719% | -19.6745% | 99 | 8/20 | 15/18/10 | 27/42/0/0/0/0 | rejected |
| `HYP_DD20_STOPTRAIL_DYN8050200_GUARD1810_SL12_TR18_ACT10_V1` | 0.0905% | -19.4877% | 99 | 8/20 | 12/18/10 | 33/39/0/0/0/0 | rejected |
| `HYP_DD20_STOPTRAIL_DYN8050200_GUARD18_12_SL12_TR18_ACT10_V1` | 0.0905% | -19.4877% | 99 | 8/20 | 12/18/10 | 33/39/0/0/0/0 | rejected |

## Next axis

- Try a less destructive portfolio guard or wider stop/trailing exits only if they keep trades above 2200; current guard remains the trade-count bottleneck.
