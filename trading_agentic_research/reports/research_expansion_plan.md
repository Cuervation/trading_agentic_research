# Research Expansion Plan

Current result: **executable research work is available; run the autonomous wrapper before expanding capabilities further.**

- Generated at: `2026-05-20T00:21:52.783149+00:00`
- Parent stays locked: `AUTO_002` / `HYP_AUTO_TIME_SERIES_MOMENTUM_SEED`
- Recommended mode: `None`
- Eligible: `True`
- Executable count: `None`
- Feature-space stall: `None` (None)

## Current executable work

- Selector found executable work: HYP_LITEXP_AUTO_002_RET52_VOL12_LOW_VOL_PROXY_V1 (paper_volatility_proxy_momentum). Run the autonomous wrapper before doing more expansion work.

### Blocker counts

| blocker | count |
|---|---:|
| - | 0 |

## Exhausted and cooldown families

### Semantically exhausted branches

| family | branch | reason | events |
|---|---|---|---:|
| `candidate_under_review_drawdown_refinement` | `candidate_under_review_drawdown_refinement/unknown_field/rank_exit` | duplicate_threshold_reached:3 | 3 |
| `cross_sectional_momentum` | `cross_sectional_momentum/unknown_field/unknown_layer` | duplicate_threshold_reached:3 | 5 |
| `feature_space_composite_confirmation` | `feature_space_composite_confirmation/close_sma_50_slope_5d_pct/rank_confirmation` | bad_threshold_reached:4 | 4 |
| `feature_space_composite_confirmation` | `feature_space_composite_confirmation/close_vs_sma20w_pct/rank_confirmation` | bad_threshold_reached:4 | 4 |
| `feature_space_composite_exit` | `feature_space_composite_exit/channel_r2/rank_exit` | duplicate_threshold_reached:7 | 7 |
| `feature_space_composite_exit` | `feature_space_composite_exit/channel_slope_pct/rank_exit` | duplicate_threshold_reached:7 | 7 |
| `feature_space_composite_exit` | `feature_space_composite_exit/close_sma_50_slope_5d_pct/rank_exit` | duplicate_threshold_reached:2 | 2 |
| `paper_low_vol_momentum` | `paper_low_vol_momentum/unknown_field/unknown_layer` | duplicate_threshold_reached:3 | 3 |
| `paper_quality_momentum` | `paper_quality_momentum/unknown_field/unknown_layer` | duplicate_threshold_reached:3 | 4 |
| `paper_regime_filter` | `paper_regime_filter/unknown_field/rank_market_filter` | duplicate_threshold_reached:2 | 4 |
| `paper_time_series_momentum` | `paper_time_series_momentum/unknown_field/unknown_layer` | bad_threshold_reached:5 | 5 |
| `paper_time_series_momentum` | `paper_time_series_momentum/v2/pure_ranking` | duplicate_threshold_reached:2 | 2 |
| `trend_following` | `trend_following/unknown_field/rank_exit` | duplicate_threshold_reached:2 | 2 |

### Families only in cooldown/advisory block

| family | hard cooldown | reason |
|---|:---:|---|
| `can_slim` | no | repeated_failed_hypotheses |
| `candidate_under_review_exit_refinement` | no | repeated_failed_hypotheses |
| `darvas_box` | no | repeated_failed_hypotheses |
| `feature_space_composite_concentration` | no | repeated_failed_hypotheses |
| `feature_space_regime` | no | repeated_failed_hypotheses |
| `low_volatility` | no | repeated_failed_hypotheses |
| `mixed` | no | repeated_failed_hypotheses |
| `momentum` | no | repeated_failed_hypotheses |
| `paper_trend_following` | no | repeated_failed_hypotheses |
| `quality` | no | repeated_failed_hypotheses |
| `quality_momentum` | no | repeated_failed_hypotheses |
| `regime` | no | repeated_failed_hypotheses |
| `risk_control_refinement` | no | repeated_failed_hypotheses |
| `risk_management` | no | repeated_failed_hypotheses |
| `tactical_asset_allocation` | no | repeated_failed_hypotheses |
| `time_series_momentum_refinement` | no | repeated_failed_hypotheses |

## Paper ideas that did not become executable work

Paper ideas read: **15**

