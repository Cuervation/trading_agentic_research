# DD20 SPY Consistency Diagnosis

Base near-miss: `HYP_DD20_SPY_DYN_65_45_25_0_V1`.

## Lost years vs SPY

| year | strategy | SPY | excess | avg exposure | regimes S/N/W/C | opened/closed | max DD year |
|---:|---:|---:|---:|---:|:---|:---|---:|
| 1999 | 0.00% | 19.38% | -19.38% | 36.67% | 1/5/6/0 | 0/0 | 0.00% |
| 2006 | 4.66% | 11.78% | -7.12% | 60.00% | 9/3/0/0 | 164/149 | -6.88% |
| 2009 | 4.56% | 19.88% | -15.32% | 55.00% | 6/3/0/3 | 176/150 | -5.36% |
| 2010 | 10.40% | 10.96% | -0.56% | 53.33% | 7/3/2/0 | 141/134 | -6.12% |
| 2012 | 6.96% | 11.69% | -4.73% | 60.00% | 9/3/0/0 | 175/173 | -3.69% |
| 2013 | 9.09% | 26.45% | -17.36% | 63.33% | 11/1/0/0 | 157/156 | -2.77% |
| 2014 | 6.72% | 12.37% | -5.65% | 65.00% | 12/0/0/0 | 160/148 | -4.57% |
| 2016 | 6.95% | 11.20% | -4.25% | 53.33% | 7/3/2/0 | 139/136 | -3.19% |
| 2017 | 5.91% | 18.48% | -12.57% | 65.00% | 12/0/0/0 | 147/156 | -2.37% |
| 2019 | 8.24% | 28.65% | -20.41% | 58.33% | 10/0/2/0 | 153/151 | -2.64% |
| 2020 | 13.89% | 15.09% | -1.20% | 53.33% | 7/2/2/1 | 134/143 | -10.53% |
| 2021 | 8.00% | 28.79% | -20.79% | 65.00% | 12/0/0/0 | 133/134 | -3.21% |
| 2023 | 10.17% | 24.81% | -14.65% | 58.33% | 9/2/1/0 | 186/141 | -5.79% |
| 2024 | 23.08% | 24.00% | -0.92% | 65.00% | 12/0/0/0 | 124/159 | -6.30% |
| 2025 | 13.48% | 16.64% | -3.16% | 56.67% | 9/1/2/0 | 128/147 | -9.97% |

## Interpretation
- Lost years: 15. Bull-market lost years (SPY >= 10%): 15.
- Lost years with average target exposure <= 45%: 1.
- If lost years cluster in strong/neutral regimes, the likely problem is lack of exposure, not bad exits.
- If lost years have many closed trades and high drawdown, exits/risk control are implicated.
- Technical note: this phase now reads embedded `spy_*` regime fields when no literal `SPY` row exists in the feature store; otherwise strong/neutral exposure variants become no-ops.
- Average lost-year target exposure: 57.89%; average SPY return in lost years: 18.68%.
