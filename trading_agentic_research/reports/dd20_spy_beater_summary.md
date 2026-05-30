# DD20 SPY Beater Summary

Constraint: `max_drawdown >= -20`, `CAGR > SPY CAGR`, `trades >= 1000`, `years_beating_spy >= years_losing_to_spy`.

## Ranking valid candidates

| rank | strategy_id | CAGR | SPY CAGR | excess | DD | Calmar | trades | years W/L |
|---:|:---|---:|---:|---:|---:|---:|---:|:---|
| 1 | `HYP_DD20_CAGR_SL12_TOPN8_GUARD18_10_V1` | 10.8660% | 6.8025% | 4.0636% | -19.7877% | 0.5491 | 2351 | 15/13 |
| 2 | `HYP_DD20_CAGR_SL12_TOPN10_GUARD18_10_V1` | 10.7755% | 6.8025% | 3.9730% | -19.7877% | 0.5446 | 2359 | 15/13 |
| 3 | `HYP_DD20_CAGR_DYN8055200_SL11_TOPN8_V1` | 10.7350% | 6.8025% | 3.9325% | -19.6588% | 0.5461 | 2353 | 16/12 |
| 4 | `HYP_DD20_RESCUE_DYN8050200_NO_NEW_CRISIS_SL11_TOPN8_V1` | 10.5412% | 6.8025% | 3.7387% | -19.6588% | 0.5362 | 2354 | 16/12 |
| 5 | `HYP_DD20_CAGR_DYN8050250_SL11_TOPN8_V1` | 10.5348% | 6.8025% | 3.7324% | -19.6588% | 0.5359 | 2354 | 16/12 |
| 6 | `HYP_DD20_CAGR_SL11_TOPN8_GUARD18_12_V1` | 10.4402% | 6.8025% | 3.6377% | -19.6588% | 0.5311 | 2376 | 16/12 |
| 7 | `HYP_DD20_CAGR_DYN8055250_SL10_TOPN8_V1` | 10.4277% | 6.8025% | 3.6252% | -19.3252% | 0.5396 | 2387 | 17/11 |
| 8 | `HYP_DD20_CAGR_SL11_TOPN10_GUARD18_10_V1` | 10.3864% | 6.8025% | 3.5839% | -19.6588% | 0.5283 | 2362 | 16/12 |
| 9 | `HYP_DD20_CAGR_SL11_TOPN8_GUARD18_14_V1` | 10.3494% | 6.8025% | 3.5470% | -19.6588% | 0.5265 | 2369 | 16/12 |
| 10 | `HYP_DD20_CAGR_SL11_TOPN8_GUARD19_12_V1` | 10.2938% | 6.8025% | 3.4913% | -19.7618% | 0.5209 | 2380 | 16/12 |
| 11 | `HYP_DD20_CAGR_SL10P5_TOPN8_GUARD18_10_V1` | 10.2593% | 6.8025% | 3.4568% | -19.1929% | 0.5345 | 2370 | 16/12 |

## Reference comparison

| strategy_id | CAGR | SPY CAGR | DD | Calmar | trades | decision |
|:---|---:|---:|---:|---:|---:|:---|
| `HYP_DD_FIRST_AUTO002_DYN_EXPOSURE_65_55_45_25_V1` | 11.8776% | 6.8025% | -28.8044% | 0.4124 | 3852 | rejected |
| `HYP_DD_FIRST_AUTO002_EXPOSURE_50_V1` | 13.1831% | 6.8025% | -31.5494% | 0.4179 | 3847 | rejected |
| `HYP_DD_FIRST_AUTO002_EXPOSURE_60_V1` | 15.7814% | 6.8025% | -36.7898% | 0.4290 | 3837 | rejected |
