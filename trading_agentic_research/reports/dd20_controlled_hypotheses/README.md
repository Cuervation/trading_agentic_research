# DD20 Controlled Hypotheses

Este directorio contiene hipótesis DD20 controladas derivadas de la última auditoría compacta.

## Qué hay acá

- `configs/generated/dd20_controlled/*.json`: configs hipótesis, una por variante controlada.
- `reports/dd20_controlled_hypotheses/hypotheses.csv`: índice compacto de todas las hipótesis.
- `reports/dd20_controlled_hypotheses/latest_summary.md`: lectura humana rápida.

## Cómo usarlo

1. Revisá `latest_summary.md`.
2. Elegí solo las hipótesis con mejor alineación causal con la auditoría.
3. No correr backtests hasta tener aprobación explícita.
4. No tocar `current_parent` ni `current_baseline` desde acá.

## Familias

- `spy_fallback_partial`: usar SPY parcialmente cuando el régimen es positivo y el portafolio está demasiado en cash.
- `topn_dynamic`: expandir TOPN solo en régimen fuerte.
- `guardrail_dynamic`: relajar/resumir el guardrail de forma dinámica sin romper el cap de DD.
- `dd_compression`: apretar el drawdown objetivo hacia -15/-17 sin matar el CAGR.

## Disciplina

- No generar variantes random.
- No promover baseline.
- No leer CSV grandes ni runs completos para esta tarea.
- Si una hipótesis no mejora nada material contra su parent DD20, se descarta.
