# README_ANALISIS_FINAL

## Resumen ejecutivo

- Grilla anterior cargada: **180 variantes**.
- Grilla extendida nueva: **118 variantes completed**, **0 failed**, **0 skipped**, **0 metric_no_effect**.
- Runs nuevos verificados en `runs/`: **118**.
- Resultado combinado: **300 filas** incluyendo baseline + grilla anterior + extensi?n.
- Baseline actual del repo: CAGR **19.13%**, Max DD **-51.08%**, worst year **-44.61%**.

## Confirmaci?n de outputs en runs/

Cada variante nueva tiene `run_id` y `run_dir` en `grid_results.csv`. Se verific? que los `run_dir` existen y contienen:

- `metrics.json`
- `trades.csv`
- `equity_curve.csv`
- `run_manifest.json`

Los reportes agregados quedan en este directorio; las corridas individuales quedan como fuente primaria en `runs/<run_id>/`.

## Mejor anterior vs mejor nueva

### Mejor anterior
`HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_SOFT_R12_C25_E75_CR50_REDD_RECOVERED_DD8_SL20` | CAGR 14.82% | DD -36.66% | 2008 DD -34.98% | 2025 DD -26.62%

### Mejor nueva / mejor global combinada para tradear
`HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_EXT_R12_C25_E66_CR33_REDD_RECOVERED_DD8_SL20` | CAGR 13.45% | DD -32.95% | 2008 DD -31.13% | 2025 DD -23.52%

La extensi?n **s? mejor?** a la ganadora anterior en perfil defensivo: baj? DD de **-36.66%** a **-32.95%**, mejor? 2008 DD de **-34.98%** a **-31.13%**, y 2025 DD de **-26.62%** a **-23.52%**. El costo fue bajar CAGR de **14.82%** a **13.45%**.

## Rankings combinados

- Best CAGR: `HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_SOFT_R18_C35_E75_CR50_REDD_RECOVERED_DD12_SLNONE` | CAGR 15.33% | DD -40.85% | 2008 DD -40.70% | 2025 DD -31.25%
- Best Drawdown puro: `HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_R15_C25_E33_CR0_RESPY_SMA200_DD15_SL30` | CAGR 0.43% | DD -25.35% | 2008 DD 0.00% | 2025 DD 0.00%
- Best Calmar: `HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_EXT_R12_C24_E75_CR50_REDD_RECOVERED_DD6_SL20` | CAGR 14.88% | DD -36.04% | 2008 DD -35.46% | 2025 DD -26.28%
- Best Balanced / To Trade: `HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_EXT_R12_C25_E66_CR33_REDD_RECOVERED_DD8_SL20` | CAGR 13.45% | DD -32.95% | 2008 DD -31.13% | 2025 DD -23.52%
- Best 2008 tradeable: `HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_SOFT_R15_C30_E50_CR25_REDD_RECOVERED_DD10_SLNONE` | CAGR 10.53% | DD -34.47% | 2008 DD -29.85% | 2025 DD -25.89%
- Best 2025 tradeable: `HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_EXT_R12_C25_E60_CR50_REDD_RECOVERED_DD8_SL18` | CAGR 11.41% | DD -33.05% | 2008 DD -32.62% | 2025 DD -21.19%
- Best STOP30 nuevo: `HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_STOP30_EXT_RE_DD8_CR0` | CAGR 0.17% | DD -31.98% | 2008 DD 0.00% | 2025 DD 0.00%


## Top 10 nuevas balanceadas

