# Strategy From Bibliography

## Goal

Convert papers/books into testable trading rules.

## Input

- Paper/book summary or citation.
- Target universe and available feature columns.

## Process

1. Extract one hypothesis only.
2. Identify signal, rebalance frequency, holding logic, risk filter, benchmark.
3. Reject vague ideas that cannot map to data columns.
4. Do not invent unavailable data.

## Output: strategy_card JSON

```json
{
  "strategy_id": "",
  "bibliography_basis": [],
  "hypothesis": "",
  "universe": "",
  "benchmark": "SPY",
  "signal_columns": [],
  "entry_rule": "",
  "exit_rule": "",
  "risk_filters": [],
  "expected_edge": "",
  "known_risks": []
}
```

## Hard Rules

- One idea per card.
- No backtest claims without a run.
- If data is missing, mark `blocked_by_data`.
