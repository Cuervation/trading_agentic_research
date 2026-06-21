# Research Runtime Workflow Specification

## Purpose

Delegate deterministic research while preserving existing governance and evidence.

## Requirements

### Requirement: Preserve research invariants

Research completion MUST retain audit evidence, costs, daily/monthly/annual SPY comparisons, parent-lock, cooldown, and duplicate controls. Data problems MUST block conclusions.

#### Scenario: Complete valid research

- GIVEN delegated research has valid evidence and comparisons
- WHEN the workflow completes
- THEN all mandatory invariants are reported

#### Scenario: Block incomplete evidence

- GIVEN SPY comparison, costs, audit evidence, or required data is missing
- WHEN a conclusion is requested
- THEN completion and promotion are blocked with reasons

### Requirement: Governed compatibility workflow

The compatibility facade MUST preserve documented legacy inputs and outputs while serializing legacy-state mutation. It MUST NOT auto-promote a baseline without audit, costs, and SPY evidence.

#### Scenario: Use the compatibility facade

- GIVEN a supported legacy request
- WHEN it is submitted through the facade
- THEN equivalent deterministic workflow semantics are produced

#### Scenario: Reject duplicate promotion

- GIVEN cooldown, parent-lock, duplicate, or governance rules prohibit promotion
- WHEN promotion is evaluated
- THEN no promotion occurs and the rule is evidenced
