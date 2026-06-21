# Slippage audit

- Slippage changes execution cost only via effective cost per side; it does not directly alter signals.
- Because the strategy is path-dependent, higher costs can alter equity DD, guard/reentry timing, stop timing, cash, and later holdings. So CAGR can improve in isolated cases even with worse per-trade economics. THIS IS NOT a free lunch.
- Sign check: configured bps are converted to percent per side and added to cost, not subtracted.
- Better-with-slip10 examples compared to base:
- {"strategy_id": "HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_LONGRUN_STRICT_STRICT_NEXT_CLOSE_R12_C22_E75_CR33_REDD_DD7_SL20", "base_trades": 6128, "slip10_trades": 6225, "base_final_equity": 234761.0803779413, "slip10_final_equity": 325704.531264622, "base_cagr": 12.217895103459252, "slip10_cagr": 13.567976896287748, "base_max_dd": -32.40108036258207, "slip10_max_dd": -31.212187197922205, "base_stops": 79, "slip10_stops": 77, "base_guard": 121, "slip10_guard": 103, "base_reentry": 23, "slip10_reentry": 25}
- {"strategy_id": "HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_LONGRUN_STRICT_STRICT_NEXT_CLOSE_R12_C22_E80_CR40_REDD_DD8_SL20", "base_trades": 5573, "slip10_trades": 5538, "base_final_equity": 299565.41515311773, "slip10_final_equity": 384937.1280517088, "base_cagr": 13.221488023892135, "slip10_cagr": 14.263194731186957, "base_max_dd": -32.6977535160423, "slip10_max_dd": -33.06268036011543, "base_stops": 77, "slip10_stops": 75, "base_guard": 117, "slip10_guard": 95, "base_reentry": 25, "slip10_reentry": 29}
- {"strategy_id": "HYP_REFINE_AUTO002_TOPN_6_V1_DDGRID_LONGRUN_STRICT_STRICT_NEXT_CLOSE_R12_C22_E78_CR40_REDD_DD8_SL20", "base_trades": 5794, "slip10_trades": 5532, "base_final_equity": 292047.8727978193, "slip10_final_equity": 367316.4132464914, "base_cagr": 13.116434927082851, "slip10_cagr": 14.067808600166366, "base_max_dd": -32.77670862795975, "slip10_max_dd": -33.13262038336228, "base_stops": 78, "slip10_stops": 75, "base_guard": 131, "slip10_guard": 88, "base_reentry": 25, "slip10_reentry": 28}

Conclusion: slippage application is directionally correct, but ranking by slip10 must be interpreted as path-dependent robustness, not proof that slippage helps.
