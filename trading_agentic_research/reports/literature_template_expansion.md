# Literature Template Expansion

Planning report for new literature templates supported by existing feature columns.

- Generated at: `2026-05-20T20:30:57.216214+00:00`
- Mode: `write`
- Writeable proposals: **0**
- Blocked proposals: **9**

## Writeable proposals

| hypothesis | family | required features |
|---|---|---|
| - | - | - |

## Blocked proposals

| hypothesis | reasons | missing features |
|---|---|---|
| `HYP_LITEXP_AUTO_002_RET52_DRAWDOWN26_PROXY_V1` | id_exists, duplicate_override_signature | - |
| `HYP_LITEXP_AUTO_002_RET52_VOL12_LOW_VOL_PROXY_V1` | id_exists, duplicate_override_signature | - |
| `HYP_LITEXP_AUTO_002_RET52_RET12_CONFIRM_PROXY_V1` | id_exists, duplicate_override_signature | - |
| `HYP_LITEXP_AUTO_002_RET52_SPY_SLOPE_REGIME_V1` | id_exists, duplicate_override_signature | - |
| `HYP_LITEXP_AUTO_002_R2_DRAWDOWN26_QUALITY_PULLBACK_V1` | id_exists, duplicate_override_signature | - |
| `HYP_LITEXP_AUTO_002_RESIDUAL26_BREADTH45_DD26_V1` | id_exists, duplicate_override_signature | - |
| `HYP_LITEXP_AUTO_002_RESIDUAL26_LOWVOL13_CONFIRM_V1` | id_exists, duplicate_override_signature | - |
| `HYP_LITEXP_AUTO_002_BREADTH_TREND_QUALITY_V1` | id_exists, duplicate_override_signature | - |
| `HYP_LITEXP_AUTO_002_SECTOR_REL26_LOWDD_V1` | id_exists, duplicate_override_signature | - |

## Suggested dry-run command

```powershell
python .\scripts\research\literature_template_expander.py `
  --state-dir .\state `
  --reports-dir .\reports `
  --hypothesis-bank .\bibliography\hypothesis_bank.jsonl `
  --paper-ideas .\bibliography\paper_ideas.jsonl `
  --no-record-missing-tasks
```
