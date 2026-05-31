# README_ANALISIS_FINAL

## Resumen ejecutivo
- Baseline `HYP_REFINE_AUTO002_TOPN_6_V1`: CAGR 19.13%, Max DD -51.08%.
- Nota de verificación: existía un run histórico con CAGR ~40.85% y DD ~-59.61%, pero la corrida actual del repo (`VALIDATE_HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_20260530`) dio CAGR 19.13% y DD -51.08%. Este reporte usa la corrida actual como fuente de verdad.
- Completed: 180; Failed: 0; Metric no effect: 0.
- Alcance: grilla parcial/full-history de las variantes completadas. Para extender a 500, usar `--resume`.
- Mejor balanceada: `HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_SOFT_R12_C25_E75_CR50_REDD_RECOVERED_DD8_SL20` CAGR 14.82%, DD -36.66%.

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
| HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_R15_C25_E33_CR0_RECOOLDOWN_180_SPY_SMA200_DD12_SL25 | 0.43 | -25.35 | 0.02 | 0.00 | 0.00 | 0.00 | 2 | 3 | 6837 |


## Mejor por Calmar
| strategy_id | cagr | max_drawdown | calmar | 2008_2009_return | 2008_2009_max_dd | 2025_return | dd_guard_activation_count | position_stop_count | cash_days |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_SOFT_R12_C25_E75_CR50_REDD_RECOVERED_DD8_SL20 | 14.82 | -36.66 | 0.40 | -27.50 | -34.98 | 0.17 | 80 | 79 | 2831 |


## Mejor balanceada
| strategy_id | cagr | max_drawdown | calmar | 2008_2009_return | 2008_2009_max_dd | 2025_return | dd_guard_activation_count | position_stop_count | cash_days |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_SOFT_R12_C25_E75_CR50_REDD_RECOVERED_DD8_SL20 | 14.82 | -36.66 | 0.40 | -27.50 | -34.98 | 0.17 | 80 | 79 | 2831 |


## Mejor stop -30
| strategy_id | cagr | max_drawdown | calmar | 2008_2009_return | 2008_2009_max_dd | 2025_return | dd_guard_activation_count | position_stop_count | cash_days |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_STOP30_PERM | 0.17 | -31.98 | 0.01 | 0.00 | 0.00 | 0.00 | 1 | 0 | 6844 |


## Qué pasó en 2008
| strategy_id | cagr | max_drawdown | 2008_2009_return | 2008_2009_max_dd | cash_days |
| --- | --- | --- | --- | --- | --- |
| HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_SOFT_R15_C30_E50_CR25_REDD_RECOVERED_DD10_SLNONE | 10.53 | -34.47 | -25.29 | -29.85 | 2831 |
| HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_SOFT_R12_C25_E75_CR50_REDD_RECOVERED_DD8_SL20 | 14.82 | -36.66 | -27.50 | -34.98 | 2831 |
| HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_SOFT_R15_C30_E75_CR25_RESPY_SMA200_DD10_SLNONE | 12.67 | -37.54 | -31.09 | -35.11 | 2831 |
| HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_SOFT_R18_C35_E50_CR25_RECOOLDOWN_90_SPY_SMA200_DD12_SLNONE | 12.31 | -35.89 | -29.77 | -35.73 | 2831 |
| HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_SOFT_R20_C35_E50_CR25_RECOOLDOWN_180_SPY_SMA200_DD15_SLNONE | 14.16 | -35.89 | -29.77 | -35.73 | 2831 |
| HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_SOFT_R10_C25_E75_CR50_REDD_RECOVERED_DD5_SLNONE | 14.21 | -37.65 | -28.83 | -36.14 | 2831 |
| HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_SOFT_R12_C28_E75_CR50_REDD_RECOVERED_DD8_SLNONE | 14.59 | -37.73 | -29.66 | -36.84 | 2831 |
| HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_SOFT_R15_C30_E75_CR50_RECOOLDOWN_90_DD10_SLNONE | 14.82 | -38.82 | -29.98 | -36.96 | 2831 |
| HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_SOFT_R15_C30_E75_CR50_REDD_RECOVERED_DD10_SL20 | 14.94 | -39.12 | -29.70 | -36.98 | 2831 |
| HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_SOFT_R15_C30_E75_CR50_REDD_RECOVERED_DD10_SLNONE | 15.17 | -38.82 | -31.50 | -38.49 | 2831 |