| source | title | blockers | missing features | generated hypotheses |
|---|---|---|---|---:|
| `multi_lookback_momentum_confirmation` | Multi-lookback momentum confirmation | missing_required_features, family_cooldown_or_exhausted, converted_but_currently_not_executable, missing_feature_task_exists | `ret_13w_pct` | 3 |
| `trend_following_fast_slow_confirmation` | Trend following fast and slow confirmation | missing_required_features, family_cooldown_or_exhausted, converted_but_currently_not_executable, missing_feature_task_exists | `ret_13w_pct` | 4 |
| `drawdown_aware_momentum` | Drawdown-aware momentum | missing_required_features, family_cooldown_or_exhausted, missing_feature_task_exists | `downside_vol_13w_pct` | 0 |
| `idiosyncratic_momentum_residual_returns` | Residual / idiosyncratic momentum | missing_required_features, family_cooldown_or_exhausted, missing_feature_task_exists | `residual_ret_26w_pct` | 0 |
| `market_breadth_momentum_regime` | Market breadth as momentum regime filter | missing_required_features, family_cooldown_or_exhausted, missing_feature_task_exists | `market_breadth_above_sma50_pct` | 0 |
| `sector_industry_relative_momentum` | Sector and industry relative strength | missing_required_features, family_cooldown_or_exhausted, missing_feature_task_exists | `ret_vs_sector_26w_pct` | 0 |
| `time_series_momentum_moskowitz_ooi_pedersen` | Time Series Momentum | missing_required_features, family_cooldown_or_exhausted, converted_but_currently_not_executable, missing_feature_task_exists | `ret_13w_pct` | 2 |
| `volatility_managed_portfolios` | Volatility managed portfolios | missing_required_features, family_cooldown_or_exhausted, missing_feature_task_exists | `downside_vol_13w_pct` | 0 |
| `cross_sectional_momentum_jegadeesh_titman` | Cross-sectional momentum | missing_required_features, family_cooldown_or_exhausted, missing_feature_task_exists | `ret_13w_pct` | 0 |
| `downside_volatility_momentum` | Downside-volatility momentum | missing_required_features, family_cooldown_or_exhausted, missing_feature_task_exists | `downside_vol_13w_pct` | 0 |
| `faber_tactical_asset_allocation_regime_filter` | Tactical asset allocation / regime filter | missing_required_features, family_cooldown_or_exhausted, converted_but_currently_not_executable, missing_feature_task_exists | `downside_vol_13w_pct` | 2 |
| `low_volatility_momentum_drawdown_control` | Low volatility anomaly and momentum crash control | missing_required_features, family_cooldown_or_exhausted, converted_but_currently_not_executable, missing_feature_task_exists | `downside_vol_13w_pct` | 3 |
| `market_state_and_momentum_crashes` | Market state and momentum crash control | missing_required_features, family_cooldown_or_exhausted, missing_feature_task_exists | `downside_vol_13w_pct` | 0 |
| `absolute_momentum_dual_momentum` | Absolute momentum and dual momentum | family_cooldown_or_exhausted, supported_template_not_materialized | - | 0 |
| `quality_momentum_trend_stability` | Quality momentum and trend stability | family_cooldown_or_exhausted, converted_but_currently_not_executable | - | 6 |

## Missing feature priorities

| priority | feature | papers unlocked | cost | calculable now | nearby/current columns |
|---|---|---:|---|:---:|---|
| high | `ret_13w_pct` | 4 | low | yes | `close_above_sma13w`, `close_ema_13w`, `close_ema_13w_slope_2w_pct`, `close_ema_13w_slope_4w_pct`, `ret_12w_pct` |
| high | `downside_vol_13w_pct` | 6 | medium | yes | `close_above_sma13w`, `close_ema_13w`, `close_ema_13w_slope_2w_pct`, `close_ema_13w_slope_4w_pct`, `close_vs_ema13w_pct` |
| high | `max_drawdown_26w_pct` | 1 | low | yes | `close_above_sma26w`, `close_ema_26w`, `close_ema_26w_slope_2w_pct`, `close_ema_26w_slope_4w_pct`, `drawdown_from_high_10_pct` |
| high | `market_breadth_above_sma50_pct` | 1 | medium | yes | `close_above_sma13w`, `close_above_sma20`, `close_above_sma200`, `close_above_sma26w`, `close_above_sma50` |
| high | `residual_ret_26w_pct` | 1 | medium | yes | `close_above_sma26w`, `close_ema_26w`, `close_ema_26w_slope_2w_pct`, `close_ema_26w_slope_4w_pct`, `ret_12w_pct` |
| medium | `realized_vol_13w_pct` | 1 | low | yes | `close_above_sma13w`, `close_ema_13w`, `close_ema_13w_slope_2w_pct`, `close_ema_13w_slope_4w_pct`, `close_ema_13w_slope_8w_pct` |
| low | `ret_vs_sector_26w_pct` | 1 | high | yes | `close_above_sma26w`, `close_ema_26w`, `close_ema_26w_slope_2w_pct`, `close_ema_26w_slope_4w_pct`, `close_vs_ema26w_pct` |

