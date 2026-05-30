# Repository Context Pack

Generated: 2026-05-29T15:13:13.363319+00:00

## Decisión central

Este repo usa Python para calcular y agentes para decidir sobre evidencia compacta. Nada se promueve sin auditoría y comparación completa contra SPY.

## Reglas duras globales

- No inventar datos.
- No correr backtests sin pedido explícito.
- No promover baseline sin audit.json y comparaciones SPY diaria, mensual y anual.
- No cambiar state/current_parent.json sin aprobación manual explícita.
- No modificar lógica de backtesting desde tareas de análisis/contexto.
- Comparar siempre contra SPY; SPY es el costo de oportunidad.
- Costos obligatorios: 0.24% compra + 0.24% venta.
- Python calcula; agentes leen evidencia compacta y deciden.

## Lectura recomendada mínima

- Este repo_context_pack.md.
- Context pack específico del rol.
- Para una corrida: runs/<run_id>/summary.md, metrics.json y audit.json.
- Solo después, monthly/yearly SPY CSV si el resumen no alcanza.

## No leer por defecto

- data/*.csv y data/**/*.csv salvo resumen puntual generado por Python.
- runs/** completo.
- runs/*/trades.csv, equity_curve.csv o spy_comparison_daily.csv salvo anomalía puntual justificada.
- reports/** grandes o históricos no relacionados con la tarea.
- runs.zip u otros dumps comprimidos.

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

## Roles disponibles

- `coordinator`: Orquestar research, decidir próximo paso y mantener estado simple.
- `analyst`: Convertir evidencia/bibliografía en hipótesis testeables.
- `coder`: Implementar utilidades Python pequeñas, testeables y sin dependencias pesadas.
- `executor`: Ejecutar corridas aprobadas y producir artefactos comparables.
- `auditor`: Revisar sesgos, costos, robustez y confiabilidad antes de decidir.
- `librarian`: Mantener bibliografía, taxonomía y memoria conceptual ordenadas.
- `literature_researcher`: Convertir bibliografía y evidencia empírica en hipótesis testeables, no ideas vagas.

## Token discipline

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
