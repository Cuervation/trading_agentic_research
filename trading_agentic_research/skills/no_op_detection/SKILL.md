# No-Op Detection

## Goal

Detect candidates that do not materially change behavior.

## Compare Against Parent

- Signals changed?
- Trades changed?
- Metrics changed?
- SPY comparison changed?

## No-Op Labels

- `signal_no_effect`
- `trade_no_effect`
- `metric_no_effect`
- `duplicate_candidate`

## Hard Rules

- `metric_no_effect` cannot move parent.
- Cosmetic config changes do not count.
- No-op candidates should be rejected or cooled down.
