# README_ANALISIS_FINAL

## Resumen ejecutivo
- Baseline `HYP_REFINE_AUTO002_TOPN_6_V1`: CAGR 19.13%, Max DD -51.08%.
- Nota de verificación: existía un run histórico con CAGR ~40.85% y DD ~-59.61%, pero la corrida actual del repo (`VALIDATE_HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_20260530`) dio CAGR 19.13% y DD -51.08%. Este reporte usa la corrida actual como fuente de verdad.
- Variantes anteriores cargadas: 180.
- Variantes nuevas completed: 588; runs nuevos en `runs/`: 588.
- Completed combinado: 768; Failed: 0; Metric no effect: 0.
- Confirmaci?n: las nuevas corridas individuales quedan en `runs/<run_id>/`; `reports/.../variant_runs/` solo guarda punteros.
- Alcance: extensi?n full-history priorizada alrededor de la mejor zona balanceada.
- Mejor balanceada: `HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_LONG_R12_C22_E75_CR40_REDD_RECOVERED_DD7_SL18` CAGR 13.52%, DD -31.73%.
- Mejor anterior: `HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_SOFT_R12_C25_E75_CR50_REDD_RECOVERED_DD8_SL20`.
- Mejor nueva: `HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_LONG_R12_C22_E75_CR40_REDD_RECOVERED_DD7_SL18`.

## Qué se implementó
- Risk controls config-driven, event logging, checkpoint/resume, reportes CSV/MD/XLSX si openpyxl está disponible.

## Resultado original
| strategy_id | cagr | max_drawdown | calmar | 2008_2009_return | 2008_2009_max_dd | 2025_return | dd_guard_activation_count | position_stop_count | cash_days |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| HYP_REFINE_AUTO002_TOPN_6_V1 | 19.13 | -51.08 | 0.37 | -39.33 | -50.96 | 1.93 | 0 | 0 | 2831 |


## Mejor por CAGR
| strategy_id | cagr | max_drawdown | calmar | 2008_2009_return | 2008_2009_max_dd | 2025_return | dd_guard_activation_count | position_stop_count | cash_days |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_SOFT_R18_C35_E75_CR50_REDD_RECOVERED_DD12_SLNONE | 15.33 | -40.85 | 0.38 | -34.03 | -40.70 | -0.38 | 61 | 0 | 2831 |


## Mejor por drawdown
| strategy_id | cagr | max_drawdown | calmar | 2008_2009_return | 2008_2009_max_dd | 2025_return | dd_guard_activation_count | position_stop_count | cash_days |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_R15_C25_E33_CR0_RESPY_SMA200_DD12_SL30 | 0.43 | -25.35 | 0.02 | 0.00 | 0.00 | 0.00 | 2 | 3 | 6837 |


## Mejor por Calmar
| strategy_id | cagr | max_drawdown | calmar | 2008_2009_return | 2008_2009_max_dd | 2025_return | dd_guard_activation_count | position_stop_count | cash_days |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_LONG_R12_C22_E75_CR40_REDD_RECOVERED_DD8_SL20 | 14.04 | -32.64 | 0.43 | -25.46 | -31.86 | -0.45 | 105 | 78 | 2831 |


## Mejor balanceada
| strategy_id | cagr | max_drawdown | calmar | 2008_2009_return | 2008_2009_max_dd | 2025_return | dd_guard_activation_count | position_stop_count | cash_days |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_LONG_R12_C22_E75_CR40_REDD_RECOVERED_DD7_SL18 | 13.52 | -31.73 | 0.43 | -25.35 | -31.55 | 0.36 | 108 | 103 | 2832 |


## Mejor stop -30
| strategy_id | cagr | max_drawdown | calmar | 2008_2009_return | 2008_2009_max_dd | 2025_return | dd_guard_activation_count | position_stop_count | cash_days |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_STOP30_PERM | 0.17 | -31.98 | 0.01 | 0.00 | 0.00 | 0.00 | 1 | 0 | 6844 |


## Qué pasó en 2008
| strategy_id | cagr | max_drawdown | 2008_2009_return | 2008_2009_max_dd | cash_days |
| --- | --- | --- | --- | --- | --- |
| HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_LONG_R12_C22_E75_CR30_REDD_RECOVERED_DD7_SL18 | 11.50 | -30.30 | -24.24 | -29.22 | 2832 |
| HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_LONG_R12_C20_E75_CR33_REDD_RECOVERED_DD8_SL20 | 10.39 | -30.82 | -23.84 | -29.43 | 2831 |
| HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_LONG_R12_C22_E75_CR30_REDD_RECOVERED_DD8_SL20 | 10.61 | -31.23 | -24.29 | -29.44 | 2831 |
| HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_LONG_R12_C21_E75_CR33_REDD_RECOVERED_DD8_SL20 | 11.31 | -29.85 | -24.10 | -29.66 | 2831 |
| HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_LONG_R12_C21_E75_CR36_REDD_RECOVERED_DD7_SL18 | 10.91 | -30.68 | -23.98 | -29.77 | 2832 |
| HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_SOFT_R15_C30_E50_CR25_REDD_RECOVERED_DD10_SLNONE | 10.53 | -34.47 | -25.29 | -29.85 | 2831 |
| HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_LONG_R12_C22_E75_CR33_REDD_RECOVERED_DD7_SL18 | 10.83 | -30.51 | -24.57 | -29.92 | 2832 |
| HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_LONG_R12_C22_E75_CR33_REDD_RECOVERED_DD8_SL18 | 10.38 | -30.51 | -24.57 | -29.92 | 2832 |
| HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_LONG_R11_C22_E75_CR33_REDD_RECOVERED_DD8_SL20 | 12.01 | -31.58 | -24.45 | -29.99 | 2831 |
| HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_LONG_R12_C22_E75_CR33_REDD_RECOVERED_DD9_SL20 | 11.57 | -31.58 | -24.64 | -30.17 | 2831 |


