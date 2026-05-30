# Bad periods report - DD20 champions

Auditoría drawdown-first: preservar DD < 20% primero, mejorar CAGR segundo, y recién después años ganados vs SPY.

## Criterios
- Empate anual/mensual: diferencia contra SPY entre -1% y +1%.
- Las causas son inferencias desde exposición, cash, trades, stops y retorno relativo; si falta una columna, se reporta como limitación.

## DD20ADAPT_105_HYP_DD20_CAGR_SL12_TOPN8_GUARD18_10_V1

Strategy: `HYP_DD20_CAGR_SL12_TOPN8_GUARD18_10_V1`

### Peores años vs SPY

| año | estrategia | SPY | diff | marca | inferencia |
|---:|---:|---:|---:|:---|:---|
| 2023 | 1.29% | 24.81% | -23.52% | loss | mala selección de activos: retorno medio por trade negativo y mayoría de trades perdedores; poca exposición: exposición bruta promedio baja; exceso de cash: cash promedio alto; régimen SPY alcista donde la estrategia quedó defensiva |
| 2025 | -3.03% | 16.64% | -19.67% | loss | poca exposición: exposición bruta promedio baja; exceso de cash: cash promedio alto; stops frecuentes: alta proporción de salidas por stop; régimen SPY alcista donde la estrategia quedó defensiva |
| 1999 | 0.00% | 19.38% | -19.38% | loss | poca exposición: exposición bruta promedio baja; exceso de cash: cash promedio alto; régimen SPY alcista donde la estrategia quedó defensiva |
| 2019 | 14.44% | 28.65% | -14.21% | loss | régimen SPY alcista donde la estrategia quedó defensiva |
| 2009 | 10.96% | 19.88% | -8.92% | loss | poca exposición: exposición bruta promedio baja; exceso de cash: cash promedio alto; régimen SPY alcista donde la estrategia quedó defensiva |

### Foco 2023-2025

| año | estrategia | SPY | diff | lectura |
|---:|---:|---:|---:|:---|
| 2023 | 1.29% | 24.81% | -23.52% | mala selección de activos: retorno medio por trade negativo y mayoría de trades perdedores; poca exposición: exposición bruta promedio baja; exceso de cash: cash promedio alto; régimen SPY alcista donde la estrategia quedó defensiva |
| 2024 | 50.07% | 24.00% | 26.08% | sin deterioro claro contra SPY en la evidencia disponible |
| 2025 | -3.03% | 16.64% | -19.67% | poca exposición: exposición bruta promedio baja; exceso de cash: cash promedio alto; stops frecuentes: alta proporción de salidas por stop; régimen SPY alcista donde la estrategia quedó defensiva |

### Peores meses vs SPY

| mes | estrategia | SPY | diff | marca |
|:---|---:|---:|---:|:---|
| 2020-04 | 0.00% | 18.01% | -18.01% | loss |
| 2011-10 | 0.00% | 14.16% | -14.16% | loss |
| 2009-03 | 0.00% | 12.63% | -12.63% | loss |
| 2001-04 | 0.00% | 10.91% | -10.91% | loss |
| 2024-07 | -9.10% | 1.00% | -10.10% | loss |
| 2008-12 | 0.00% | 9.90% | -9.90% | loss |
| 2026-04 | 0.00% | 9.68% | -9.68% | loss |
| 2000-03 | -1.05% | 8.62% | -9.67% | loss |

## DD20ADAPT_107_HYP_DD20_CAGR_DYN8055250_SL10_TOPN8_V1

Strategy: `HYP_DD20_CAGR_DYN8055250_SL10_TOPN8_V1`

### Peores años vs SPY

| año | estrategia | SPY | diff | marca | inferencia |
|---:|---:|---:|---:|:---|:---|
| 2023 | 1.65% | 24.81% | -23.16% | loss | poca exposición: exposición bruta promedio baja; exceso de cash: cash promedio alto; régimen SPY alcista donde la estrategia quedó defensiva |
| 2025 | -4.95% | 16.64% | -21.59% | loss | mala selección de activos: retorno medio por trade negativo y mayoría de trades perdedores; poca exposición: exposición bruta promedio baja; exceso de cash: cash promedio alto; stops frecuentes: alta proporción de salidas por stop; régimen SPY alcista donde la estrategia quedó defensiva |
| 2019 | 8.55% | 28.65% | -20.11% | loss | régimen SPY alcista donde la estrategia quedó defensiva |
| 1999 | 0.00% | 19.38% | -19.38% | loss | poca exposición: exposición bruta promedio baja; exceso de cash: cash promedio alto; régimen SPY alcista donde la estrategia quedó defensiva |
| 2004 | -1.02% | 8.67% | -9.68% | loss | poca exposición: exposición bruta promedio baja; exceso de cash: cash promedio alto; stops frecuentes: alta proporción de salidas por stop |

