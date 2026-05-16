# SPY Comparison

## Goal

Force every strategy to face SPY as benchmark.

## Required Evidence

- Daily comparison.
- Monthly comparison.
- Yearly comparison.
- CAGR strategy vs SPY.
- Drawdown strategy vs SPY.

## Decision Rule

Reject if strategy earns less than SPY and does not strongly reduce risk.

## Read First

1. `spy_comparison_summary.json`
2. `metrics.json`
3. `summary.md`

## Hard Rules

- Positive nominal return is not enough.
- SPY is the opportunity cost.
- No SPY comparison means reject.
