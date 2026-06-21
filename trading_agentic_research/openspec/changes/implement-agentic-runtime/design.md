# Design: Implement Agentic Runtime

## Technical Approach

Add a standard-library, serial runtime beside the existing synchronous research scripts. SQLite is the runtime source of truth; existing `state/`, `runs/`, governance, cost, SPY, parent-lock, cooldown, and duplicate artifacts remain domain truth. A persisted coordinator delegates typed child tasks to adapters around current deterministic functions/CLIs. No external LLM is required.

## Architecture Decisions

| Option | Tradeoff | Decision |
|---|---|---|
| Serial scheduler vs distributed workers | Lower throughput, far safer for current unlocked JSON/JSONL writers | One scheduler/legacy-mutation lane in v1 |
| Frozen dataclasses/enums vs mandatory Pydantic | More manual validation, no new runtime dependency | `@dataclass(frozen=True, slots=True)`, `StrEnum`, strict `from_dict` validators |
| SQLite WAL vs more JSON state | Dual state during rollout, but atomic claims/recovery | `state/agentic_runtime.sqlite3`, WAL, foreign keys, busy timeout |
| Local/subprocess executors vs LLM-first | Trusted-code boundary, deterministic and testable | Protocol plus local-function and JSON subprocess executors |

## Trust Boundary and Flow

The store, scheduler, registry loader, context builder, and registered local adapters are trusted application code. Permissions constrain registered capabilities, paths, environment, network, subprocess use, and output size; they are **not an OS sandbox**. Subprocess executors receive filtered inputs/environment but remain trusted. Untrusted code requires later container/OS isolation.

```text
CLI -> Store -> Scheduler -> Coordinator root
                         -> select/generate child
                         -> execute child -> audit child -> governance child
                              | artifacts/hashes | compact results
```

The coordinator persists each child, waits, and receives only `TaskResult` plus artifact references. The minimal workflow wraps eligibility/selection, config materialization, `run_backtest.py`, `evaluate_candidate.py`, and existing governance. Legacy-mutating children execute exclusively.

## Package / File Map

| Path | Action | Responsibility |
|---|---|---|
| `scripts/agentic_runtime/{models,codec,store,scheduler}.py` | Create | Contracts, JSON validation, SQLite lifecycle |
| `scripts/agentic_runtime/{executors,context,registry,cli}.py` | Create | Execution, isolation, definitions, operations |
| `scripts/agentic_runtime/__main__.py` | Create | `submit/status/work/cancel/resume/events` |
| `contracts/agentic_runtime/v1/*.schema.json` | Create | Published JSON envelopes |
| `scripts/research/{runtime_adapters,agentic_workflow}.py` | Create | Deterministic adapters and coordinator |
| `agents/*.md`, `skills/*/SKILL.md`, `AGENTS.md` | Modify | Versioned metadata and skill registration |
| `scripts/run_research_batch_autonomous.py` | Modify | Opt-in compatibility facade; preserve arguments/exit semantics |
| `tests/agentic_runtime/` | Create | Runtime tests |

## Contracts, Persistence, and Scheduling

Enums define task/failure states. Frozen `AgentSpec`, `SkillSpec`, `TaskRequest`, `TaskRecord`, `TaskResult`, `Failure`, `ArtifactRef`, `PermissionSet`, `RetryPolicy`, and `Budget` reject unknown fields, invalid transitions, non-JSON values, and unsupported `schema_version`; serialization is canonical UTF-8 JSON.

Schema: `runs`; `tasks` (parent, agent, executor, state, input/output/failure JSON, deadline, attempts, lease, version, unique `(run_id,idempotency_key)`); `task_dependencies`; `attempts`; append-only `events`; immutable `artifacts` (path, SHA-256, size, media type); and versioned `memory` keyed by `(scope,scope_id,key)`. Every mutation uses explicit transactions. Claims use `BEGIN IMMEDIATE`, dependency checks, compare-and-set state/version, and expiring `lease_owner/lease_until`; expired work is reclaimed. Duplicate submission returns the existing task. Completion atomically records result, usage, artifacts, event, and terminal state.

The scheduler selects one ready task by creation order. Retry requires persisted classification, adapter-declared safety, remaining budget, idempotency, and backoff—never blind retry. Cancellation is persisted; local handlers poll a token, while `Popen` subprocesses are terminated then killed after grace. Deadlines and run/task budgets cover wall time, tasks, depth, retries, subprocesses, and output bytes. Ambiguous side effects become manual-review failures; adapters stage artifacts and write completion markers.

Context contains explicit compact evidence/artifact references only. Memory scopes are task, agent, and shared run; sharing is explicit. The registry scans `agents/*.md` and `skills/*/SKILL.md`, parses a strict metadata header (`id`, `version`, `description`, capabilities/skills), validates uniqueness/references, and rejects malformed definitions before submission.

## Testing and Rollout

Strict TDD with pytest: unit-test codecs, metadata, permissions, transitions, budgets, and failure policy; integration-test WAL claims, crash/lease recovery, idempotency, DAG waits, cancellation/timeouts, subprocess envelopes, and restart resume; characterize the delegated workflow against existing audit, SPY, costs, parent lock, cooldown, duplicates, and exit codes. Use fakes—no builds or backtests.

Roll out additively in chained slices: contracts/store; scheduler/executors; isolation/registry/CLI; adapters/workflow; opt-in facade. Keep legacy default and rollback path until parity passes. Fix and characterize the existing unreachable `update_memory()` write before adapter migration. No data migration is required.

## Open Questions

None blocking.
