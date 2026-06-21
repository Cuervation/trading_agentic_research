# SPY fallback audit

- Approx warning count scanned: 0
- Unique warning messages: 0
- Date span found: none
- Affects signals: yes, market_filter can fall back true when SPY metrics are unavailable/NaN.
- Likely scope: mostly dates where required SPY filter fields are missing/NaN; confirm via feature store if needed.
- Risk: medium. If fallback=True happens broadly, market filter is permissive and can overstate realism. If only early warmup, acceptable with documentation.
- Correction: precompute/validate SPY market filter fields and either skip warmup dates or require explicit fallback policy in config.
