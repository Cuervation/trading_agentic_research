# Runtime Contracts Specification

## Purpose

Define stable runtime data and state semantics.

## Requirements

### Requirement: Validated runtime records

The system MUST validate typed requests, task records, results, failures, artifacts, permissions, budgets, and states before persistence or execution.

#### Scenario: Accept a valid request

- GIVEN a request with valid identifiers, inputs, permissions, and budget
- WHEN the runtime validates it
- THEN it is accepted without semantic loss

#### Scenario: Reject an invalid record

- GIVEN a record with an unknown state or invalid budget
- WHEN validation occurs
- THEN the record is rejected with field-level evidence

### Requirement: Stable task relationships and outcomes

Every delegated task MUST identify its parent and root, and every terminal outcome MUST be represented as success, classified failure, or cancellation with artifact references.

#### Scenario: Record child delegation

- GIVEN a running parent delegates valid work
- WHEN the child request is accepted
- THEN parent, root, and child identities are preserved

#### Scenario: Preserve compatible contracts

- GIVEN a supported older contract version
- WHEN it is read by the runtime
- THEN its documented meaning remains unchanged
