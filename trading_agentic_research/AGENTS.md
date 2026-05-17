# AGENTS.md

## Decisión central

Este proyecto usa agentes para investigar estrategias, no para hacer magia. Python calcula; los agentes leen evidencia compacta y deciden. Si una estrategia no tiene comparación contra SPY y `audit.json`, NO se promueve.

## Reglas globales

- No inventar datos.
- No correr backtests sin pedido explícito.
- No promover estrategias sin `audit.json`.
- No promover estrategias sin comparación contra SPY diaria, mensual y anual.
- No leer CSV grandes desde agentes salvo que un script Python haya producido un resumen insuficiente o sospechoso.
- Código, funciones, módulos y JSON en inglés.
- Documentación puede estar en español.
- Mantener el sistema simple, auditable y barato en tokens.
- Costos obligatorios: `0.24%` por compra y `0.24%` por venta.

## Regla de bajo consumo de tokens

Los agentes deben leer primero:

1. `summary.md`
2. `metrics.json`
3. `audit.json`
4. archivos de estado compactos en `state/`

Los CSV grandes son para scripts Python, no para agentes. Un agente solo puede pedir lectura directa de CSV si necesita investigar una anomalía puntual y debe explicar por qué.

## Roles

### Coordinator

**Rol:** orquestar el proceso de research y decidir el siguiente paso.

**Puede leer:**

- `SPEC.md`
- `AGENTS.md`
- `configs/*.json`
- `state/*.json`
- `runs/*/summary.md`
- `runs/*/metrics.json`
- `runs/*/audit.json`

**Debe producir:**

- decisiones de estado en `state/research_state.json`
- actualización de `state/current_parent.json` cuando corresponda
- recomendación de siguiente candidato o rechazo

### Analyst

**Rol:** convertir bibliografía en hipótesis testeables.

**Puede leer:**

- `SPEC.md`
- `configs/strategy_registry.json`
- notas o resúmenes bibliográficos provistos por el usuario
- `state/parameter_effect_memory.json`
- `state/rejected_candidates.json`

**Debe producir:**

- hipótesis compactas de estrategia
- parámetros candidatos razonables
- explicación causal esperada

### Coder

**Rol:** implementar contratos Python simples y testeables cuando se pida código.

**Puede leer:**

- `SPEC.md`
- `backtester/*.py`
- `scripts/*.py`
- `tests/*.py`
- `configs/*.json`

**Debe producir:**

- cambios pequeños en `backtester/`, `scripts/` o `tests/`
- nombres en inglés
- código sin dependencias innecesarias

### Executor

**Rol:** ejecutar corridas aprobadas y producir artefactos.

**Puede leer:**

- `configs/*.json`
- `state/current_baseline.json`
- `state/current_parent.json`
- scripts Python necesarios
- datos de entrada validados por Python

**Debe producir por corrida:**

- `spy_comparison_daily.csv`
- `spy_comparison_monthly.csv`
- `spy_comparison_yearly.csv`
- `metrics.json`
- `audit.json`
- `summary.md`

### Auditor

**Rol:** revisar si el resultado es confiable o debe rechazarse.

**Puede leer:**

- `SPEC.md`
- `runs/*/summary.md`
- `runs/*/metrics.json`
- `runs/*/audit.json`
- comparaciones contra SPY cuando sea necesario
- tests relevantes

**Debe producir:**

- decisión: `rejected`, `accepted_for_followup` o `promoted_to_baseline`
- razones concretas
- flags de sesgo: lookahead, survivorship, overfitting, leakage, costos faltantes

### Librarian

**Rol:** mantener orden conceptual y bibliográfico.

**Puede leer:**

- `SPEC.md`
- `configs/strategy_registry.json`
- notas bibliográficas
- `state/rejected_candidates.json`
- `state/parameter_effect_memory.json`

**Debe producir:**

- referencias normalizadas
- familias de estrategias
- detección de duplicados conceptuales

## Archivos críticos

| Archivo | Dueño principal | Propósito |
|---|---|---|
| `SPEC.md` | Coordinator / Auditor | Contrato del proyecto. |
| `configs/strategy_registry.json` | Librarian / Analyst | Catálogo de estrategias. |
| `configs/project_config.json` | Coordinator | Configuración global. |
| `state/research_state.json` | Coordinator | Estado actual del research. |
| `state/current_baseline.json` | Coordinator / Auditor | Baseline vigente. |
| `state/rejected_candidates.json` | Auditor | Historial de rechazos. |
| `state/parameter_effect_memory.json` | Analyst / Librarian | Aprendizaje causal de parámetros. |
| `runs/*/summary.md` | Executor | Resumen compacto para agentes. |
| `runs/*/metrics.json` | Executor | Métricas calculadas por Python. |
| `runs/*/audit.json` | Auditor / Executor | Evidencia de auditoría. |

## Regla de promoción

Una estrategia solo puede ser `promoted_to_baseline` si:

- existe `audit.json`,
- existen comparaciones contra SPY diaria, mensual y anual,
- pasó costos obligatorios,
- no tiene sospecha de lookahead,
- supera a SPY en CAGR,
- gana contra SPY en varios años,
- y no depende de un único período raro.

Si falta evidencia, se rechaza o queda como `accepted_for_followup`. NO se promociona. Así se construye research serio: con evidencia, no con ganas.

### Literature Researcher

**Rol:** convertir bibliografía y evidencia empírica en hipótesis testeables.

**Puede leer:**

- `bibliography/sources.yaml`
- `bibliography/extracted_principles.jsonl`
- `bibliography/hypothesis_bank.jsonl`
- `state/learning_memory.json`
- `state/evidence_memory.json`

**Debe producir:**

- hipótesis con `bibliography_basis` o `empirical_basis`
- referencias `source_id`, `run_id` o `learning_id`
- flags: `concentration_risk`, `riskier_candidate`, `defensive_improvement` cuando aplique

**Regla dura:** no generar variantes random sin justificación.
