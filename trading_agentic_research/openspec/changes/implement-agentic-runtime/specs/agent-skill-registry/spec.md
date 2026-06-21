# Agent and Skill Registry Specification

## Purpose

Load trustworthy, versioned agent and skill definitions.

## Requirements

### Requirement: Complete registry validation

The registry MUST reject malformed versions, duplicate identities, unresolved references, unsupported executors, and invalid permission or budget declarations before activation.

#### Scenario: Activate a valid registry

- GIVEN all definitions and references are valid
- WHEN the registry loads
- THEN a versioned validated snapshot becomes available

#### Scenario: Reject an invalid registry

- GIVEN a definition references a missing skill or excessive permission
- WHEN validation runs
- THEN activation fails with actionable diagnostics

### Requirement: Stable execution snapshot

A task MUST retain the registry versions resolved at submission so later registry changes cannot silently alter its meaning.

#### Scenario: Registry changes after submission

- GIVEN a task references an activated snapshot
- WHEN newer definitions are loaded
- THEN the task continues with its original resolved versions

#### Scenario: Resume with unavailable definitions

- GIVEN a resumable task's required version is unavailable
- WHEN resume is requested
- THEN resume is denied without substituting another version
