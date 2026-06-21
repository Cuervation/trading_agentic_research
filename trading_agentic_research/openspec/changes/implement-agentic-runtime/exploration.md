## Exploration: Executable hybrid agentic runtime

### Current State
The repository is deterministic and only pseudo-agentic:

- `agents/*.md` and `skills/*/SKILL.md` describe roles and rules, but no runtime loads them into executable agent definitions.
- `scripts/research/autonomy_orchestrator.py` is a synchronous policy loop over an in-process handler registry. Handlers are ordinary functions, not isolated agents or delegated child tasks.
- `scripts/run_research_batch_autonomous.py` and `scripts/run_research_batch.py` coordinate a long sequence of direct function calls and blocking subprocesses. They have coarse batch recovery, but no durable task DAG, task ownership, cancellation token, unified timeout, or budget accounting.
- The useful deterministic boundaries already exist: hypothesis selection/generation, candidate config creation, backtest execution, audit, learning, governance, and recovery are callable functions or CLIs.
- State is fragmented across many JSON/JSONL files. Most writers use direct `Path.write_text`; updates spanning files are not transactional, writers are not locked, and retry/idempotency rules vary by module. Histories such as `research_state.json`, `generation_feedback.json`, and nested blocker context grow without a runtime retention policy.
- Context packs encode valuable read restrictions, but they are generated documentation rather than enforced task context. Permissions are prose, shared state is globally visible, and subprocesses inherit the repository environment.
- Timeout handling exists only in specialized daemons. The main autonomous batch path uses blocking `subprocess.run` without timeout or cancellation.
- JSON schemas are mostly passive documentation; tests check schema shape but the orchestration path does not validate agent/task inputs and outputs against runtime contracts.
- A source defect exists in `scripts/research/autonomous.py`: `update_memory()` constructs an event but its append/write/return statements are misplaced after an unconditional return in `mixed_mechanism_for_claims`, so that compatibility path currently returns `None`.

The existing system should therefore be treated as a proven collection of deterministic research tools surrounded by duplicated orchestration, not as an agent runtime.

### Affected Areas
- `scripts/agentic_runtime/` — new dependency-free runtime core: models, scheduler, state store, executor protocol, permissions, budgets, cancellation, and context/memory scopes.
- `contracts/agentic_runtime/` — versioned task, result, event, agent, skill, failure, permission, and budget contracts.
- `scripts/research/agentic_workflow.py` — research-specific coordinator workflow that creates and joins delegated child tasks.
- `scripts/research/runtime_adapters.py` — adapters around existing selection, generation, backtest, audit, governance, learning, and recovery functions/CLIs.
- `scripts/run_research_batch_autonomous.py` — compatibility CLI/facade that submits a root runtime task while preserving existing arguments and exit semantics.
- `scripts/run_research_batch.py` and `scripts/research_loop.py` — retained initially as legacy exclusive adapters; later reduced as orchestration moves into the runtime.
- `scripts/research/autonomy_orchestrator.py`, `autonomy_handlers.py`, and `autonomy_recovery_policy.py` — policy and handler logic to reuse behind typed task adapters rather than parallel orchestration.
- `scripts/research/real_executor.py`, `scripts/run_backtest.py`, and `scripts/evaluate_candidate.py` — deterministic tool boundaries for execution and audit adapters.
- `agents/*.md` — source material for versioned `AgentSpec` definitions and role-level permissions.
- `skills/*/SKILL.md` — declarative skill registry loaded into task context; skills remain instructions/contracts, not arbitrary executable code.
- `scripts/context/build_agent_context_pack.py` — context compilation logic to move behind per-task context construction and enforcement.
- `state/` — runtime database plus compact exported status views; existing domain state remains compatible during migration.
- `tests/agentic_runtime/` — focused tests for state recovery, task delegation, idempotency, permissions, retries, cancellation, timeout, budgets, and executor contracts.
- Existing autonomous workflow tests — compatibility characterization tests proving unchanged audit, SPY, cost, parent-lock, cooldown, and duplicate behavior.

### Approaches
1. **Wrap the existing autonomous script as one durable task** — place retries, timeout, and status around the current CLI without decomposing it.
   - Pros: Smallest change; fastest way to gain resumable execution and top-level observability.
   - Cons: Agents remain fictional; no real child-task delegation, context isolation, fine-grained permissions, or safe per-step retries.
   - Effort: Low

2. **Incremental hybrid runtime with compatibility adapters** — add a generic task runtime, model each role action as a persisted parent/child task, and invoke existing deterministic tools through adapters.
   - Pros: Delivers real delegation without an LLM dependency; preserves proven research behavior; supports future local/remote executors; migration can be sliced and reversed.
   - Cons: Runtime state and legacy domain state coexist temporarily; broad legacy adapters must be serialized because current tools mutate shared files.
   - Effort: Medium/High

3. **Rewrite the research pipeline as a new event-sourced multi-agent platform** — replace current scripts, state files, and governance flow in one change.
   - Pros: Cleanest theoretical architecture and strongest uniformity.
   - Cons: Very high regression risk, difficult behavioral equivalence, oversized review surface, and unnecessary dependency/security pressure.
   - Effort: Very High

