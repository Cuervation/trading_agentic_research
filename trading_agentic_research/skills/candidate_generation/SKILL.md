# Candidate Generation

## Goal

Generate the next candidate by changing few variables.

## Input

- Current parent strategy.
- Rejected candidates.
- Parameter effect memory.
- Cooldowns.

## Process

1. Change one main variable, two max.
2. Check rejected candidates first.
3. Check cooldowns before reusing a failed idea.
4. Prefer causal changes over random parameter search.

## Output

```json
{
  "candidate_id": "",
  "parent_id": "",
  "changes": [],
  "reason": "",
  "expected_effect": "",
  "cooldown_checked": true,
  "rejected_duplicate": false
}
```

## Hard Rules

- Do not repeat rejected candidates.
- Do not tune many knobs at once.
- No candidate without expected causal effect.
