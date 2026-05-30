# DD20 Champion Audit

Auditoría comparativa de las tres mejores candidatas DD20 detectadas esta semana. No se modificó lógica de trading, configs, baseline ni parent.

## Conclusión rápida
- Mejor candidata drawdown-first: `DD20ADAPT_105_HYP_DD20_CAGR_SL12_TOPN8_GUARD18_10_V1` (10.87% CAGR, DD -19.79%).
- Más conservadora: `DD20ADAPT_105_HYP_DD20_CAGR_SL10P5_TOPN8_GUARD18_10_V1` (DD -19.19%).
- Mejor consistencia vs SPY: `DD20ADAPT_107_HYP_DD20_CAGR_DYN8055250_SL10_TOPN8_V1` (14/11 años win/loss).

## Tabla ejecutiva

| run_id | CAGR | DD | SPY CAGR | excess CAGR | años W/L | meses W/L | trades | calmar |
|:---|---:|---:|---:|---:|:---:|:---:|---:|---:|
| `DD20ADAPT_105_HYP_DD20_CAGR_SL12_TOPN8_GUARD18_10_V1` | 10.87% | -19.79% | 6.80% | 4.06% | 13/11 | 135/121 | 2351 | 0.549 |
| `DD20ADAPT_107_HYP_DD20_CAGR_DYN8055250_SL10_TOPN8_V1` | 10.43% | -19.33% | 6.80% | 3.63% | 14/11 | 136/129 | 2387 | 0.540 |
| `DD20ADAPT_105_HYP_DD20_CAGR_SL10P5_TOPN8_GUARD18_10_V1` | 10.26% | -19.19% | 6.80% | 3.46% | 13/11 | 136/127 | 2370 | 0.535 |

## Principales debilidades
- `DD20ADAPT_105_HYP_DD20_CAGR_SL12_TOPN8_GUARD18_10_V1` tuvo debilidad fuerte en 2023: -23.52% vs SPY.
- `DD20ADAPT_105_HYP_DD20_CAGR_SL10P5_TOPN8_GUARD18_10_V1` tuvo debilidad fuerte en 2023: -23.38% vs SPY.
- `DD20ADAPT_107_HYP_DD20_CAGR_DYN8055250_SL10_TOPN8_V1` tuvo debilidad fuerte en 2023: -23.16% vs SPY.
- `DD20ADAPT_107_HYP_DD20_CAGR_DYN8055250_SL10_TOPN8_V1` tuvo debilidad fuerte en 2025: -21.59% vs SPY.
- `DD20ADAPT_105_HYP_DD20_CAGR_SL10P5_TOPN8_GUARD18_10_V1` tuvo debilidad fuerte en 2019: -21.33% vs SPY.
- `DD20ADAPT_105_HYP_DD20_CAGR_SL10P5_TOPN8_GUARD18_10_V1` tuvo debilidad fuerte en 2025: -21.22% vs SPY.
- `DD20ADAPT_105_HYP_DD20_CAGR_SL12_TOPN8_GUARD18_10_V1` peor episodio DD: -19.79% entre 2024-12-06 y 2025-11-20.
- `DD20ADAPT_107_HYP_DD20_CAGR_DYN8055250_SL10_TOPN8_V1` peor episodio DD: -19.33% entre 2024-12-06 y 2025-11-20.
- `DD20ADAPT_105_HYP_DD20_CAGR_SL10P5_TOPN8_GUARD18_10_V1` peor episodio DD: -19.19% entre 2024-12-06 y 2025-11-20.
- `DD20ADAPT_105_HYP_DD20_CAGR_SL12_TOPN8_GUARD18_10_V1` perdedores: 757 trades, mediana -8.95%.
- `DD20ADAPT_107_HYP_DD20_CAGR_DYN8055250_SL10_TOPN8_V1` perdedores: 796 trades, mediana -10.70%.
- `DD20ADAPT_105_HYP_DD20_CAGR_SL10P5_TOPN8_GUARD18_10_V1` perdedores: 789 trades, mediana -11.05%.

## Próximos experimentos recomendados
- No promover baseline todavía: primero revisar los años/meses malos y la causa de defensividad vs SPY.
- Separar experimento de asset-selection vs risk-management: si un año pierde por selección, tocar stop/guardrail no ataca la raíz.
- Revisar exposición/cash en 2023-2025 antes de relajar guardrails. Si SPY subió fuerte y el sistema quedó en cash, el problema es oportunidad perdida, no solo DD.
- Mantener el orden drawdown-first: DD < 20%, después CAGR, después años ganados vs SPY.

## Archivos generados
- `champion_summary.csv`
- `yearly_vs_spy.csv`
- `monthly_vs_spy.csv`
- `drawdown_episodes.csv`
- `trade_quality.csv`
- `regime_breakdown.csv`
- `bad_periods_report.md`
- `README_AUDIT_DD20_CHAMPIONS.md`

## Limitaciones de datos
- Missing SPY regime columns: ['spy_channel_r2', 'spy_channel_slope_pct']
