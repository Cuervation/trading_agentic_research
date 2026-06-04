# README_ANALISIS_FINAL

Validación robusta read-only para `HYP_REFINE_AUTO002_TOPN_6_V1` y variantes DDGRID.

IMPORTANTE: esto no toca motor, configs ni runs existentes. El walk-forward es validación por subperíodos usando parámetros fijos; NO es walk-forward de optimización real.

## Inventario y consistencia

Ver `robust_results.csv`. Incompletos quedan marcados como `incomplete=true`. Diferencias contra `metrics.json` quedan en columnas `abs_diff_*`, `rel_diff_*` y `metric_warning`.

## Walk-forward read-only

Ver `walkforward_results.csv`. SPY solo se informa si hay benchmark disponible en datos leídos; no se inventa comparación.

## Costos / slippage

Ver `cost_slippage_estimates.csv`. Las filas indican `approximation=true/false` y columnas usadas.

## Carteras combinadas

Ver `portfolio_mix_results.csv`. DD20 encontrado: `True`.

## Auditoría de ejecución

`execution_timing_uncertain=true`. `requires_engine_change=true` para validar estrictamente timing/lookahead sin inferencias.

## Conclusión directa para Hernán

- Mejor single por Calmar recalculado: `mejor_global` (`HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_LONG_R12_C22_E75_CR40_REDD_RECOVERED_DD8_SL20`).
- Mejor portfolio por Calmar recalculado: `A_100_mejor_global`.
- La mejor global sigue como candidata principal si supera a las defensivas en Calmar/estabilidad de subperíodos; mirá robust_results + walkforward antes de promocionar.
- La alternativa defensiva conviene más si reduce DD materialmente con pérdida menor de CAGR.
- La sub -30 DD vale la pena solo si el límite psicológico/operativo de DD <30% pesa más que el CAGR perdido.
- Una cartera combinada es preferible si mejora Calmar/DD frente a la mejor individual.
- Señales de sobreoptimización: mirar concentración de performance por ventana y años malos.
- Riesgo ejecución/lookahead: no confirmado, pero timing incierto en modo read-only.
- Paper trading: conveniente solo después de revisar `limitations.md`; no promocionar baseline ni tocar motor todavía.
- Próxima validación con motor: instrumentar timing de guards/stops, next-open/next-close, slippage/costos exactos y lookahead checks.

Pass/fail: `PASS_READONLY_WITH_LIMITATIONS`
Requires engine change: `true`