### Recommendation
Choose **Approach 2**. The first production-ready runtime should use only the Python standard library and existing project dependencies:

1. **Runtime contracts**
   - Define `AgentSpec`, `SkillSpec`, `TaskRequest`, `TaskRecord`, `TaskResult`, `ArtifactRef`, `Failure`, `RetryPolicy`, `PermissionSet`, and `Budget`.
   - Task states should be explicit: `queued`, `running`, `waiting`, `succeeded`, `failed`, `cancelled`, `timed_out`, and `budget_exhausted`.
   - Every task carries `run_id`, `task_id`, `parent_task_id`, dependency IDs, executor name, idempotency key, deadline, attempt count, and compact input/output references.

2. **Durable atomic state**
   - Use stdlib `sqlite3` in WAL mode as the runtime source of truth, with transactional task claims, dependency updates, attempts, events, memory entries, and unique idempotency keys.
   - Keep large evidence outside the database and store immutable artifact references/hashes. Continue producing existing compact JSON/Markdown research artifacts.
   - Use leases so interrupted `running` tasks can be reclaimed on restart. A single scheduler process should own orchestration in v1.

3. **Real delegation through pluggable executors**
   - Define a `TaskExecutor` protocol returning a typed `TaskResult`.
   - Ship `LocalFunctionExecutor` for deterministic registered handlers and `SubprocessJsonExecutor` for a child process that receives a task envelope and returns a result envelope.
   - A subagent is a persisted child task with its own agent, skills, context, permissions, budget, and result—not merely a function named after a role.
   - External LLM/service executors can implement the same protocol later; the first runtime needs none.

4. **Isolation, memory, and permissions**
   - Build immutable per-task context from explicit artifact references and allowlisted compact evidence. Child tasks do not inherit the parent transcript or unrestricted state.
   - Namespace memory as task-local, agent-local, and explicitly shared run memory. Parents receive compact child results and artifact references only.
   - Route tool use through an adapter registry with capability IDs, allowed path globs, network/subprocess flags, environment allowlists, and output-size limits.
   - Treat in-process adapters as trusted code. Capability mediation is enforceable application policy, not an OS sandbox; arbitrary untrusted executors require a later container/process-isolation layer.

5. **Lifecycle controls**
   - Centralize failure classification using the existing recovery vocabulary: fatal, recoverable, data, governance, no-material-result, timeout, cancellation, and budget exhaustion.
   - Retry only classified retryable failures, with persisted attempts, backoff, idempotency checks, and remaining-budget checks. Never blindly rerun a backtest after ambiguous partial side effects.
   - Support cooperative cancellation between steps and direct-child process termination, monotonic deadlines, per-task/whole-run timeouts, maximum task/depth/retry/subprocess/output budgets, and explicit terminal reasons.

6. **Research workflow and compatibility**
   - Implement a deterministic root `Coordinator` workflow: preflight; delegate hypothesis/literature work; select and materialize a candidate; delegate execution; delegate audit; apply governance; then schedule recovery or stop.
   - Initially wrap current functions/CLIs unchanged. Put adapters that write legacy `state/`, `runs/`, `reports/`, or bibliography files in an exclusive lane to prevent concurrent corruption.
   - Preserve current CLI arguments, exit codes, run artifacts, SPY/cost requirements, parent lock, duplicate guards, cooldowns, and manual promotion rules. Runtime state is additive, not a replacement for domain evidence.
   - Add characterization tests before moving each orchestration branch. Fix and lock the intended `update_memory()` behavior as an explicit prerequisite.

The implementation should be delivered as reviewable work units: runtime contracts/store; scheduler/executors; isolation/lifecycle controls; deterministic research adapters; compatibility facade; then delegated research workflow. This will exceed a single 400-line review budget and should be planned as chained slices.

### Risks
- Legacy adapters mutate multiple shared JSON/JSONL files non-transactionally; concurrent execution must remain disabled for that lane.
- Runtime SQLite state and legacy domain state can diverge after a crash unless reconciliation rules and idempotency boundaries are explicit.
- Subprocess cancellation may leave partial artifacts; adapters need staging, completion markers, and failure classification before retry.
- Application-level permissions do not securely sandbox malicious Python code or arbitrary external executors.
- Existing agent and skill documents are inconsistent in structure and encoding; loaders need validation, versioning, and clear failure behavior.
- Existing contracts and tests do not fully characterize current orchestration, and the broken `update_memory()` path makes “preserve behavior” ambiguous without a compatibility decision.
- Unbounded event/context payloads can recreate current state bloat unless retention and compact-result limits are enforced.

### Ready for Proposal
Yes — the proposal should lock the v1 boundary to a serial, dependency-free, SQLite-backed runtime with real persisted child tasks, trusted capability-mediated adapters, and backward-compatible autonomous research behavior. Secure execution of untrusted agents, distributed scheduling, and mandatory LLM integration should remain out of scope.