## Supported literature templates using existing features

These are proposals only. They are not written to the hypothesis bank by this planner.

| hypothesis | family | required features |
|---|---|---|
| - | - | - |

## Hypotheses that should become possible after expansion

| hypothesis | unlocked by | source | priority |
|---|---|---|---|
| `HYP_LIT_AUTO_002_FAST_TREND_SMA20_RET13_CONFIRM_V1` | `ret_13w_pct` | missing_feature_task | high |
| `HYP_LIT_AUTO_002_FAST_TREND_SMA20_RET13_CONFIRM_V4` | `ret_13w_pct` | missing_feature_task | high |
| `HYP_LIT_AUTO_002_PAPER_CROSS_SECTIONAL_MOMENTUM_RET52_RET13_CONFIRM_V4` | `ret_13w_pct` | missing_feature_task | high |
| `HYP_LIT_AUTO_002_PAPER_MULTI_LOOKBACK_MOMENTUM_CONFIRMATION_RET52_RET13_CONFIRM_V1` | `ret_13w_pct` | missing_feature_task | high |
| `HYP_LIT_AUTO_002_PAPER_MULTI_LOOKBACK_MOMENTUM_CONFIRMA_RET52_RET13_CONFIRM_V1` | `ret_13w_pct` | missing_feature_task | high |
| `HYP_LIT_AUTO_002_PAPER_DOWNSIDE_VOLATILITY_MOMENTUM_DOWNSIDE_VOL13_RET26_V4` | `downside_vol_13w_pct` | missing_feature_task | high |
| `HYP_LIT_AUTO_002_PAPER_DRAWDOWN_AWARE_MOMENTUM_DOWNSIDE_VOL13_RET26_V4` | `downside_vol_13w_pct` | missing_feature_task | high |
| `HYP_LIT_AUTO_002_PAPER_LOW_VOLATILITY_ANOMALY_AND_MOMEN_DOWNSIDE_VOL13_RET26_V4` | `downside_vol_13w_pct` | missing_feature_task | high |
| `HYP_LIT_AUTO_002_PAPER_MARKET_STATE_AND_MOMENTUM_CRASH__DOWNSIDE_VOL13_RET26_V4` | `downside_vol_13w_pct` | missing_feature_task | high |
| `HYP_LIT_AUTO_002_PAPER_TACTICAL_ASSET_ALLOCATION_REGIME_DOWNSIDE_VOL13_RET26_V4` | `downside_vol_13w_pct` | missing_feature_task | high |
| `HYP_LIT_AUTO_002_DRAWDOWN_AWARE_RET52_MAXDD26_V4` | `max_drawdown_26w_pct` | missing_feature_task | high |
| `HYP_LIT_AUTO_002_BREADTH_REGIME_RET52_V4` | `market_breadth_above_sma50_pct` | missing_feature_task | high |
| `HYP_LIT_AUTO_002_PAPER_MARKET_BREADTH_AS_MOMENTUM_REGIM_BREADTH_REGIME_V4` | `market_breadth_above_sma50_pct` | missing_feature_task | high |
| `HYP_LIT_AUTO_002_PAPER_RESIDUAL_IDIOSYNCRATIC_MOMENTUM_RESIDUAL_RET26_V4` | `residual_ret_26w_pct` | missing_feature_task | high |
| `HYP_LIT_AUTO_002_RESIDUAL_MOMENTUM_RET26_V4` | `residual_ret_26w_pct` | missing_feature_task | high |
| `HYP_LIT_AUTO_002_VOL_MANAGED_RET26_REALIZED_VOL13_V4` | `realized_vol_13w_pct` | missing_feature_task | medium |
| `HYP_LIT_AUTO_002_PAPER_SECTOR_AND_INDUSTRY_RELATIVE_STR_SECTOR_REL_RET26_V4` | `ret_vs_sector_26w_pct` | missing_feature_task | low |
| `HYP_LIT_AUTO_002_SECTOR_REL_STRENGTH_RET26_V4` | `ret_vs_sector_26w_pct` | missing_feature_task | low |

## Duplicate pressure

- Duplicate strategy-effect signatures: **18**
- Pre-run blocked attempts indexed: **7**

