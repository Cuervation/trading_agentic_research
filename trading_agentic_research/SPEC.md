# SPEC

## Decisión central

El proyecto busca estrategias de trading basadas en bibliografía que superen a SPY de forma consistente. No alcanza con que una estrategia gane dinero nominalmente: SIEMPRE debe evaluarse contra SPY, porque SPY es el costo de oportunidad real.

## 1. Objetivo

Buscar, testear y auditar estrategias de trading sobre S&P 500 / SPY basadas en bibliografía, empezando por momentum + trend following.

La investigación debe producir aprendizaje reutilizable, no solo resultados aislados.

## 2. Regla principal

Una estrategia no es buena por tener retorno positivo.

Una estrategia solo es interesante si, comparada contra SPY:

- mejora retorno ajustado por riesgo,
- reduce drawdown de forma material,
- mejora estabilidad,
- o genera aprendizaje causal útil para nuevas hipótesis.

Si no supera a SPY ni reduce riesgo de forma clara, debe rechazarse. PUNTO. Acá no hacemos autoengaño con backtests lindos.

## 3. Comparación obligatoria contra SPY

Cada corrida debe producir estos archivos dentro de su carpeta de run:

| Archivo | Propósito |
|---|---|
| `spy_comparison_daily.csv` | Comparación diaria entre estrategia y SPY. |
| `spy_comparison_monthly.csv` | Comparación mes a mes contra SPY. |
| `spy_comparison_yearly.csv` | Comparación año a año contra SPY. |
| `metrics.json` | Métricas numéricas de estrategia, SPY y diferencia relativa. |
| `audit.json` | Resultado de auditoría: sesgos, costos, trades, decisión. |
| `summary.md` | Resumen corto para agentes humanos/LLM. |

Ninguna estrategia puede promocionarse si falta alguno de estos archivos.

## 4. Criterios de rechazo

Rechazar una estrategia si ocurre cualquiera de estas condiciones:

- `strategy_cagr < spy_cagr` y no mejora el drawdown de forma material.
- Pierde contra SPY en la mayoría de los años evaluados.
- Su ganancia depende de un solo año aislado.
- Tiene pocos trades para validar el comportamiento.
- El cambio no tuvo efecto real contra baseline o parent.
- Hay sospecha de `lookahead bias`.
- No se aplicaron costos.

El rechazo debe quedar registrado con una razón clara. Si no podés explicar por qué una estrategia gana, todavía no entendiste la estrategia.

## 5. Criterios de `accepted_for_followup`

Una corrida puede quedar como `accepted_for_followup` si aporta algo útil aunque no merezca promoción a baseline.

Ejemplos válidos:

- Mejora drawdown.
- Mejora estabilidad mensual o anual.
- Mejora exceso de retorno en una región clara del mercado.
- Produce aprendizaje causal sobre un parámetro, filtro o régimen.
- Muestra una señal prometedora pero todavía incompleta.

`accepted_for_followup` NO significa “estrategia ganadora”. Significa “vale la pena investigar más”.

## 6. Criterios de `promoted_to_baseline`

Promover una estrategia a baseline solo si cumple todo esto:

- Supera a SPY en CAGR.
- Supera a SPY en varios años, no solo en un evento raro.
- Tiene drawdown igual o mejor que SPY, o retorno extra suficiente para justificar más riesgo.
- Tiene suficientes trades para evaluar la hipótesis.
- No depende de un único período anómalo.
- Pasa auditoría completa.
- Tiene `audit.json` y comparación contra SPY diaria, mensual y anual.

Promover sin auditoría es una falla de proceso, no una decisión agresiva.

## 7. Regla de costos

Aplicar siempre:

- `0.24%` por compra.
- `0.24%` por venta.

El costo total ida y vuelta mínimo es `0.48%`.

Toda métrica reportada debe ser posterior a costos. Si una corrida no aplica costos, debe rechazarse automáticamente.

## 8. Arquitectura

| Capa | Responsabilidad |
|---|---|
| Weekly feature store | Generar señales. |
| Daily feature store | Ejecutar trades, equity diaria, stops y drawdown. |
| Python | Calcular métricas, comparaciones y artefactos. |
| Agentes | Leer summaries chicos, auditar y decidir. |

Regla de diseño: Python hace el cálculo pesado. Los agentes NO leen CSV grandes salvo que sea estrictamente necesario para auditar un problema específico.

## 9. Sesgos a controlar

Controlar explícitamente:

- `lookahead bias`: señales usando información futura.
- `survivorship bias`: universo construido solo con ganadores sobrevivientes.
- `overfitting`: parámetros ajustados al pasado sin robustez.
- `data leakage`: features contaminadas con resultados futuros.
- comparación injusta contra SPY: costos, fechas, exposición o frecuencia mal alineadas.

## 10. Fuera de alcance por ahora

- No implementar el backtester completo todavía.
- No descargar datos.
- No correr backtests.
- No agregar dependencias fuera de `pandas`, `numpy` y `pytest` sin justificación explícita.
