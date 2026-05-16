# Promotion Governance

## Goal

Control movement between rejected, follow-up, parent, and baseline.

## Decisions

- `rejected`: do not continue.
- `accepted_for_followup`: useful learning; may guide next candidate.
- `promoted_candidate`: candidate for manual review.
- `promoted_to_baseline`: manual future step only.

## Required Before Any Promotion

- `audit.json`
- SPY daily/monthly/yearly comparison.
- Costs applied.
- No critical warnings.

## Hard Rules

- Never move baseline without audit.
- Never auto-promote to baseline.
- `can_promote_baseline` must stay false until manual governance exists.
