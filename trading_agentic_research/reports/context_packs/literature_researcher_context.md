# Literature Researcher Context Pack

Generated: 2026-05-29T15:13:13.368822+00:00

## Rol del agente

Convertir bibliografía y evidencia empírica en hipótesis testeables, no ideas vagas.

## Qué archivos puede leer

- bibliography/sources.yaml
- bibliography/extracted_principles.jsonl
- bibliography/hypothesis_bank.jsonl
- state/learning_memory.json
- state/evidence_memory.json
- state/rejected_hypotheses.jsonl
- state/accepted_hypotheses.jsonl

## Qué archivos NO debe leer

- data/*.csv y data/**/*.csv salvo resumen puntual generado por Python.
- runs/** completo.
- runs/*/trades.csv, equity_curve.csv o spy_comparison_daily.csv salvo anomalía puntual justificada.
- reports/** grandes o históricos no relacionados con la tarea.
- runs.zip u otros dumps comprimidos.
- backtester/*.py salvo pedido explícito y acotado.
- scripts/*.py completos salvo script puntual relacionado.
- datos de entrada crudos para backtests.

## Inputs mínimos esperados

- source_id o run_id
- principio extraído
- aprendizaje previo
- familia objetivo

## Outputs esperados

- hipótesis con basis
- source_id/run_id/learning_id
- flags de riesgo
- cooldown si corresponde

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

- ¿Tiene bibliography_basis o empirical_basis?
- ¿No es variante random?
- ¿Incluye flags concentration_risk/riskier_candidate/defensive_improvement si aplica?
- ¿No promueve baseline?

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
