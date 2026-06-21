# Execution timing audit

## Resultado corto

| Evento | Timing default actual | Timing strict_next_close | Evidencia de código |
|---|---|---|---|
| `portfolio_drawdown_guard` | `same_close` | señal con cierre previo, ejecución en próximo close disponible | default usa `current_equity_dd_pct` del día y escala con `valuation_prices` del mismo día; strict usa `previous_equity_dd_pct` |
| reduced exposure | `same_close` en ajuste diario / rebalance del día | próximo close disponible tras señal previa | `_scale_positions_to_target_gross_exposure` vende con precio del día actual; strict cambia señal a día previo |
| crisis mode | `same_close` | próximo close disponible tras señal previa | igual que guard, estado crisis se deriva del DD diario |
| reentry | `same_close` | próximo close disponible tras señal previa | `_portfolio_reentry_allowed` usa DD/SPY row; strict pasa benchmark/DD previos |
| `position_stop_loss` | `same_close` | señal con cierre previo, salida en close actual | default evalúa stop con precio actual; strict usa `signal_prices=previous_valuation_prices` y ejecuta con precio actual |
| rebalance exits | `next_close` desde señal semanal | sin cambio material | `_build_rebalance_plan` usa primer daily close estrictamente posterior a `signal_date` |
| `market_filter_failed` | `next_close` desde señal semanal | sin cambio material | exit_reason dentro de rebalance plan ya ejecuta posterior al signal_date |
| `left_top_n` | `next_close` desde señal semanal | sin cambio material | idem rebalance exits |

## Lookahead

No aparece lookahead fuerte en rebalance semanal: las señales se ejecutan en el primer cierre diario posterior al `signal_date`.
La duda real estaba en guards/stops diarios: el modo default sí usa cierre del mismo día para detectar y ejecutar; eso es optimista para señales dependientes del cierre. `strict_next_close` corrige esa parte desplazando la detección al cierre previo y ejecutando en el cierre actual.

## Limitación

Esto sigue siendo close-to-close, no next-open. Para paper/live, la siguiente validación realista sería `strict_next_open` o un modelo de fill/slippage explícito.
