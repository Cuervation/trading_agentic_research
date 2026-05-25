# DD_FIRST Long Loop Summary

- Status: completed
- Stop reason: requested_strategy_ids_completed
- Completed runs: 21
- Useful candidates: 7
- Total attempts: 19
- Failed attempts: 0
- Repaired errors: 0
- Generated hypotheses: 21
- Current axis: exposure_reduction_partial
- Exhausted axes: soft_spy_regime, low_vol_momentum_soft_penalty, anti_extension_soft_filter, trailing_and_exit_refinement, diversification_cap
- Cooldown axes: drawdown_proxy_filter
- Best DD_FIRST candidate: DD_FIRST_02_HYP_DD_FIRST_AUTO002_EXPOSURE_50_V1
- Last error: 
- Last lesson: Exposure reduction partial is the first useful DD_FIRST axis. Monotonic exposure refinement should identify the best fixed exposure between 50 and 75 before testing dynamic regime exposure.
- Next action: continue_axis:exposure_reduction_partial

| run_id | strategy_id | axis | CAGR | SPY CAGR | excess | max DD | parent DD | DD improvement | Calmar | years W/L | trades | decision | value_delivered |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|
| DD_FIRST_01_HYP_DD_FIRST_AUTO002_EXPOSURE_75_V1 | HYP_DD_FIRST_AUTO002_EXPOSURE_75_V1 | exposure_reduction_partial | 19.640769 | 6.802475 | 12.838294 | -44.052781 | -54.644063 | 19.382311 | 0.445846 | 22/6 | 3796 | accepted_for_followup | dd_first_followup_signal |
| DD_FIRST_01_HYP_DD_FIRST_AUTO002_SPY_REGIME_EXPOSURE_V1 | HYP_DD_FIRST_AUTO002_SPY_REGIME_EXPOSURE_V1 | spy_regime_strict | 0.0 | 6.802475 | -6.802475 | 0.0 | -54.644063 | 100.0 | 0.0 | 8/20 | 0 | rejected | defensive_learning |
| DD_FIRST_02_HYP_DD_FIRST_AUTO002_EXPOSURE_50_V1 | HYP_DD_FIRST_AUTO002_EXPOSURE_50_V1 | exposure_reduction_partial | 13.183145 | 6.802475 | 6.38067 | -31.549424 | -54.644063 | 42.263766 | 0.417857 | 20/8 | 3847 | accepted_for_followup | dd_first_followup_signal |
| DD_FIRST_02_HYP_DD_FIRST_AUTO002_QUALITY_LOWVOL_RANK_V1 | HYP_DD_FIRST_AUTO002_QUALITY_LOWVOL_RANK_V1 | quality_momentum | 14.038741 | 6.802475 | 7.236266 | -76.787243 | -54.644063 | -40.522572 | 0.182826 | 21/7 | 3203 | rejected | return_signal_without_dd_improvement |
| DD_FIRST_03_HYP_DD_FIRST_AUTO002_EXPOSURE_85_V1 | HYP_DD_FIRST_AUTO002_EXPOSURE_85_V1 | exposure_reduction_partial | 22.183311 | 6.802475 | 15.380836 | -48.517761 | -54.644063 | 11.211286 | 0.45722 | 23/5 | 3767 | accepted_for_followup | dd_first_followup_signal |
| DD_FIRST_03_HYP_DD_FIRST_AUTO002_TRAILING_18_TOPN_9_V1 | HYP_DD_FIRST_AUTO002_TRAILING_18_TOPN_9_V1 | trailing_stop | 23.681881 | 6.802475 | 16.879406 | -57.882834 | -54.644063 | -5.927033 | 0.409135 | 20/8 | 2408 | rejected | return_signal_without_dd_improvement |
| DD_FIRST_04_HYP_DD_FIRST_AUTO002_SOFT_SPY_TOPN_8_V1 | HYP_DD_FIRST_AUTO002_SOFT_SPY_TOPN_8_V1 | soft_spy_regime | 25.929269 | 6.802475 | 19.126795 | -54.644063 | -54.644063 | 0.0 | 0.474512 | 22/6 | 3706 | rejected | return_signal_without_dd_improvement |
| DD_FIRST_05_HYP_DD_FIRST_AUTO002_SOFT_SPY_TOPN_5_V1 | HYP_DD_FIRST_AUTO002_SOFT_SPY_TOPN_5_V1 | soft_spy_regime | 25.929269 | 6.802475 | 19.126795 | -54.644063 | -54.644063 | 0.0 | 0.474512 | 22/6 | 3706 | rejected | return_signal_without_dd_improvement |
| DD_FIRST_06_HYP_DD_FIRST_AUTO002_ANTI_EXTENSION_SMA52_80_V1 | HYP_DD_FIRST_AUTO002_ANTI_EXTENSION_SMA52_80_V1 | anti_extension_soft_filter | 22.846647 | 6.802475 | 16.044173 | -58.361365 | -54.644063 | -6.802757 | 0.391469 | 22/6 | 3772 | rejected | return_signal_without_dd_improvement |
| DD_FIRST_07_HYP_DD_FIRST_AUTO002_DD_PROXY_26W_V1 | HYP_DD_FIRST_AUTO002_DD_PROXY_26W_V1 | drawdown_proxy_filter | 25.929269 | 6.802475 | 19.126795 | -54.644063 | -54.644063 | 0.0 | 0.474512 | 22/6 | 3706 | rejected | return_signal_without_dd_improvement |
| DD_FIRST_08_HYP_DD_FIRST_AUTO002_TRAILING_24_V1 | HYP_DD_FIRST_AUTO002_TRAILING_24_V1 | trailing_and_exit_refinement | 20.520474 | 6.802475 | 13.717999 | -59.129016 | -54.644063 | -8.207576 | 0.347046 | 21/7 | 3845 | rejected | return_signal_without_dd_improvement |
| DD_FIRST_09_HYP_DD_FIRST_AUTO002_TOPN_12_V1 | HYP_DD_FIRST_AUTO002_TOPN_12_V1 | trailing_and_exit_refinement | 29.768113 | 6.802475 | 22.965638 | -54.10438 | -54.644063 | 0.987633 | 0.550198 | 22/6 | 2938 | rejected | defensive_learning |
| DD_FIRST_11_HYP_DD_FIRST_AUTO002_LOWVOL_PENALTY_V1 | HYP_DD_FIRST_AUTO002_LOWVOL_PENALTY_V1 | low_vol_momentum_soft_penalty | 25.241914 | 6.802475 | 18.439439 | -54.568365 | -54.644063 | 0.138529 | 0.462574 | 22/6 | 3704 | rejected | defensive_learning |
| DD_FIRST_12_HYP_DD_FIRST_AUTO002_LOWVOL_PENALTY_LIGHT_V1 | HYP_DD_FIRST_AUTO002_LOWVOL_PENALTY_LIGHT_V1 | low_vol_momentum_soft_penalty | 25.161063 | 6.802475 | 18.358588 | -54.567962 | -54.644063 | 0.139266 | 0.461096 | 22/6 | 3708 | rejected | defensive_learning |
| DD_FIRST_13_HYP_DD_FIRST_AUTO002_ANTI_EXTENSION_SMA20W_60_V1 | HYP_DD_FIRST_AUTO002_ANTI_EXTENSION_SMA20W_60_V1 | anti_extension_soft_filter | 25.161374 | 6.802475 | 18.358899 | -54.053049 | -54.644063 | 1.08157 | 0.465494 | 22/6 | 3700 | rejected | defensive_learning |
| DD_FIRST_14_HYP_DD_FIRST_AUTO002_DD_PROXY_26W_V2 | HYP_DD_FIRST_AUTO002_DD_PROXY_26W_V2 | drawdown_proxy_filter | 24.462241 | 6.802475 | 17.659766 | -54.753286 | -54.644063 | -0.199881 | 0.446772 | 20/8 | 3741 | rejected | return_signal_without_dd_improvement |
| DD_FIRST_15_HYP_DD_FIRST_AUTO002_DD_PROXY_13W_V1 | HYP_DD_FIRST_AUTO002_DD_PROXY_13W_V1 | drawdown_proxy_filter | 21.773932 | 6.802475 | 14.971457 | -54.874142 | -54.644063 | -0.421051 | 0.396798 | 20/8 | 3829 | rejected | return_signal_without_dd_improvement |
| DD_FIRST_16_HYP_DD_FIRST_AUTO002_EXPOSURE_60_V1 | HYP_DD_FIRST_AUTO002_EXPOSURE_60_V1 | exposure_reduction_partial | 15.78141 | 6.802475 | 8.978936 | -36.789786 | -54.644063 | 32.673772 | 0.428962 | 21/7 | 3837 | accepted_for_followup | dd_first_followup_signal |
| DD_FIRST_17_HYP_DD_FIRST_AUTO002_EXPOSURE_65_V1 | HYP_DD_FIRST_AUTO002_EXPOSURE_65_V1 | exposure_reduction_partial | 17.073327 | 6.802475 | 10.270852 | -39.288674 | -54.644063 | 28.100745 | 0.434561 | 21/7 | 3822 | accepted_for_followup | dd_first_followup_signal |
| DD_FIRST_18_HYP_DD_FIRST_AUTO002_EXPOSURE_70_V1 | HYP_DD_FIRST_AUTO002_EXPOSURE_70_V1 | exposure_reduction_partial | 18.359931 | 6.802475 | 11.557456 | -41.709045 | -54.644063 | 23.671405 | 0.440191 | 21/7 | 3816 | accepted_for_followup | dd_first_followup_signal |
| DD_FIRST_19_HYP_DD_FIRST_AUTO002_EXPOSURE_55_V1 | HYP_DD_FIRST_AUTO002_EXPOSURE_55_V1 | exposure_reduction_partial | 14.484545 | 6.802475 | 7.682071 | -34.210675 | -54.644063 | 37.39361 | 0.423393 | 20/8 | 3842 | accepted_for_followup | dd_first_followup_signal |

## Validation notes

- Focused DD_FIRST validation passed: py_compile and 6 targeted tests.
- Full pytest still fails during collection on legacy imports outside DD_FIRST: classify_candidate, all_literature_ideas, hard_cooldown_families.
- Parent/baseline locks were not moved; no --allow-parent-update was used.
