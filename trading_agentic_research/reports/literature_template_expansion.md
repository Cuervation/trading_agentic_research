# Literature Template Expansion

Planning report for new literature templates supported by existing feature columns.

- Generated at: `2026-05-19T23:56:29.186386+00:00`
- Mode: `write`
- Writeable proposals: **5**
- Blocked proposals: **0**

## Writeable proposals

| hypothesis | family | required features |
|---|---|---|
| `HYP_LITEXP_AUTO_002_RET52_DRAWDOWN26_PROXY_V1` | `paper_drawdown_proxy_momentum` | `ret_52w_pct`, `drawdown_from_high_26w_pct`, `close` |
| `HYP_LITEXP_AUTO_002_RET52_VOL12_LOW_VOL_PROXY_V1` | `paper_volatility_proxy_momentum` | `ret_52w_pct`, `volatility_12w_pct`, `close` |
| `HYP_LITEXP_AUTO_002_RET52_RET12_CONFIRM_PROXY_V1` | `paper_near_horizon_confirmation` | `ret_52w_pct`, `ret_12w_pct`, `close` |
| `HYP_LITEXP_AUTO_002_RET52_SPY_SLOPE_REGIME_V1` | `paper_regime_slope_filter` | `ret_52w_pct`, `spy_close_sma_50_slope_5d_pct`, `close` |
| `HYP_LITEXP_AUTO_002_R2_DRAWDOWN26_QUALITY_PULLBACK_V1` | `paper_quality_pullback_momentum` | `channel_r2`, `drawdown_from_high_26w_pct`, `close` |

## Blocked proposals

| hypothesis | reasons | missing features |
|---|---|---|

## Suggested dry-run command

```powershell
python .\scripts\research\literature_template_expander.py `
  --state-dir .\state `
  --reports-dir .\reports `
  --hypothesis-bank .\bibliography\hypothesis_bank.jsonl `
  --paper-ideas .\bibliography\paper_ideas.jsonl `
  --no-record-missing-tasks
```
