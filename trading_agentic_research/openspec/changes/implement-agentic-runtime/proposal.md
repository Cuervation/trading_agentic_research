# Proposal: Implement Incremental Agentic Runtime

## Intent

Introduce an auditable runtime that turns documented agents into persisted parent-child tasks while preserving deterministic research behavior, without requiring an external LLM.

## Scope

### In Scope
- Typed runtime contracts and validated agent/skill registries.
- SQLite scheduling, leases, idempotency, memory, and task DAGs.
- Local-function and JSON-subprocess executors.
- Context/memory isolation, permissions, retries, timeouts, cancellation, and budgets.
- Compatibility adapters plus a delegated research workflow preserving audit, SPY, cost, governance, parent-lock, cooldown, and duplicate invariants.
- CLI submission, status, cancellation, and resume; tests and documentation.

### Out of Scope
- Distributed scheduling, parallel legacy-state mutation, or secure execution of untrusted code.
- Mandatory LLM/cloud integration or immediate removal of existing autonomous interfaces.

## Capabilities

### New Capabilities
- `runtime-contracts`: Typed requests, records, results, failures, artifacts, permissions, budgets, and states.
- `durable-task-scheduling`: Transactional SQLite tasks, dependencies, claims, leases, events, idempotency, and recovery.
- `runtime-executors`: Executor protocol with trusted local-function and cancellable JSON-subprocess implementations.
- `task-isolation-permissions`: Scoped context/memory and capability-mediated resource access.
- `runtime-lifecycle-controls`: Persisted retries, timeouts, cancellation, failure classification, and budgets.
- `agent-skill-registry`: Loading and validation of versioned agent and skill definitions.
- `research-runtime-workflow`: Compatibility adapters and delegated workflow over existing deterministic research tools.
- `runtime-operations`: CLI submission, status inspection, cancellation, resume, and compact evidence reporting.

### Modified Capabilities
None; existing autonomous interfaces remain compatible during migration.

## Approach

Build a serial Python runtime using SQLite WAL as source of truth. Persist delegations with explicit inputs, permissions, executors, and compact outputs; keep large evidence in immutable artifacts. Serialize legacy state mutation and migrate through chained, reversible slices.

## Affected Areas

| Area | Impact | Description |
|---|---|---|
| `contracts/agentic_runtime/` | New | Versioned schemas |
| `scripts/agentic_runtime/` | New | Store, scheduler, executors, isolation |
| `scripts/research/` | Modified | Adapters and workflow |
| `scripts/run_research_batch_autonomous.py` | Modified | Compatibility facade |
| `state/`, tests, docs | New/Modified | Runtime evidence and guidance |

## Risks

| Risk | Mitigation |
|---|---|
| Runtime/domain-state divergence | Idempotency, reconciliation, completion markers |
| Unsafe retry after partial effects | Classified failures and adapter-specific retry rules |
| Permission overclaim | Document trust boundary; reject invalid definitions |

## Rollback Plan

Disable the runtime facade, retain its additive database, and route unchanged CLI contracts back to legacy orchestration. Revert each chained slice independently.

## Success Criteria

- [ ] Restart evidence proves recovery, child linkage, isolation, controls, and deterministic resume.
- [ ] Compatibility tests prove unchanged audit, SPY, cost, governance, and CLI semantics.
- [ ] Registry validation, operations CLI, and documentation work without an external LLM.
