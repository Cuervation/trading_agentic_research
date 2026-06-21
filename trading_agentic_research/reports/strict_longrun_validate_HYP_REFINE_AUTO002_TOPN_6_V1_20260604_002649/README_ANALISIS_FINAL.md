# README_ANALISIS_FINAL

## Resumen ejecutivo
Strict longrun enfocada alrededor de DD7 SL18. Corridas completadas: 2. Fallidas: 0. Next open disponible: True.

## Mejor candidato anterior
HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_STRICT_R12_C22_E75_CR40_REDD_RECOVERED_DD7_SL18

## Mejor candidato nuevo
HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_LONGRUN_STRICT_STRICT_NEXT_CLOSE_R11_C22_E75_CR40_REDD_DD7_SL18

## Impacto slippage/costos
Ver `combined_strict_results.csv`. Ranking robusto penaliza DD, peor año, 2008/2025, pérdida con slippage y exposición baja.

## Portfolios finales
Ver `strict_portfolio_mix_results.csv`.

## Conclusión directa para Hernán
- DD7 SL18 sigue siendo principal salvo que `Best robust` supere claramente su Calmar/DD.
- DD8 SL20 solo vuelve a convenir si aparece arriba en Best Robust/Best To Trade.
- Next open: evaluado en top si disponible.
- Slippage 10 bps: revisar Best Slippage Resistant; no se inventó slippage.
- Paper trading: solo si best robust mantiene edge con 10 bps.
- No seguiría probando grillas amplias; solo fill model/paper.
