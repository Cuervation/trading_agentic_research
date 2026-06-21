# PAPER_TRADING_CHECKLIST

- [x] Configuraci?n congelada PAPER_V1.
- [x] strict_next_open activo.
- [x] slippage 10 bps por lado activo.
- [x] SPY block_on_nan activo.
- [x] Runner PAPER-only.
- [x] Config hash + lock obligatorio.
- [x] Resume/state store creado.
- [x] Monitoreo diario creado.
- [x] ?rdenes PAPER=true.
- [x] Cero integraci?n live.

## Detener paper si
- error de datos;
- config hash diferente;
- DD paper excede l?mite;
- diferencia se?al/ejecuci?n inexplicable;
- SPY fallback fuera de pol?tica;
- p?rdida/corrupci?n estado;
- fill imposible.
