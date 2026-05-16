# Failure Recovery

## Goal

Classify failures and preserve useful research state.

## Failure Types

- `fatal_error`: code crash or impossible state.
- `recoverable_error`: missing output that can be regenerated.
- `data_issue`: missing columns, missing SPY, bad dates, bad prices.
- `no_material_candidate`: ran successfully but changed nothing useful.

## Process

1. Record failure type.
2. Keep logs/summaries small.
3. Do not overwrite useful run artifacts.
4. Decide retry, reject, or cooldown.

## Hard Rules

- Do not invent missing data.
- Do not rerun blindly.
- Data issues block conclusions.
