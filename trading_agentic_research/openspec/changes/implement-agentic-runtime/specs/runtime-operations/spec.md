# Runtime Operations Specification

## Purpose

Operate persisted workflows through auditable commands.

## Requirements

### Requirement: Submit and inspect workflows

The CLI MUST support idempotent submission and status inspection showing task state, parent-child progress, limits, failures, and compact artifact evidence.

#### Scenario: Submit twice

- GIVEN an accepted submission with an idempotency key
- WHEN the same submission is repeated
- THEN the existing workflow identity and status are returned

#### Scenario: Inspect delegated progress

- GIVEN a workflow has running, blocked, and completed descendants
- WHEN status is requested
- THEN their relationships and current reasons are reported

### Requirement: Cancel and resume safely

The CLI MUST persist cancellation requests and MAY resume only eligible interrupted work without repeating committed effects or resetting consumed budgets.

#### Scenario: Resume interrupted work

- GIVEN a recoverable interrupted workflow has valid registry versions
- WHEN resume is requested
- THEN execution continues from persisted safe state

#### Scenario: Deny unsafe resume

- GIVEN work is terminal, permission-denied, budget-exhausted, or unreconciled
- WHEN resume is requested
- THEN it is rejected with the blocking reason
