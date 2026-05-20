# Research Expansion Plan

Current result: **research is exhausted under the current hypothesis space; do not launch backtests until a new feature/template/family creates executable work.**

- Generated at: `2026-05-20T16:17:55.708394+00:00`
- Parent stays locked: `AUTO_002` / `HYP_AUTO_TIME_SERIES_MOMENTUM_SEED`
- Recommended mode: `literature_or_new_family`
- Eligible: `False`
- Executable count: `0`
- Feature-space stall: `True` (feature_space_recent_bad:10_good:0_window:10)

## Why no hypotheses are executable

- No eligible hypotheses found (all rejected/cooldown/invalid/consumed/scoped/duplicate-signature).
- Selector-equivalent executable_count=0.
- Top blockers: rejected=135, feature_space_stalled_literature_mode=113, duplicate_override_signature=69, consumed=19, candidate_review_scope:no_active_candidate_under_review=12, accepted_already=8.
- Feature-space stall is active: feature_space_recent_bad:10_good:0_window:10.
- Literature mining produced no supported executable hypotheses.
- Feature-space expansion produced no new rows; current combinations are exhausted or duplicate.

### Blocker counts

| blocker | count |
|---|---:|
| `rejected` | 135 |
| `feature_space_stalled_literature_mode` | 113 |
| `duplicate_override_signature` | 69 |
| `consumed` | 19 |
| `candidate_review_scope:no_active_candidate_under_review` | 12 |
| `accepted_already` | 8 |
| `semantic_branch_exhausted` | 5 |

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
| `paper_low_vol_momentum` | `paper_low_vol_momentum/unknown_field/unknown_layer` | duplicate_threshold_reached:4 | 4 |
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
| `multi_lookback_momentum_confirmation` | Multi-lookback momentum confirmation | family_cooldown_or_exhausted, converted_but_currently_not_executable, missing_feature_task_exists | - | 3 |
| `trend_following_fast_slow_confirmation` | Trend following fast and slow confirmation | family_cooldown_or_exhausted, converted_but_currently_not_executable, missing_feature_task_exists | - | 4 |
| `drawdown_aware_momentum` | Drawdown-aware momentum | family_cooldown_or_exhausted, converted_but_currently_not_executable, missing_feature_task_exists | - | 1 |
| `idiosyncratic_momentum_residual_returns` | Residual / idiosyncratic momentum | family_cooldown_or_exhausted, converted_but_currently_not_executable, missing_feature_task_exists | - | 1 |
| `market_breadth_momentum_regime` | Market breadth as momentum regime filter | family_cooldown_or_exhausted, converted_but_currently_not_executable, missing_feature_task_exists | - | 1 |
| `sector_industry_relative_momentum` | Sector and industry relative strength | family_cooldown_or_exhausted, converted_but_currently_not_executable, missing_feature_task_exists | - | 2 |
| `time_series_momentum_moskowitz_ooi_pedersen` | Time Series Momentum | family_cooldown_or_exhausted, converted_but_currently_not_executable, missing_feature_task_exists | - | 2 |
| `volatility_managed_portfolios` | Volatility managed portfolios | family_cooldown_or_exhausted, converted_but_currently_not_executable, missing_feature_task_exists | - | 1 |
| `cross_sectional_momentum_jegadeesh_titman` | Cross-sectional momentum | family_cooldown_or_exhausted, missing_feature_task_exists, supported_template_not_materialized | - | 0 |
| `downside_volatility_momentum` | Downside-volatility momentum | family_cooldown_or_exhausted, missing_feature_task_exists, supported_template_not_materialized | - | 0 |
| `faber_tactical_asset_allocation_regime_filter` | Tactical asset allocation / regime filter | family_cooldown_or_exhausted, converted_but_currently_not_executable, missing_feature_task_exists | - | 2 |
| `low_volatility_momentum_drawdown_control` | Low volatility anomaly and momentum crash control | family_cooldown_or_exhausted, converted_but_currently_not_executable, missing_feature_task_exists | - | 4 |
| `market_state_and_momentum_crashes` | Market state and momentum crash control | family_cooldown_or_exhausted, missing_feature_task_exists, supported_template_not_materialized | - | 0 |
| `absolute_momentum_dual_momentum` | Absolute momentum and dual momentum | family_cooldown_or_exhausted, supported_template_not_materialized | - | 0 |
| `quality_momentum_trend_stability` | Quality momentum and trend stability | family_cooldown_or_exhausted, converted_but_currently_not_executable | - | 6 |

## Missing feature priorities

| priority | feature | papers unlocked | cost | calculable now | nearby/current columns |
|---|---|---:|---|:---:|---|
| - | - | 0 | - | - | - |

## Supported literature templates using existing features

These are proposals only. They are not written to the hypothesis bank by this planner.

| hypothesis | family | required features |
|---|---|---|
| - | - | - |

## Hypotheses that should become possible after expansion

| hypothesis | unlocked by | source | priority |
|---|---|---|---|
| - | - | - | - |

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

- Create a genuinely new family/template before backtesting again; current space is exhausted.

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
