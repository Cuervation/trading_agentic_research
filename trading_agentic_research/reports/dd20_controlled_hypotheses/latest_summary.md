# DD20 Controlled Hypotheses

Esta generación usa solo evidencia compacta: context packs + última auditoría DD20. No se ejecutaron backtests y no se tocó current_parent ni current_baseline.

## Fuente de evidencia
- Audit folder: `C:\Pythons\ML-Trading\Momentum\trading_agentic_research\reports\dd20_champion_audit\20260529_115541`

## Context packs disponibles

- `repo_context_pack.md`: ok
- `coordinator_context.md`: ok
- `analyst_context.md`: ok
- `coder_context.md`: ok
- `executor_context.md`: ok
- `auditor_context.md`: ok
- `librarian_context.md`: ok
- `literature_researcher_context.md`: ok

## Resumen
- Hipótesis generadas: 12
- Familias: spy_fallback_partial=3, topn_dynamic=3, guardrail_dynamic=3, dd_compression=3

## Hipótesis más prometedoras
- `HYP_DD20_CTRL_DD_COMPRESS_17_45_V1` — Move max drawdown toward -15/-17 while keeping the strategy above SPY. (parent `DD20ADAPT_105_HYP_DD20_CAGR_SL10P5_TOPN8_GUARD18_10_V1`, riesgo High).
- `HYP_DD20_CTRL_SPY_FALLBACK_50_V1` — Reduce opportunity loss in positive SPY regimes by replacing a controlled slice of idle cash with SPY exposure. (parent `DD20ADAPT_105_HYP_DD20_CAGR_SL12_TOPN8_GUARD18_10_V1`, riesgo Medium).
- `HYP_DD20_CTRL_TOPN_DYNAMIC_12_8_V1` — Expand the book only in strong SPY regimes and keep TOPN tight when SPY is weak. (parent `DD20ADAPT_105_HYP_DD20_CAGR_SL12_TOPN8_GUARD18_10_V1`, riesgo Medium).
- `HYP_DD20_CTRL_GUARD_DYNAMIC_12_20_V1` — Reduce time spent locked out by the guard while still hard-stopping near -20%. (parent `DD20ADAPT_107_HYP_DD20_CAGR_DYN8055250_SL10_TOPN8_V1`, riesgo Medium-high).

## Criterios usados
- No más de 12 hipótesis.
- Cada hipótesis surge de una lectura causal de la auditoría: cash alto, exposición baja, guard activado, o DD cerca del cap.
- Sin variantes random.
- Sin backtests.

## Próximo paso recomendado
Si querés validar estas hipótesis, el siguiente paso debería ser un filtro de prioridad o un set de tareas de ejecución, no correr todo de golpe.
