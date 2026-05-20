# Missing Feature Priority

Actionable backlog for converting paper ideas into real hypotheses. This report is planning-only; it does not mutate feature stores or hypothesis history.

- Generated at: `2026-05-20T00:21:52.749372+00:00`
- Missing-feature tasks read: **25**
- Distinct missing features: **7**

## Priority table

| priority | feature | score | papers unlocked | cost | calculable now | nearby/current columns |
|---|---|---:|---:|---|:---:|---|
| high | `ret_13w_pct` | 16 | 4 | low | yes | `close_above_sma13w`, `close_ema_13w`, `close_ema_13w_slope_2w_pct`, `close_ema_13w_slope_4w_pct`, `ret_12w_pct` |
| high | `downside_vol_13w_pct` | 15 | 6 | medium | yes | `close_above_sma13w`, `close_ema_13w`, `close_ema_13w_slope_2w_pct`, `close_ema_13w_slope_4w_pct`, `close_vs_ema13w_pct` |
| high | `max_drawdown_26w_pct` | 12 | 1 | low | yes | `close_above_sma26w`, `close_ema_26w`, `close_ema_26w_slope_2w_pct`, `close_ema_26w_slope_4w_pct`, `drawdown_from_high_10_pct` |
| high | `market_breadth_above_sma50_pct` | 11 | 1 | medium | yes | `close_above_sma13w`, `close_above_sma20`, `close_above_sma200`, `close_above_sma26w`, `close_above_sma50` |
| high | `residual_ret_26w_pct` | 11 | 1 | medium | yes | `close_above_sma26w`, `close_ema_26w`, `close_ema_26w_slope_2w_pct`, `close_ema_26w_slope_4w_pct`, `ret_12w_pct` |
| medium | `realized_vol_13w_pct` | 9 | 1 | low | yes | `close_above_sma13w`, `close_ema_13w`, `close_ema_13w_slope_2w_pct`, `close_ema_13w_slope_4w_pct`, `close_ema_13w_slope_8w_pct` |
| low | `ret_vs_sector_26w_pct` | 6 | 1 | high | yes | `close_above_sma26w`, `close_ema_26w`, `close_ema_26w_slope_2w_pct`, `close_ema_26w_slope_4w_pct`, `close_vs_ema26w_pct` |

## Details

### `ret_13w_pct` — high priority

- Unlocks: **4** paper idea(s): cross_sectional_momentum_jegadeesh_titman, multi_lookback_momentum_confirmation, time_series_momentum_moskowitz_ooi_pedersen, trend_following_fast_slow_confirmation
- Formula: group by ticker; pct_change(13) * 100
- Base columns available: ticker, close
- Base columns missing: -
- Families: paper_time_series_momentum, paper_trend_following
- Nearby columns: close_above_sma13w, close_ema_13w, close_ema_13w_slope_2w_pct, close_ema_13w_slope_4w_pct, ret_12w_pct, ret_1d_pct, ret_1w_pct, ret_2w_pct, ret_3d_pct, ret_4w_pct, ret_52w_pct, ret_8w_pct
- Note: ret_12w_pct already exists, but ret_13w_pct is a distinct template dependency.

### `downside_vol_13w_pct` — high priority

- Unlocks: **6** paper idea(s): downside_volatility_momentum, drawdown_aware_momentum, faber_tactical_asset_allocation_regime_filter, low_volatility_momentum_drawdown_control, market_state_and_momentum_crashes, volatility_managed_portfolios
- Formula: rolling 13-week std using only negative weekly returns
- Base columns available: ticker, close
- Base columns missing: -
- Families: paper_downside_risk_momentum
- Nearby columns: close_above_sma13w, close_ema_13w, close_ema_13w_slope_2w_pct, close_ema_13w_slope_4w_pct, close_vs_ema13w_pct, close_vs_ema8w_pct, close_vs_sma10_pct, close_vs_sma13w_pct, close_vs_sma4w_pct, close_vs_sma8w_pct, dist_to_high_13w_pct, drawdown_from_high_13w_pct
- Note: Use the same return convention as realized_vol_13w_pct.

### `max_drawdown_26w_pct` — high priority

- Unlocks: **1** paper idea(s): drawdown_aware_momentum
- Formula: rolling 26-week max drawdown from rolling peak close
- Base columns available: ticker, close
- Base columns missing: -
- Families: paper_downside_risk_momentum
- Nearby columns: close_above_sma26w, close_ema_26w, close_ema_26w_slope_2w_pct, close_ema_26w_slope_4w_pct, drawdown_from_high_10_pct, drawdown_from_high_13w_pct, drawdown_from_high_200_pct, drawdown_from_high_20_pct, drawdown_from_high_26w_pct, drawdown_from_high_50_pct, drawdown_from_high_52w_pct, ret_26w_pct
- Note: drawdown_from_high_26w_pct exists as a near proxy; decide whether the exact max-drawdown definition is needed.

### `market_breadth_above_sma50_pct` — high priority

- Unlocks: **1** paper idea(s): market_breadth_momentum_regime
- Formula: percentage of active universe above 50-day or 10-week SMA by date
- Base columns available: ticker, close
- Base columns missing: -
- Families: paper_breadth_regime
- Nearby columns: close_above_sma13w, close_above_sma20, close_above_sma200, close_above_sma26w, close_above_sma50, close_above_sma52w, close_vs_sma50_pct, days_above_sma20_last10, days_above_sma50_last20, spy_close_vs_sma50_pct, volume_ratio_vs_sma50, weeks_above_sma13_last8
- Note: No external feature is needed if the weekly universe is representative, but membership survivorship must be documented.

### `residual_ret_26w_pct` — high priority

- Unlocks: **1** paper idea(s): idiosyncratic_momentum_residual_returns
- Formula: 26-week stock return residualized against SPY return via rolling beta or simple market subtraction baseline
- Base columns available: ticker, close
- Base columns missing: -
- Families: paper_residual_momentum
- Nearby columns: close_above_sma26w, close_ema_26w, close_ema_26w_slope_2w_pct, close_ema_26w_slope_4w_pct, ret_12w_pct, ret_1w_pct, ret_26w_pct, ret_2d_pct, ret_2w_pct, ret_4w_pct, ret_52w_pct, ret_8w_pct
- Note: Can start with market-residual before sector residual; document the model.

### `realized_vol_13w_pct` — medium priority

- Unlocks: **1** paper idea(s): volatility_managed_portfolios
- Formula: rolling 13-week std of weekly returns, annualization optional but must be documented
- Base columns available: ticker, close
- Base columns missing: -
- Families: paper_low_vol_momentum
- Nearby columns: close_above_sma13w, close_ema_13w, close_ema_13w_slope_2w_pct, close_ema_13w_slope_4w_pct, close_ema_13w_slope_8w_pct, close_sma_13w, close_sma_13w_slope_2w_pct, close_vs_ema13w_pct, close_vs_sma13w_pct, dist_to_low_13w_pct, ret_12w_pct, ret_1w_pct
- Note: volatility_12w_pct exists and can be used to validate scale/shape.

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