| signature | runs | ranking | entry | exit |
|---|---:|---|---|---|
| `51139eb3f3b6` | 48 | `{'field': 'ret_52w_pct', 'order': 'desc'}` | `{'by': 'ret_52w_pct', 'top_n': 10, 'type': 'top_n'}` | `{'rank_threshold': 30, 'type': 'drop_below_rank'}` |
| `aca740e81ec0` | 4 | `{'field': 'ret_26w_pct', 'order': 'desc'}` | `{'by': 'ret_26w_pct', 'top_n': 12, 'type': 'top_n'}` | `{'rank_threshold': 30, 'type': 'drop_below_rank'}` |
| `0907c547e363` | 3 | `{'field': 'ret_52w_pct', 'order': 'desc'}` | `{'by': 'ret_52w_pct', 'top_n': 15, 'type': 'top_n'}` | `{'rank_threshold': 20, 'type': 'drop_below_rank'}` |
| `0be33a27e991` | 3 | `{'field': 'ret_52w_pct', 'order': 'desc'}` | `{'by': 'ret_52w_pct', 'top_n': 15, 'type': 'top_n'}` | `{'rank_threshold': 30, 'type': 'drop_below_rank'}` |
| `143261c4a548` | 3 | `{'field': 'channel_r2', 'order': 'desc'}` | `{'by': 'ret_52w_pct', 'top_n': 15, 'type': 'top_n'}` | `{'rank_threshold': 20, 'type': 'drop_below_rank'}` |
| `231ccb51a9cb` | 3 | `{'field': 'close_vs_sma20w_pct', 'order': 'desc'}` | `{'by': 'ret_52w_pct', 'top_n': 15, 'type': 'top_n'}` | `{'rank_threshold': 20, 'type': 'drop_below_rank'}` |
| `7396b2d11fb5` | 3 | `{'field': 'ret_26w_pct', 'order': 'desc'}` | `{'by': 'ret_52w_pct', 'top_n': 15, 'type': 'top_n'}` | `{'rank_threshold': 20, 'type': 'drop_below_rank'}` |
| `e579e6d7c72a` | 3 | `{'field': 'channel_r2', 'order': 'desc'}` | `{'by': 'ret_52w_pct', 'top_n': 15, 'type': 'top_n'}` | `{'rank_threshold': 20, 'type': 'drop_below_rank'}` |

## Priority actions

### High

- Add or intentionally proxy `ret_13w_pct`: unlocks 4 paper idea(s), cost=low, calculable_now=True.
- Add or intentionally proxy `downside_vol_13w_pct`: unlocks 6 paper idea(s), cost=medium, calculable_now=True.
- Add or intentionally proxy `max_drawdown_26w_pct`: unlocks 1 paper idea(s), cost=low, calculable_now=True.
- Add or intentionally proxy `market_breadth_above_sma50_pct`: unlocks 1 paper idea(s), cost=medium, calculable_now=True.

### Medium

- Do not write duplicate-signature templates; unsupported ideas must become missing-feature tasks, not fake hypotheses.

### Low

- Broaden paper search only after feature/template blockers are addressed; adding papers alone already failed to produce executable hypotheses.

## Suggested commands

### Refresh missing-feature priority report

```powershell
python .\scripts\research\missing_feature_task_prioritizer.py `
  --state-dir .\state `
  --reports-dir .\reports `
  --paper-ideas .\bibliography\paper_ideas.jsonl
```

### Dry-run supported literature templates using current features

```powershell
python .\scripts\research\literature_template_expander.py `
  --state-dir .\state `
  --reports-dir .\reports `
  --hypothesis-bank .\bibliography\hypothesis_bank.jsonl `
  --paper-ideas .\bibliography\paper_ideas.jsonl `
  --no-record-missing-tasks
```

### After adding features/templates, rerun literature miner before backtests

```powershell
python .\scripts\research\literature_hypothesis_miner.py `
  --parent-strategy-config .\configs/generated/HYP_AUTO_TIME_SERIES_MOMENTUM_SEED.json `
  --hypothesis-bank .\bibliography\hypothesis_bank.jsonl `
  --state-dir .\state `
  --paper-ideas .\bibliography\paper_ideas.jsonl
```

### Then rerun autonomous research wrapper

```powershell
python .\scripts\run_research_batch_autonomous.py `
  --max-runs 5 `
  --max-recovery-cycles 2 `
  --project-config .\configs\project_config.json `
  --state-dir .\state `
  --runs-dir .\runs `
  --reports-dir .\reports
```

## Guardrail

Do **not** rerun old `HYP_FSPACE` variants, do **not** override duplicate signatures, and do **not** move `AUTO_002`/`current_parent` as part of expansion planning.
