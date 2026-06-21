# Runtime Executors Specification

## Purpose

Execute trusted local functions and JSON subprocesses through one observable contract.

## Requirements

### Requirement: Uniform executor outcomes

Each executor MUST consume a validated request and return a validated result or classified failure without bypassing runtime controls.

#### Scenario: Execute a local function

- GIVEN a permitted local-function task
- WHEN its executor completes
- THEN the runtime records its result and artifacts

#### Scenario: Reject malformed output

- GIVEN an executor emits output that violates its contract
- WHEN the runtime validates the output
- THEN execution fails as a non-successful classified outcome

### Requirement: Controllable subprocess execution

JSON-subprocess execution MUST support deadlines and cancellation and MUST preserve diagnostic evidence without treating partial output as success.

#### Scenario: Cancel a subprocess

- GIVEN a running subprocess receives cancellation
- WHEN cancellation is enforced
- THEN it terminates and records cancellation evidence

#### Scenario: Exceed a deadline

- GIVEN a subprocess exceeds its deadline
- WHEN the deadline is enforced
- THEN it records a timeout failure and no success result
