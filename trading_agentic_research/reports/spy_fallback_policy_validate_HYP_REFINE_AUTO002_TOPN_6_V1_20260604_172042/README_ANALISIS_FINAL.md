# README_ANALISIS_FINAL

## Resumen ejecutivo
Mini-validaci?n SPY fallback sobre candidata principal strict_next_open + slippage 10 bps.

- current: CAGR 12.65% / DD -32.11% / fb 10 out 10
- allow_warmup_only: CAGR 14.09% / DD -31.30% / fb 10 out 10
- block_on_nan: CAGR 14.09% / DD -31.30% / fb 10 out 10

## Conclusi?n directa para Hern?n
- Fallback total: 10.
- Fallback fuera de warmup: 10.
- `fallback=True` es riesgoso porque ocurri? fuera del warmup definido de 252 d?as.
- Pol?tica recomendada: `block_on_nan` si mantiene m?tricas aceptables.
- Candidata principal: PASS.
- Paper trading: s? solo con pol?tica expl?cita y monitoreo de SPY fallback; no real-money todav?a sin paper.
- Falta: monitorear feed SPY y fallback count en paper trading.
