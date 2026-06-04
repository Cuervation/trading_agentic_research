# Limitations

- Validación read-only: no reoptimiza y no rerunea backtests.
- Walk-forward aquí significa subperíodos con parámetros fijos; NO es walk-forward de optimización real.
- Costos/slippage son post-trade estimados; si no hay columnas explícitas, quedan como approximation=true.
- Execution timing: no se modifica motor; si manifest/notes no confirman same-close/next-close/next-open, se marca incierto.
- implementation_notes con posibles pistas: 6.
- execution_timing_uncertain=true
- requires_engine_change: validación estricta de timing/lookahead necesita instrumentar o extender motor en otra etapa.