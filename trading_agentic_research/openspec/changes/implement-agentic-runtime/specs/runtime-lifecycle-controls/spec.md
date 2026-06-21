# Runtime Lifecycle Controls Specification

## Purpose

Bound execution and make failure handling safe and recoverable.

## Requirements

### Requirement: Classified retry safety

The system MUST classify failures before retry and MUST retry only when policy, remaining budget, and effect safety allow it.

#### Scenario: Retry a transient failure

- GIVEN a retryable failure with no committed effect and remaining attempts
- WHEN policy evaluates it
- THEN a delayed retry is persisted

#### Scenario: Block an unsafe retry

- GIVEN failure follows an uncertain partial effect or data-integrity problem
- WHEN policy evaluates it
- THEN automatic retry is blocked pending reconciliation

### Requirement: Enforced execution limits

Deadlines, cancellation, attempt limits, and task or workflow budgets MUST be persisted and enforced across restarts.

#### Scenario: Exhaust a budget

- GIVEN execution reaches its configured budget
- WHEN more work is requested
- THEN new work is denied and the limiting reason is recorded

#### Scenario: Cancel a task tree

- GIVEN cancellation targets a parent
- WHEN it is applied
- THEN pending descendants are cancelled and running descendants receive cancellation
