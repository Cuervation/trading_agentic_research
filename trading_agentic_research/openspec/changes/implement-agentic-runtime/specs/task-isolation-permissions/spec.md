# Task Isolation and Permissions Specification

## Purpose

Prevent context leakage and unauthorized resource access.

## Requirements

### Requirement: Scoped task context and memory

Each task MUST receive only its explicit inputs, authorized memory scope, and permitted parent context; sibling-private data MUST remain isolated.

#### Scenario: Read authorized parent context

- GIVEN a child is delegated an approved context subset
- WHEN the child starts
- THEN only that subset is available

#### Scenario: Prevent sibling leakage

- GIVEN sibling tasks have private memory
- WHEN one sibling requests the other's memory
- THEN access is denied and audited

### Requirement: Capability-mediated access

Every protected resource action MUST require an effective permission, and delegation MUST NOT increase permissions beyond the parent's grant.

#### Scenario: Permit authorized access

- GIVEN a task has the required capability
- WHEN it accesses the scoped resource
- THEN the action proceeds and is attributable

#### Scenario: Deny privilege escalation

- GIVEN a child requests a capability absent from its parent
- WHEN delegation is validated
- THEN creation is denied with no resource effect
