# Coder Context Pack

Generated: 2026-05-29T15:13:13.366661+00:00

## Rol del agente

Implementar utilidades Python pequeñas, testeables y sin dependencias pesadas.

## Qué archivos puede leer

- SPEC.md
- AGENTS.md
- scripts/*.py puntuales
- backtester/*.py solo si la tarea lo exige
- tests/*.py puntuales
- configs/*.json puntuales

## Qué archivos NO debe leer

- data/*.csv y data/**/*.csv salvo resumen puntual generado por Python.
- runs/** completo.
- runs/*/trades.csv, equity_curve.csv o spy_comparison_daily.csv salvo anomalía puntual justificada.
- reports/** grandes o históricos no relacionados con la tarea.
- runs.zip u otros dumps comprimidos.
- datos de entrada crudos para backtests.

## Inputs mínimos esperados

- contrato de cambio
- archivos puntuales
- criterios de aceptación
- restricciones de no tocar trading logic

## Outputs esperados

- script/utilidad pequeña
- reporte generado
- errores claros si faltan archivos
- sin cambios de baseline/parent

## Reglas duras

- No inventar datos.
- No correr backtests sin pedido explícito.
- No promover baseline sin audit.json y comparaciones SPY diaria, mensual y anual.
- No cambiar state/current_parent.json sin aprobación manual explícita.
- No modificar lógica de backtesting desde tareas de análisis/contexto.
- Comparar siempre contra SPY; SPY es el costo de oportunidad.
- Costos obligatorios: 0.24% compra + 0.24% venta.
- Python calcula; agentes leen evidencia compacta y deciden.

## Estado actual relevante

- Project: `trading_agentic_research` (ok)
- Benchmark: `SPY`
- Cost per side: `0.24%`
- Frequencies: signal `weekly`, rebalance `monthly`, execution `daily`
- Current parent: `AUTO_002` / `HYP_AUTO_TIME_SERIES_MOMENTUM_SEED` (ok)
- Parent manual approval required: `True`
- Parent promotion blocked: `True`
- Current baseline: `None` / `SP500_MOMENTUM_TREND_BASELINE_V1` (ok)
- Baseline reason: Initial bibliographic baseline, not validated yet
- Research loop: `completed`, mode `automatic_loop`, active family `cross_sectional_momentum`, last run `EXP_176` (ok)

### Recent compact notes
- Loop iteration started.
- Loop iteration completed.
- Loop iteration started.
- Loop iteration completed.
- Loop iteration started.
- Loop iteration completed.
- Loop iteration started.
- Loop iteration completed.

## Checklist de decisión

- ¿El cambio es chico y reversible?
- ¿Usa Python estándar cuando alcanza?
- ¿Evita modificar backtesting si no fue pedido?
- ¿Reporta missing sin fallar innecesariamente?

## Advertencias para ahorrar tokens

- Leer primero este context pack, no el repo entero.
- Para runs, pedir summary.md + metrics.json + audit.json antes de cualquier CSV.
- Si falta evidencia, reportar missing y parar; no compensar leyendo carpetas enormes.
- Pedir a Python un resumen nuevo cuando la evidencia compacta sea insuficiente.
- Mantener respuestas y decisiones breves: evidencia, decisión, próximo paso.

## Source file availability

- `AGENTS.md`: ok
- `SPEC.md`: ok
- `agents/analyst.md`: ok
- `agents/auditor.md`: ok
- `agents/coder.md`: ok
- `agents/coordinator.md`: ok
- `agents/executor.md`: ok
- `agents/librarian.md`: ok
- `agents/literature_researcher.md`: ok
- `configs/project_config.json`: ok
- `state/current_parent.json`: ok
- `state/current_baseline.json`: ok
- `state/research_state.json`: ok
