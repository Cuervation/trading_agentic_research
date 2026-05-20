# Missing Feature Priority

Actionable backlog for converting paper ideas into real hypotheses. This report is planning-only; it does not mutate feature stores or hypothesis history.

- Generated at: `2026-05-20T01:26:46.310933+00:00`
- Missing-feature tasks read: **25**
- Distinct missing features: **1**

## Priority table

| priority | feature | score | papers unlocked | cost | calculable now | nearby/current columns |
|---|---|---:|---:|---|:---:|---|
| low | `ret_vs_sector_26w_pct` | 6 | 1 | high | yes | `close_above_sma26w`, `close_ema_26w`, `close_ema_26w_slope_2w_pct`, `close_ema_26w_slope_4w_pct`, `close_vs_ema26w_pct` |

## Details

### `ret_vs_sector_26w_pct` — low priority

- Unlocks: **1** paper idea(s): sector_industry_relative_momentum
- Formula: stock ret_26w_pct minus sector aggregate ret_26w_pct
- Base columns available: ticker, close
- Base columns missing: -
- Families: paper_sector_momentum
- Nearby columns: close_above_sma26w, close_ema_26w, close_ema_26w_slope_2w_pct, close_ema_26w_slope_4w_pct, close_vs_ema26w_pct, close_vs_sma26w_pct, close_vs_sma52w_pct, dist_to_low_26w_pct, ret_12w_pct, ret_26w_pct, ret_2w_pct, ret_52w_pct
- Note: Requires sector/industry mapping; none is assumed from price columns alone.

## Suggested command

```powershell
python .\scripts\research\missing_feature_task_prioritizer.py `
  --state-dir .\state `
  --reports-dir .\reports `
  --paper-ideas .\bibliography\paper_ideas.jsonl
```

Next: implement the highest-priority feature or use an existing proxy template; then rerun literature mining before launching backtests.
