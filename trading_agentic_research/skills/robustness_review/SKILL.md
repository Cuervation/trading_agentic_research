# Robustness Review

## Goal

Check whether a result is stable enough to continue.

## Review Checklist

- Annual consistency.
- Monthly consistency.
- Max drawdown.
- Number of trades.
- Dependency on one rare year.
- Excess return versus SPY.

## Red Flags

- Wins only in one isolated year.
- Too few trades.
- Worse drawdown with weak excess return.
- Large parameter sensitivity.

## Output

```json
{
  "robustness_status": "pass|weak|fail",
  "reasons": [],
  "followup_questions": []
}
```

## Hard Rules

- Do not rescue ugly results with storytelling.
- Evidence first, narrative second.
