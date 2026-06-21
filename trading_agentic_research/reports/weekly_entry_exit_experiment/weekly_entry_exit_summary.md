# Weekly entry / weekly exit experiment

Frequency-only causal experiment. Ranking, top_n, exit threshold, filters, costs and universe remain inherited.

- Strategies selected: 1
- Completed/reused weekly runs: 1
- Skipped/failed: 0
- Governance: no promotion; current_parent/current_baseline untouched.
- Decision must use net post-cost results; weekly frequency is not assumed better.

## Top 10 weekly por CAGR

| strategy | weekly run | metric | CAGR | Max DD | trades |
|---|---|---:|---:|---:|---:|
| HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_LONGRUN_STRICT_STRICT_NEXT_CLOSE_R13_C22_E75_CR33_REDD_DD7_SL18_WEEKLY_ENTRY_EXIT_V1 | WEEKLY_HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_LONGRUN_STRICT_STRICT_NEXT_CLOSE_R13_C22_E75_CR33_REDD_DD7_SL18_20260610_093645_584698_18208 | 11.115941763212689 | 11.115941763212689 | -29.105870186014315 | 12143 |

## Top 10 weekly por menor drawdown

| strategy | weekly run | metric | CAGR | Max DD | trades |
|---|---|---:|---:|---:|---:|
| HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_LONGRUN_STRICT_STRICT_NEXT_CLOSE_R13_C22_E75_CR33_REDD_DD7_SL18_WEEKLY_ENTRY_EXIT_V1 | WEEKLY_HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_LONGRUN_STRICT_STRICT_NEXT_CLOSE_R13_C22_E75_CR33_REDD_DD7_SL18_20260610_093645_584698_18208 | -29.105870186014315 | 11.115941763212689 | -29.105870186014315 | 12143 |

## Top 10 mejores weekly vs original por mejora de drawdown

| strategy | weekly run | metric | CAGR | Max DD | trades |
|---|---|---:|---:|---:|---:|
| HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_LONGRUN_STRICT_STRICT_NEXT_CLOSE_R13_C22_E75_CR33_REDD_DD7_SL18_WEEKLY_ENTRY_EXIT_V1 | WEEKLY_HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_LONGRUN_STRICT_STRICT_NEXT_CLOSE_R13_C22_E75_CR33_REDD_DD7_SL18_20260610_093645_584698_18208 | 3.0039007796409365 | 11.115941763212689 | -29.105870186014315 | 12143 |

## Top 10 mejores weekly vs original por CAGR delta

| strategy | weekly run | metric | CAGR | Max DD | trades |
|---|---|---:|---:|---:|---:|
| HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_LONGRUN_STRICT_STRICT_NEXT_CLOSE_R13_C22_E75_CR33_REDD_DD7_SL18_WEEKLY_ENTRY_EXIT_V1 | WEEKLY_HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_LONGRUN_STRICT_STRICT_NEXT_CLOSE_R13_C22_E75_CR33_REDD_DD7_SL18_20260610_093645_584698_18208 | -0.41376651903710737 | 11.115941763212689 | -29.105870186014315 | 12143 |

## Peores 10 por caída de CAGR

| strategy | weekly run | metric | CAGR | Max DD | trades |
|---|---|---:|---:|---:|---:|
| HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_LONGRUN_STRICT_STRICT_NEXT_CLOSE_R13_C22_E75_CR33_REDD_DD7_SL18_WEEKLY_ENTRY_EXIT_V1 | WEEKLY_HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_LONGRUN_STRICT_STRICT_NEXT_CLOSE_R13_C22_E75_CR33_REDD_DD7_SL18_20260610_093645_584698_18208 | -0.41376651903710737 | 11.115941763212689 | -29.105870186014315 | 12143 |

## Peores 10 por aumento de trades

| strategy | weekly run | metric | CAGR | Max DD | trades |
|---|---|---:|---:|---:|---:|
| HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_LONGRUN_STRICT_STRICT_NEXT_CLOSE_R13_C22_E75_CR33_REDD_DD7_SL18_WEEKLY_ENTRY_EXIT_V1 | WEEKLY_HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_LONGRUN_STRICT_STRICT_NEXT_CLOSE_R13_C22_E75_CR33_REDD_DD7_SL18_20260610_093645_584698_18208 | 5663 | 11.115941763212689 | -29.105870186014315 | 12143 |

## Conclusión

Weekly parece prometedor en 0/1 casos con CAGR no inferior y trade multiplier <= 1.5.
Turnover alto, costos acumulados y whipsaw son riesgos principales. Revisar cada fila neta post-costos antes de cualquier promoción.
