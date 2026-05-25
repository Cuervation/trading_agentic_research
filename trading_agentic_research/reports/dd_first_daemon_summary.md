# DD_FIRST Autonomous Daemon Summary

- Status: completed
- Batch: 1
- Total attempts: 5
- Completed runs: 26
- Champions found: 2
- Last error: 
- Last lesson: dynamic_regime_exposure: champion candidate under DD_FIRST constraints.
- Next batch plan: HYP_DD_FIRST_AUTO002_DYN_EXPOSURE_75_60_50_25_V1, HYP_DD_FIRST_AUTO002_DYN_EXPOSURE_70_60_50_25_V1, HYP_DD_FIRST_AUTO002_DYN_EXPOSURE_75_60_55_35_V1, HYP_DD_FIRST_AUTO002_DYN_EXPOSURE_70_55_45_25_V1, HYP_DD_FIRST_AUTO002_DYN_EXPOSURE_65_55_45_25_V1

## Champions
- dd_min_champion: HYP_DD_FIRST_AUTO002_DYN_EXPOSURE_65_55_45_25_V1 / DDDAEMON_001_HYP_DD_FIRST_AUTO002_DYN_EXPOSURE_65_55_45_25_V1 DD=-28.804358 CAGR=11.87758
- balanced_dd_champion: HYP_DD_FIRST_AUTO002_DYN_EXPOSURE_65_55_45_25_V1 / DDDAEMON_001_HYP_DD_FIRST_AUTO002_DYN_EXPOSURE_65_55_45_25_V1 DD=-28.804358 CAGR=11.87758
- return_with_dd_guard_champion: HYP_DD_FIRST_AUTO002_EXPOSURE_65_V1 / DD_FIRST_17_HYP_DD_FIRST_AUTO002_EXPOSURE_65_V1 DD=-39.288674 CAGR=17.073327

## Axis status
- exposure_reduction_partial: active attempts=7 champions=0
- soft_spy_regime: exhausted attempts=2 champions=0
- low_vol_momentum_soft_penalty: exhausted attempts=2 champions=0
- anti_extension_soft_filter: exhausted attempts=2 champions=0
- drawdown_proxy_filter: cooldown attempts=3 champions=0
- trailing_and_exit_refinement: exhausted attempts=2 champions=0
- diversification_cap: exhausted attempts=0 champions=0
- dynamic_regime_exposure: active attempts=5 champions=5
- exposure_plus_crisis_guard: active attempts=0 champions=0
- exposure_plus_breakeven: active attempts=0 champions=0
- exposure_plus_soft_spy_topn: active attempts=0 champions=0
- exposure_plus_low_vol_penalty: active attempts=0 champions=0
- exposure_plus_anti_extension: active attempts=0 champions=0
- controlled_combos: active attempts=0 champions=0

## Validation notes

- Focused DD_FIRST daemon validation passed: py_compile and 10 targeted tests.
- Full pytest still fails during collection on legacy imports outside DD_FIRST: classify_candidate, all_literature_ideas, hard_cooldown_families.
- Parent/baseline locks were not moved; no --allow-parent-update was used.
