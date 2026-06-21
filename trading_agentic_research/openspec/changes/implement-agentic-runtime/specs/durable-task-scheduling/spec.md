# Durable Task Scheduling Specification

## Purpose

Provide recoverable, dependency-aware task coordination.

## Requirements

### Requirement: Transactional scheduling and delegation

The system MUST atomically persist tasks, dependencies, parent-child links, events, claims, and leases. A child MUST NOT run before its dependencies succeed.

#### Scenario: Run a ready child

- GIVEN a persisted child whose dependencies succeeded
- WHEN a worker claims it
- THEN one active lease authorizes execution

#### Scenario: Keep a blocked child pending

- GIVEN a child with an incomplete dependency
- WHEN scheduling occurs
- THEN the child remains unclaimed

### Requirement: Idempotent recovery

Submission and completion operations MUST be idempotent by scoped key, and expired claims MUST be recoverable without duplicating committed effects.

#### Scenario: Repeat submission

- GIVEN a task already exists for an idempotency key
- WHEN the same logical submission is repeated
- THEN the original task identity is returned

#### Scenario: Recover an expired lease

- GIVEN a worker stopped after its lease expired
- WHEN recovery runs
- THEN the task becomes safely claimable or is blocked for reconciliation