## Qué pasó en 2025
| strategy_id | cagr | max_drawdown | 2025_return | 2025_max_dd | cash_days |
| --- | --- | --- | --- | --- | --- |
| HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_SOFT_R15_C30_E50_CR25_REDD_RECOVERED_DD10_SLNONE | 10.53 | -34.47 | 0.55 | -25.89 | 2831 |
| HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_SOFT_R12_C25_E75_CR50_REDD_RECOVERED_DD8_SL20 | 14.82 | -36.66 | 0.17 | -26.62 | 2831 |
| HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_SOFT_R10_C25_E75_CR50_REDD_RECOVERED_DD5_SLNONE | 14.21 | -37.65 | -2.20 | -27.20 | 2831 |
| HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_SOFT_R12_C28_E75_CR50_REDD_RECOVERED_DD8_SLNONE | 14.59 | -37.73 | 0.85 | -27.33 | 2831 |
| HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_SOFT_R18_C35_E50_CR25_RECOOLDOWN_90_SPY_SMA200_DD12_SLNONE | 12.31 | -35.89 | -1.50 | -27.40 | 2831 |
| HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_SOFT_R20_C35_E50_CR25_RECOOLDOWN_180_SPY_SMA200_DD15_SLNONE | 14.16 | -35.89 | -3.42 | -28.82 | 2831 |
| HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_SOFT_R15_C30_E75_CR50_REDD_RECOVERED_DD10_SL20 | 14.94 | -39.12 | 1.97 | -29.58 | 2831 |
| HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_SOFT_R15_C30_E75_CR50_RECOOLDOWN_90_DD10_SLNONE | 14.82 | -38.82 | -2.45 | -30.55 | 2831 |
| HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_SOFT_R15_C30_E75_CR50_REDD_RECOVERED_DD10_SLNONE | 15.17 | -38.82 | -2.45 | -30.55 | 2831 |
| HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_SOFT_R15_C30_E75_CR25_RESPY_SMA200_DD10_SLNONE | 12.67 | -37.54 | -5.79 | -30.59 | 2831 |


## Riesgos pendientes
- Validar económicamente daily-close vs next-close. No hay intraday.
- Repetir con datos actualizados si cambia feature store.

## Cómo continuar
```powershell
python .\scripts\run_dd_guard_grid_auto.py --base-strategy HYP_REFINE_AUTO002_TOPN_6_V1 --data-folder "C:\Pythons\ML-Trading\Momentum\trading_agentic_research\data" --output-dir "reports\dd_guard_grid_HYP_REFINE_AUTO002_TOPN_6_V1_20260530_140830" --stage all --max-screening-runs 500 --max-full-runs 300 --resume
```

## Conclusión directa para Hernán
- Mejor variante: `HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_SOFT_R12_C25_E75_CR50_REDD_RECOVERED_DD8_SL20`.
- Más segura: `HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_R15_C25_E33_CR0_RECOOLDOWN_180_SPY_SMA200_DD12_SL25`.
- Mejor equilibrio: `HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_SOFT_R12_C25_E75_CR50_REDD_RECOVERED_DD8_SL20`.
- Tradearía: `HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_SOFT_R12_C25_E75_CR50_REDD_RECOVERED_DD8_SL20` si aceptás el modelo daily-close y confirmás robustness fuera de muestra.
- NO tradearía solo por CAGR: `HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_SOFT_R18_C35_E75_CR50_REDD_RECOVERED_DD12_SLNONE` sin mirar DD/stress; CAGR sin supervivencia es VANIDAD.
- Stop -30: mejor observado `HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_STOP30_PERM`. En esta corrida fue demasiado tardío/brusco: bajó DD, pero dejó CAGR cerca de cero o negativo.
- Si una defensa temprana mantiene CAGR decente y baja DD antes de -30, es más sana que esperar el incendio.
- Próximos tests: next-close estricto, walk-forward, costos/slippage más duros, sensibilidad 2008/2025.
