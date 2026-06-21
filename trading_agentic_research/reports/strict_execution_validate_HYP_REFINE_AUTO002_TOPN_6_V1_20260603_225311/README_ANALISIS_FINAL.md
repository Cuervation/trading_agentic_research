# README_ANALISIS_FINAL

## Resumen ejecutivo

Validación strict next-close completada. La limitación `execution_timing_uncertain=true` queda resuelta para guards/stops daily close: el default era optimista (`same_close`) para guards/stops, y `strict_next_close` desplaza la señal al cierre previo y ejecuta al próximo cierre disponible.

## Compatibilidad preservada

- Baseline original sin strict: CAGR 19.13%, Max DD -51.08%.
- Mejor global original sin strict: CAGR 14.04%, Max DD -32.64%.
- Resultado: baseline/default no cambió materialmente.

## Original vs strict

- Mejor global strict DD8 SL20: CAGR 13.42%, Max DD -32.81%, Calmar 0.409, delayed executions 210.
- Alternativa defensiva strict DD7 SL18: CAGR 13.97%, Max DD -32.06%, Calmar 0.436, delayed executions 209.
- Sub30 strict: CAGR 12.44%, Max DD -32.34%, Calmar 0.385; deja de ser sub -30 bajo strict.

## Costos/slippage

`cost2_slip2` duplica el costo por lado. Slippage base está en 0 porque no hay modelo/fill/slippage explícito configurado; por eso no se inventó impacto adicional.

- Mejor global strict cost2/slip2: CAGR 12.02%, Max DD -33.67%.
- Alternativa defensiva strict cost2/slip2: CAGR 11.00%, Max DD -32.95%.
- Sub30 strict cost2/slip2: CAGR 10.53%, Max DD -33.12%.

## Portfolios strict

Mejor portfolio por Calmar: `C_50_mejor_50_defensiva_strict` con CAGR 13.71%, Max DD -32.42%, Calmar 0.423.
No supera al mejor single strict (`DD7 SL18`, Calmar 0.436), aunque diversifica entre dos variantes razonables.

## Conclusión directa para Hernán

- R12 C22 E75 CR40 DD8 SL20 **sobrevive**, pero deja de ser la candidata principal bajo strict.
- DD7 SL18 conviene más: mejor CAGR, menor DD y mejor Calmar bajo strict.
- Sub30 no conviene como principal: bajo strict ya no mantiene DD sub -30.
- Portfolio combinado no supera al DD7 single, pero el 50/50 DD8+DD7 es alternativa razonable si querés diversificar reglas.
- Strict next-close **sí cambia la decisión**: favorece DD7 SL18.
- Paper trading: sí, pero con DD7 SL18 como candidata principal y aclarando que falta validar next-open/slippage real.
- Falta otra validación: modelo de fill `strict_next_open` o slippage por lado distinto de cero.

Pass/fail: `PASS_WITH_LIMITATIONS`
