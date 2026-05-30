# Context Packs

Usá estos packs para darle a Codex el contexto justo según el rol. La idea es simple: menos repo entero, más contrato compacto.

## Qué pasarle a Codex según la tarea

| Tarea | Archivo recomendado |
|---|---|
| Orientación general del repo | `repo_context_pack.md` |
| Decidir próximo paso de research | `coordinator_context.md` |
| Crear hipótesis desde evidencia | `analyst_context.md` |
| Escribir scripts/utilidades | `coder_context.md` |
| Ejecutar corridas aprobadas | `executor_context.md` |
| Auditar resultados | `auditor_context.md` |
| Ordenar bibliografía/taxonomía | `librarian_context.md` |
| Convertir papers en hipótesis | `literature_researcher_context.md` |

## Cuándo usar cada context pack

- `coordinator_context.md`: Orquestar research, decidir próximo paso y mantener estado simple.
- `analyst_context.md`: Convertir evidencia/bibliografía en hipótesis testeables.
- `coder_context.md`: Implementar utilidades Python pequeñas, testeables y sin dependencias pesadas.
- `executor_context.md`: Ejecutar corridas aprobadas y producir artefactos comparables.
- `auditor_context.md`: Revisar sesgos, costos, robustez y confiabilidad antes de decidir.
- `librarian_context.md`: Mantener bibliografía, taxonomía y memoria conceptual ordenadas.
- `literature_researcher_context.md`: Convertir bibliografía y evidencia empírica en hipótesis testeables, no ideas vagas.

## Cómo evitar lectura innecesaria de CSV/runs

1. Pasá primero `repo_context_pack.md` + el pack del rol.
2. Para una corrida, pedí solo `summary.md`, `metrics.json` y `audit.json`.
3. Si falta evidencia anual/mensual, recién ahí permitir `spy_comparison_yearly.csv` o `spy_comparison_monthly.csv`.
4. No leer `spy_comparison_daily.csv`, `trades.csv` o `equity_curve.csv` salvo anomalía puntual.
5. Si hace falta detalle pesado, pedí un script Python que genere un resumen chico.

## Qué agente usar por problema

- ¿No sabés qué hacer después? `Coordinator`.
- ¿Querés una hipótesis nueva? `Analyst` o `Literature Researcher`.
- ¿Hay que crear un script o utilidad? `Coder`.
- ¿Hay que correr una estrategia aprobada? `Executor`.
- ¿Hay que decidir si un resultado sirve? `Auditor`.
- ¿Hay duplicados conceptuales o bibliografía desordenada? `Librarian`.

## Regla práctica

Si Codex pide leer un CSV grande, exigile primero que explique qué pregunta concreta no puede responder con los packs, `summary.md`, `metrics.json` y `audit.json`. Esto no es burocracia: es arquitectura. Si no cuidás el contexto, el agente se vuelve caro, lento y peor.