| strategy_id | cagr | max_drawdown | calmar | balanced_score | 2008_2009_return | 2008_2009_max_dd | q4_2018_max_dd | 2025_return | 2025_max_dd | cash_days | run_id |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_EXT_R12_C25_E66_CR33_REDD_RECOVERED_DD8_SL20 | 13.45 | -32.95 | 0.41 | 17.10 | -25.74 | -31.13 | -24.68 | 1.24 | -23.52 | 2831 | DDGRID_EXT_R12_C25_E66_CR33_REDD_RECOVERED_DD8_SL20_EXT_20260531_130013_116_6ee6cd52 |
| HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_EXT_FINE_R10_C22_E75_CR50_REDD_RECOVERED_DD6_SL18 | 13.80 | -33.80 | 0.41 | 16.53 | -26.02 | -33.48 | -24.54 | 1.14 | -24.76 | 2832 | DDGRID_EXT_FINE_R10_C22_E75_CR50_REDD_RECOVERED_DD6_SL18_EXT_20260531_113222_014_044b28e2 |
| HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_EXT_R12_C24_E66_CR40_REDD_RECOVERED_DD8_SL20 | 13.66 | -33.90 | 0.40 | 16.52 | -25.83 | -32.14 | -25.19 | 1.24 | -23.52 | 2831 | DDGRID_EXT_R12_C24_E66_CR40_REDD_RECOVERED_DD8_SL20_EXT_20260531_123147_085_8fb864ac |
| HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_EXT_FINE_R12_C25_E66_CR40_REDD_RECOVERED_DD8_SL20 | 13.93 | -34.38 | 0.41 | 16.39 | -26.11 | -32.40 | -25.21 | 1.24 | -23.52 | 2831 | DDGRID_EXT_FINE_R12_C25_E66_CR40_REDD_RECOVERED_DD8_SL20_EXT_20260531_112717_012_c84bc8f4 |
| HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_EXT_R12_C25_E75_CR25_REDD_RECOVERED_DD8_SL20 | 12.19 | -32.11 | 0.38 | 16.30 | -25.79 | -30.14 | -24.50 | -3.67 | -26.65 | 2831 | DDGRID_EXT_R12_C25_E75_CR25_REDD_RECOVERED_DD8_SL20_EXT_20260531_125548_112_d05c225f |
| HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_EXT_R12_C25_E66_CR40_REDD_RECOVERED_DD6_SL20 | 13.71 | -34.38 | 0.40 | 16.27 | -25.72 | -32.22 | -25.21 | 2.11 | -23.39 | 2831 | DDGRID_EXT_R12_C25_E66_CR40_REDD_RECOVERED_DD6_SL20_EXT_20260531_125741_114_d6683506 |
| HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_EXT_FINE_R12_C25_E66_CR50_REDD_RECOVERED_DD8_SL20 | 14.15 | -34.51 | 0.41 | 16.26 | -26.71 | -34.24 | -25.99 | 1.24 | -23.52 | 2831 | DDGRID_EXT_FINE_R12_C25_E66_CR50_REDD_RECOVERED_DD8_SL20_EXT_20260531_112110_005_6332dc42 |
| HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_EXT_R12_C22_E75_CR50_REDD_RECOVERED_DD8_SL18 | 13.66 | -33.95 | 0.40 | 16.22 | -26.41 | -33.77 | -25.54 | 0.88 | -25.09 | 2832 | DDGRID_EXT_R12_C22_E75_CR50_REDD_RECOVERED_DD8_SL18_EXT_20260531_124309_100_981787bc |
| HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_EXT_R12_C25_E75_CR33_REDD_RECOVERED_DD10_SL20 | 12.80 | -33.11 | 0.39 | 16.11 | -26.30 | -31.70 | -25.29 | -0.93 | -27.78 | 2831 | DDGRID_EXT_R12_C25_E75_CR33_REDD_RECOVERED_DD10_SL20_EXT_20260531_125430_111_3ffb3d16 |
| HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_EXT_R12_C24_E66_CR50_REDD_RECOVERED_DD8_SL20 | 13.99 | -34.57 | 0.40 | 16.09 | -26.55 | -34.09 | -25.94 | 1.24 | -23.52 | 2831 | DDGRID_EXT_R12_C24_E66_CR50_REDD_RECOVERED_DD8_SL20_EXT_20260531_113951_025_9f63d461 |


## Comparaci?n contra baseline

- Baseline DD: **-51.08%**.
- Mejor nueva DD: **-32.95%**.
- Mejora de DD: **18.13 puntos**.
- Sacrificio de CAGR vs baseline: **5.68 puntos**.
- 2008/2009 DD baseline: **-50.96%** vs nueva **-31.13%**.
- 2025 DD baseline: **-35.04%** vs nueva **-23.52%**.

## STOP30

La revalidaci?n de STOP30 sigue sin convencer. Controla drawdown qued?ndose demasiado en cash y no mejora el balance retorno/riesgo frente a defensa temprana. No lo usar?a como defensa principal.

## Limitaciones

- Backtest daily-close; no simula stops intradiarios.
- La se?al base se reutiliza y los controles de riesgo son config-driven.
- No se modific? la estrategia original, AUTO_002, current_parent ni baseline oficial.
- Siguiente validaci?n seria: walk-forward, slippage/costos m?s duros, next-close estricto y cartera combinada.

## C?mo continuar

```powershell
python .\scripts\run_dd_guard_grid_auto.py --base-strategy HYP_REFINE_AUTO002_TOPN_6_V1 --data-folder "C:\Pythons\ML-Trading\Momentum\trading_agentic_research\data" --stage all --resume --previous-report-dir "reports/dd_guard_grid_HYP_REFINE_AUTO002_TOPN_6_V1_20260530_140830" --output-dir "reports\dd_guard_grid_HYP_REFINE_AUTO002_TOPN_6_V1_EXTENDED_20260531_110433" --max-screening-runs 250 --max-full-runs 250 --ensure-runs-output
```

## Conclusi?n directa para Hern?n

- S? apareci? una variante mejor que la ganadora anterior: `HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_EXT_R12_C25_E66_CR33_REDD_RECOVERED_DD8_SL20`.
- La que tradear?a ahora: `HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_EXT_R12_C25_E66_CR33_REDD_RECOVERED_DD8_SL20`.
- No seguir?a extendiendo ciegamente la grilla; ya hay una mejora defensiva clara.
- Pr?ximo paso: pasar a walk-forward / slippage / cartera combinada. Eso vale m?s que tirar 1.000 variantes m?s.
- Los runs individuales quedaron en: `C:\Pythons\ML-Trading\Momentum\trading_agentic_research\runs\<run_id>\`.