### Foco 2023-2025

| año | estrategia | SPY | diff | lectura |
|---:|---:|---:|---:|:---|
| 2023 | 1.65% | 24.81% | -23.16% | poca exposición: exposición bruta promedio baja; exceso de cash: cash promedio alto; régimen SPY alcista donde la estrategia quedó defensiva |
| 2024 | 48.97% | 24.00% | 24.97% | sin deterioro claro contra SPY en la evidencia disponible |
| 2025 | -4.95% | 16.64% | -21.59% | mala selección de activos: retorno medio por trade negativo y mayoría de trades perdedores; poca exposición: exposición bruta promedio baja; exceso de cash: cash promedio alto; stops frecuentes: alta proporción de salidas por stop; régimen SPY alcista donde la estrategia quedó defensiva |

### Peores meses vs SPY

| mes | estrategia | SPY | diff | marca |
|:---|---:|---:|---:|:---|
| 2020-04 | 0.00% | 18.01% | -18.01% | loss |
| 2011-10 | 0.00% | 14.16% | -14.16% | loss |
| 2009-03 | 0.00% | 12.63% | -12.63% | loss |
| 2001-04 | 0.00% | 10.91% | -10.91% | loss |
| 2024-07 | -9.32% | 1.00% | -10.33% | loss |
| 2000-03 | -1.39% | 8.62% | -10.02% | loss |
| 2008-12 | 0.00% | 9.90% | -9.90% | loss |
| 2003-12 | -6.32% | 3.42% | -9.74% | loss |

## DD20ADAPT_105_HYP_DD20_CAGR_SL10P5_TOPN8_GUARD18_10_V1

Strategy: `HYP_DD20_CAGR_SL10P5_TOPN8_GUARD18_10_V1`

### Peores años vs SPY

| año | estrategia | SPY | diff | marca | inferencia |
|---:|---:|---:|---:|:---|:---|
| 2023 | 1.44% | 24.81% | -23.38% | loss | mala selección de activos: retorno medio por trade negativo y mayoría de trades perdedores; poca exposición: exposición bruta promedio baja; exceso de cash: cash promedio alto; régimen SPY alcista donde la estrategia quedó defensiva |
| 2019 | 7.32% | 28.65% | -21.33% | loss | régimen SPY alcista donde la estrategia quedó defensiva |
| 2025 | -4.58% | 16.64% | -21.22% | loss | mala selección de activos: retorno medio por trade negativo y mayoría de trades perdedores; poca exposición: exposición bruta promedio baja; exceso de cash: cash promedio alto; stops frecuentes: alta proporción de salidas por stop; régimen SPY alcista donde la estrategia quedó defensiva |
| 1999 | 0.00% | 19.38% | -19.38% | loss | poca exposición: exposición bruta promedio baja; exceso de cash: cash promedio alto; régimen SPY alcista donde la estrategia quedó defensiva |
| 2004 | -0.89% | 8.67% | -9.56% | loss | poca exposición: exposición bruta promedio baja; exceso de cash: cash promedio alto; stops frecuentes: alta proporción de salidas por stop |

### Foco 2023-2025

| año | estrategia | SPY | diff | lectura |
|---:|---:|---:|---:|:---|
| 2023 | 1.44% | 24.81% | -23.38% | mala selección de activos: retorno medio por trade negativo y mayoría de trades perdedores; poca exposición: exposición bruta promedio baja; exceso de cash: cash promedio alto; régimen SPY alcista donde la estrategia quedó defensiva |
| 2024 | 47.74% | 24.00% | 23.74% | sin deterioro claro contra SPY en la evidencia disponible |
| 2025 | -4.58% | 16.64% | -21.22% | mala selección de activos: retorno medio por trade negativo y mayoría de trades perdedores; poca exposición: exposición bruta promedio baja; exceso de cash: cash promedio alto; stops frecuentes: alta proporción de salidas por stop; régimen SPY alcista donde la estrategia quedó defensiva |

### Peores meses vs SPY

| mes | estrategia | SPY | diff | marca |
|:---|---:|---:|---:|:---|
| 2020-04 | 0.00% | 18.01% | -18.01% | loss |
| 2011-10 | 0.00% | 14.16% | -14.16% | loss |
| 2009-03 | 0.00% | 12.63% | -12.63% | loss |
| 2001-04 | 0.00% | 10.91% | -10.91% | loss |
| 2003-12 | -6.71% | 3.42% | -10.13% | loss |
| 2024-07 | -9.10% | 1.00% | -10.10% | loss |
| 2008-12 | 0.00% | 9.90% | -9.90% | loss |
| 2026-04 | 0.00% | 9.68% | -9.68% | loss |