## Qué pasó en 2025
| strategy_id | cagr | max_drawdown | 2025_return | 2025_max_dd | cash_days |
| --- | --- | --- | --- | --- | --- |
| HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_EXT_R12_C25_E60_CR50_REDD_RECOVERED_DD8_SL18 | 11.41 | -33.05 | 1.49 | -21.19 | 2832 |
| HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_EXT_R12_C25_E60_CR50_REDD_RECOVERED_DD8_SL22 | 11.94 | -34.77 | 1.02 | -21.52 | 2831 |
| HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_EXT_R12_C25_E60_CR50_REDD_RECOVERED_DD8_SL20 | 11.53 | -34.05 | 1.88 | -21.58 | 2831 |
| HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_EXT_R12_C24_E60_CR50_REDD_RECOVERED_DD8_SL20 | 11.81 | -33.67 | 1.88 | -21.58 | 2831 |
| HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_LONG_R12_C20_E75_CR33_REDD_RECOVERED_DD8_SL20 | 10.39 | -30.82 | 1.58 | -22.61 | 2831 |
| HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_LONG_R12_C20_E75_CR36_REDD_RECOVERED_DD8_SL22 | 10.65 | -32.52 | 0.92 | -22.90 | 2831 |
| HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_EXT_R12_C25_E66_CR50_REDD_RECOVERED_DD6_SL18 | 13.32 | -34.01 | 2.66 | -22.98 | 2832 |
| HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_EXT_R12_C24_E66_CR50_REDD_RECOVERED_DD8_SL18 | 13.21 | -33.75 | 1.79 | -23.10 | 2832 |
| HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_EXT_R12_C26_E66_CR50_REDD_RECOVERED_DD8_SL18 | 13.28 | -34.47 | 1.79 | -23.10 | 2832 |
| HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_EXT_R12_C25_E66_CR40_REDD_RECOVERED_DD8_SL18 | 12.81 | -34.08 | 1.79 | -23.10 | 2832 |


## Riesgos pendientes
- Validar económicamente daily-close vs next-close. No hay intraday.
- Repetir con datos actualizados si cambia feature store.

## Cómo continuar
```powershell
python .\scripts\run_dd_guard_grid_auto.py --base-strategy HYP_REFINE_AUTO002_TOPN_6_V1 --data-folder "C:\Pythons\ML-Trading\Momentum\trading_agentic_research\data" --output-dir "reports\dd_guard_grid_HYP_REFINE_AUTO002_TOPN_6_V1_LONGRUN_20260601_230028" --stage all --max-screening-runs 250 --max-full-runs 250 --resume --previous-report-dir reports/dd_guard_grid_HYP_REFINE_AUTO002_TOPN_6_V1_20260530_140830 --ensure-runs-output
```

## Conclusión directa para Hernán
- Apareci? una variante nueva mejor que la anterior: `HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_LONG_R12_C22_E75_CR40_REDD_RECOVERED_DD7_SL18` vs `HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_SOFT_R12_C25_E75_CR50_REDD_RECOVERED_DD8_SL20`.
- Mejor variante: `HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_LONG_R12_C22_E75_CR40_REDD_RECOVERED_DD7_SL18`.
- Más segura: `HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_R15_C25_E33_CR0_RESPY_SMA200_DD12_SL30`.
- Mejor equilibrio: `HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_LONG_R12_C22_E75_CR40_REDD_RECOVERED_DD7_SL18`.
- Tradearía: `HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_LONG_R12_C22_E75_CR40_REDD_RECOVERED_DD7_SL18` si aceptás el modelo daily-close y confirmás robustness fuera de muestra.
- NO tradearía solo por CAGR: `HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_SOFT_R18_C35_E75_CR50_REDD_RECOVERED_DD12_SLNONE` sin mirar DD/stress; CAGR sin supervivencia es VANIDAD.
- Stop -30: mejor observado `HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_STOP30_PERM`. En esta corrida fue demasiado tardío/brusco: bajó DD, pero dejó CAGR cerca de cero o negativo.
- Si una defensa temprana mantiene CAGR decente y baja DD antes de -30, es más sana que esperar el incendio.
- Próximos tests: next-close estricto, walk-forward, costos/slippage más duros, sensibilidad 2008/2025.
