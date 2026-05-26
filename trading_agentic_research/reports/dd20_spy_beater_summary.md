# DD20 SPY Beater Summary

Constraint: `max_drawdown >= -20`, `CAGR > SPY CAGR`, `trades >= 3000`, `years_beating_spy >= years_losing_to_spy`.

## No valid candidates yet

- Closest by DD: `HYP_DD20_STOP_DYN8050200_GUARD1810_SL10_V1` already passes DD20 at DD -19.3252%; missing: add 655 trades.
- Closest by CAGR: `HYP_DD_FIRST_AUTO002_EXPOSURE_60_V1` at CAGR 15.7814% vs SPY 6.8025%.
- Missing to pass: add 655 trades
- Parameter adjustment indicated: lower weak/crisis exposure first; if DD passes but yearly SPY balance fails, keep crisis at 0 and restore selective strong-regime exposure or use a softer equity guard.

## Reference comparison

| strategy_id | CAGR | SPY CAGR | DD | Calmar | trades | decision |
|:---|---:|---:|---:|---:|---:|:---|
| `HYP_DD_FIRST_AUTO002_DYN_EXPOSURE_65_55_45_25_V1` | 11.8776% | 6.8025% | -28.8044% | 0.4124 | 3852 | rejected |
| `HYP_DD_FIRST_AUTO002_EXPOSURE_50_V1` | 13.1831% | 6.8025% | -31.5494% | 0.4179 | 3847 | rejected |
| `HYP_DD_FIRST_AUTO002_EXPOSURE_60_V1` | 15.7814% | 6.8025% | -36.7898% | 0.4290 | 3837 | rejected |
