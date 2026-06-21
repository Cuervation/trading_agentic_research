# Implementation notes

## Archivos tocados/controlados

- `backtester/execution.py`: ajuste mínimo para respetar `execution_timing.apply_to` en `strict_next_close`.
- `scripts/run_backtest.py`: ya registraba métricas/manifest de execution timing en esta rama.
- `scripts/validation/run_strict_execution_validation.py`: usado como runner de validación strict.

## Compatibilidad

- Default sigue `current_default`.
- `strict_next_close` solo se activa con `execution_timing.enabled=true` y `mode=strict_next_close`.
- Baseline original sin strict recalculó 19.1313% CAGR / -51.0819% DD: consistente.
- Mejor global sin strict recalculó 14.0379% CAGR / -32.6412% DD: consistente.

## Costos/slippage

El motor ya aplica `cost_per_side_pct`. La rama soporta `execution_costs.cost_multiplier` y `slippage_multiplier`; como no hay `slippage_per_side_pct` base configurado, el escenario `cost2_slip2` duplica costos y deja slippage efectivo en 0. Esto queda como limitación explícita, no como resultado inventado.

## Validaciones

- `python -m py_compile backtester/execution.py scripts/run_backtest.py scripts/validation/run_strict_execution_validation.py`: PASS.
- Corridas individuales guardadas en `runs/STRICT_EXEC_*`.
- `run_manifest.json` registra `execution_timing_mode`.
- Configs originales no se modificaron; configs strict se escribieron en el report y carpeta generated/strict.
