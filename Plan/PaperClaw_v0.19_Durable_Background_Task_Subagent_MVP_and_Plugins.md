# PaperClaw v0.19 — Durable Background Task & Subagent Runtime MVP and Plugins

## 1. Status and dependency

This document is a **proposed implementation plan**, not a statement that the capability already exists.

v0.19 depends on the v0.18 isolated subagent increment being consolidated and accepted first. The required v0.18 baseline is:

- the main Agent can call a bounded `delegate_tasks` tool;
- each Worker receives a fresh runtime state and a separate model adapter;
- task DAG validation, path scope, writable scope, tool allow-list and file lease/CAS protections are enforced;
- recursive subagent delegation is prohibited;
- parent cancellation reaches the delegated task DAG;
- only a compact structured result is returned to the parent context.

The v0.18 synchronous implementation remains valid. v0.19 adds a durable task lifecycle beside it instead of replacing the existing Coordinator/Worker path.

Before v0.19 development begins:

1. v0.17 must be present on `main` with release evidence complete;
2. the v0.18 subagent and Desktop i18n changes must be rebased or consolidated without unresolved merge markers;
3. full non-live CI, Desktop Playwright and package smoke must pass at the exact v0.18 candidate SHA;
4. one real-provider isolated-subagent scenario must be recorded separately from Fake/Mock tests.

## 2. Objective

v0.19 converts delegated subagent work from one synchronous tool invocation into a first-class, durable and observable Task Runtime.

The MVP must provide:

1. persistent parent/child task records;
2. explicit task state transitions and terminal outcomes;
3. background execution with bounded concurrency;
4. durable queue, claim, lease and heartbeat semantics;
5. idempotent task creation and safe recovery after process restart;
6. task-scoped cancellation, timeout and budget enforcement;
7. durable task events with SSE replay;
8. structured task output retrieval without injecting full Worker history into the parent context;
9. trace correlation across parent Run, Task, Worker and Tool calls;
10. static plugin boundaries for future queue, executor, policy, telemetry, Skill and LSP adapters.

This version does **not** claim distributed exactly-once execution, arbitrary instruction-pointer recovery, production multi-tenant isolation, or automatic retry of uncertain external side effects.

## 3. Architecture

```text
CLI / TUI / Desktop / FastAPI
            ↓
TaskApplicationService
            ↓
SQLiteDurableTaskStore + DurableTaskEventStore
            ↓
Task admission / dependency / authorization policies
            ↓
Task queue → claim → lease → heartbeat
            ↓
TaskWorkerPool (bounded concurrency)
            ↓
Isolated Subagent Runtime
            ↓
Coordinator / Worker / Reviewer / ToolRegistry
            ↓
Task result + redacted events + durable receipts
```

The parent Agent does not own the Worker thread or process directly. It creates a durable task request and receives a `task_id`.

SQLite remains the source of truth for MVP task state and task events. In-memory conditions, thread notifications and local queues are wake-up optimizations only and must not be required for correctness.

The existing durable Run store remains authoritative for parent Run state. The new Task store records child work and links it through `parent_run_id` and optional `parent_task_id`.

## 4. Core contracts

### 4.1 Task identifiers and ownership

Every task must have:

- `task_id` — stable unique identifier;
- `idempotency_key` — caller-provided or deterministically derived creation key;
- `parent_run_id` — parent Agent Run;
- `parent_task_id` — optional parent task for future nested workflows;
- `conversation_id` — inherited ownership boundary;
- `agent_id` — Worker identity after claim;
- `attempt` — monotonically increasing execution attempt;
- `created_at`, `updated_at`, `terminal_at`;
- `task_version` — optimistic concurrency version.

The v0.19 public runtime must reject recursive `delegate_tasks` from Worker tool registries. `parent_task_id` exists for storage compatibility and future orchestrators, not to enable recursive model-driven subagents in this MVP.

### 4.2 Task request

`DurableTaskRequest` must include:

- overall goal;
- task title and objective;
- measurable acceptance criteria;
- dependencies;
- allowed paths;
- writable paths;
- allowed tools;
- task-specific step/model/tool/time budgets;
- output size limit;
- disconnect policy;
- retry policy identifier;
- optional metadata that is JSON-safe, bounded and redacted before persistence.

Raw API credentials, complete parent prompts, complete parent history and unbounded tool output must never be persisted in the task request.

### 4.3 Task states

Required state flow:

```text
created
   ↓
queued
   ↓
claimed
   ↓
running ───────────────→ succeeded
   │                         │
   ├→ waiting_dependency ────┘
   ├→ cancelling → cancelled
   ├→ timed_out
   ├→ failed
   ├→ blocked
   └→ unknown_outcome
```

Rules:

- only the application service may perform durable state transitions;
- every transition uses compare-and-swap on `task_version`;
- terminal states are immutable;
- a task with unsatisfied dependencies cannot be claimed;
- a dependency failure moves the dependent task to `blocked` unless an explicit policy says otherwise;
- `unknown_outcome` is terminal for automatic execution and requires operator review;
- cancellation is a request until the Worker confirms a terminal outcome.

### 4.4 Error taxonomy

The task runtime must preserve typed error categories:

- `validation_error`;
- `permission_denied`;
- `dependency_failed`;
- `queue_timeout`;
- `provider_timeout`;
- `tool_timeout`;
- `run_timeout`;
- `transport_error`;
- `protocol_error`;
- `execution_error`;
- `cancelled`;
- `budget_exhausted`;
- `recovery_required`;
- `unknown_outcome`.

These errors must not collapse into one generic failure string.

## 5. MVP scope

### 5.1 Durable task creation

Implement a `TaskApplicationService.create_task()` path that:

1. validates request structure and scope;
2. verifies parent Run and conversation ownership;
3. performs deterministic task admission checks;
4. creates the task and initial `task.created` event atomically;
5. enforces an idempotency uniqueness constraint;
6. returns the existing task when the same idempotency key is replayed with an equivalent request;
7. rejects key reuse with a materially different request fingerprint.

The parent Agent-facing tool should be split into two modes:

- existing `delegate_tasks` — synchronous compatibility path;
- new `task_create` — durable background path returning task identifiers immediately.

### 5.2 Durable queue, claim and lease

The SQLite reference implementation must support:

- deterministic enqueue order;
- dependency-aware eligibility;
- atomic claim of one eligible task;
- one active lease owner at a time;
- lease expiration;
- periodic heartbeat;
- bounded attempts;
- graceful release on known cancellation;
- startup classification of abandoned tasks.

Minimum lease fields:

- `lease_owner`;
- `lease_expires_at`;
- `last_heartbeat_at`;
- `claim_token`;
- `attempt`.

Only one Worker may successfully claim a given task version. Losing claim attempts must be observable but must not mutate the task.

### 5.3 Bounded background Worker pool

Implement a local `TaskWorkerPool` with:

- explicit start and stop lifecycle;
- bounded concurrency through a semaphore or fixed worker count;
- no unbounded thread creation;
- cooperative shutdown;
- per-task wall-time timeout;
- parent and task cancellation polling;
- Worker heartbeat while the task is active;
- deterministic exception classification;
- no daemon-thread-only correctness assumption.

Blocking model or tool adapters may execute in controlled threads, but durable state transitions must remain serialized through the application/store boundary.

The default MVP concurrency should remain small and configurable, for example 1–3 Workers.

### 5.4 Isolated subagent execution

Each claimed task must create:

- a fresh Agent runtime state;
- a fresh model adapter or explicitly safe provider session;
- a scoped ToolRegistry;
- no `delegate_tasks` or `task_create` recursive tool;
- a task-scoped stop token;
- a task-scoped event bridge;
- a task-scoped budget ledger.

The Worker receives only:

- the task objective;
- acceptance criteria;
- permitted workspace context;
- explicit project instructions selected by the existing context pipeline;
- dependency output summaries when required.

The Worker must not receive the full parent conversation or hidden parent reasoning.

### 5.5 Task budgets

Enforce both per-task and parent aggregate limits:

- max steps;
- max model calls;
- max tool calls;
- max wall time;
- max output bytes;
- optional token/cost budget when provider metadata is available.

The parent Run must be able to reserve a bounded child-task budget before creation. Child usage must be reported back to the parent budget ledger even when the child task fails or is cancelled.

Budget exhaustion produces a typed terminal outcome. It must not be represented as successful task completion.

### 5.6 Cancellation semantics

Support:

- cancel one task;
- cancel all child tasks for a parent Run;
- parent cancellation propagation;
- cancellation before claim;
- cancellation after claim but before model/tool execution;
- cancellation during a cooperative model/tool call;
- `unknown_outcome` when a side-effecting operation cannot be confirmed.

A client disconnect must not implicitly cancel a background task. Default policy is `detach_on_disconnect`.

`cancel_on_disconnect` may be supported only as an explicit persisted policy.

### 5.7 Recovery and idempotency

On service or Worker restart, active tasks with expired leases must be classified:

- safe to retry → return to `queued` with incremented attempt;
- durable terminal receipt exists → finalize from receipt;
- task never began external execution → return to `queued`;
- side effect may have occurred without a durable receipt → `unknown_outcome`;
- corrupted or incompatible state → `blocked` or `recovery_required`.

Automatic retry is permitted only when the retry policy and durable evidence classify the operation as safe.

Examples:

| Operation | Default automatic retry |
|---|---:|
| read-only file/query operation | yes, within attempt budget |
| provider 429/5xx before tool execution | yes, classified backoff |
| local atomic file write with verified expected hash | conditional |
| shell command with unknown side effect | no |
| external write, email, payment or delete | no without idempotency receipt |

### 5.8 Durable task events and SSE

Persist task events with per-task monotonically increasing sequence numbers.

Required events:

- `task.created`;
- `task.queued`;
- `task.claimed`;
- `task.started`;
- `task.heartbeat`;
- `task.dependency.waiting`;
- `task.model.completed`;
- `task.tool.completed`;
- `task.progress`;
- `task.output.available`;
- `task.cancellation.requested`;
- `task.completed`;
- `task.failed`;
- `task.cancelled`;
- `task.timed_out`;
- `task.blocked`;
- `task.unknown_outcome`.

`GET /v1/tasks/{task_id}/events` must:

- accept `Last-Event-ID`;
- replay persisted events after that sequence;
- continue waiting for new events;
- emit non-sequenced transport heartbeats;
- stop only after the task is terminal and no later event remains;
- preserve existing redaction rules.

### 5.9 Task query and control interfaces

Add Agent tools or equivalent runtime commands:

- `TaskCreateTool` / `task_create`;
- `TaskGetTool` / `task_get`;
- `TaskListTool` / `task_list`;
- `TaskStopTool` / `task_stop`;
- `TaskOutputTool` / `task_output`.

Minimum Service API:

```http
POST /v1/tasks
GET  /v1/tasks/{task_id}
GET  /v1/tasks/{task_id}/events
POST /v1/tasks/{task_id}/cancel
GET  /v1/runs/{run_id}/tasks
GET  /v1/tasks/{task_id}/output
```

Public responses must expose bounded summaries, state, counters and redacted errors. They must not expose raw credentials, complete prompts or unrestricted tool output.

### 5.10 Structured task output

`TaskOutput` should contain:

- task outcome;
- summary;
- acceptance-criteria results;
- changed file paths;
- verification evidence references;
- warnings and unresolved issues;
- resource counters;
- bounded artifact references;
- output fingerprint.

The parent Agent should receive or retrieve this compact structure. Full Worker histories stay in durable trace storage and are not automatically copied into parent context.

### 5.11 Trace and observability

Correlate:

- `request_id`;
- `conversation_id`;
- `parent_run_id`;
- `task_id`;
- `parent_task_id`;
- `agent_id`;
- `attempt`;
- model call identifiers;
- tool call identifiers;
- event sequence;
- prompt/policy version and fingerprint where available.

Minimum metrics:

- queue latency;
- execution latency;
- dependency wait latency;
- model/tool call counts;
- retry count;
- heartbeat failures;
- cancellation latency;
- recovery count;
- terminal outcome counts;
- task success rate;
- budget exhaustion rate;
- `unknown_outcome` rate.

Logs and exported traces must use the existing redaction boundary before leaving the runtime.

## 6. Persistence model

The exact schema may follow existing repository conventions, but the MVP needs equivalent tables or projections for:

### `durable_tasks`

- task identity and ownership;
- request fingerprint and idempotency key;
- current state and version;
- dependency data;
- limits and policy identifiers;
- lease/heartbeat fields;
- attempt and error classification;
- terminal output summary and fingerprint;
- timestamps.

### `durable_task_events`

- task ID;
- sequence;
- event type;
- redacted JSON payload;
- timestamp;
- uniqueness on `(task_id, sequence)`.

### `durable_task_receipts`

- task ID and attempt;
- operation/tool identifier;
- idempotency key when present;
- pre-execution and post-execution status;
- bounded result fingerprint;
- side-effect classification;
- timestamp.

### `durable_task_dependencies`

- task ID;
- dependency task ID;
- dependency policy;
- uniqueness on the task/dependency pair.

Schema migrations must be additive and tested against an existing v0.17/v0.18 database fixture.

## 7. Security and authorization

Every task creation and execution must cross deterministic non-model policies.

Minimum checks:

- parent Run/conversation ownership;
- task count and aggregate budget;
- allowed tool capabilities;
- workspace path containment;
- writable path containment;
- dependency ownership;
- recursive delegation denial;
- external network and private-address policy;
- high-risk action approval requirements;
- output redaction and size limits.

The invariant remains:

> A model may propose a task or tool call; only the policy and application layers can authorize durable creation and execution.

Policy plugin failures must fail closed.

Observer/exporter plugin failures must be isolated and must not change durable task state.

## 8. Plugin boundaries after MVP

Plugins remain static, explicitly registered and versioned. v0.19 must not introduce arbitrary runtime code download, automatic discovery from untrusted directories or a public plugin marketplace.

### 8.1 Queue backend plugin

`TaskQueueBackendPlugin`

Proposed contract:

- enqueue task reference;
- claim eligible task;
- renew lease;
- acknowledge terminal state;
- release or retry with backoff;
- dead-letter/blocked notification;
- health status.

Future adapters:

- `RedisStreamsTaskQueuePlugin`;
- PostgreSQL `SKIP LOCKED` queue;
- cloud queue adapter.

The queue is not the source of truth for final task state. Durable storage remains authoritative.

### 8.2 Durable task store plugin

`DurableTaskStorePlugin`

Future adapters:

- PostgreSQL task/event store;
- external artifact/blob store;
- event notification backend.

SQLite remains the reference MVP implementation and defines conformance behavior.

### 8.3 Task executor plugin

`TaskExecutorPlugin`

Possible implementations:

- local thread-backed Worker;
- local subprocess Worker;
- remote Worker gateway.

The contract must preserve task scope, stop token, event sink, budget ledger and typed terminal result. Executor exceptions must not bypass durable finalization.

### 8.4 Admission and authorization plugins

- `TaskAdmissionPolicyPlugin`;
- `TaskCapabilityPolicyPlugin`;
- `TaskDependencyPolicyPlugin`;
- `TaskRetryPolicyPlugin`;
- `TaskApprovalPlugin`;
- `TaskNetworkEgressPolicyPlugin`.

Any exception or invalid response from these plugins produces denial or manual review, never implicit permission.

### 8.5 Resilience plugins

- `TaskBackoffPlugin`;
- `ProviderCircuitBreakerPlugin`;
- `ProviderFallbackPlugin`;
- `TaskRateLimitPlugin`;
- `TaskBudgetPolicyPlugin`.

Retry classification must distinguish authentication, 429, 5xx, transport, protocol, context overflow, invalid response, tool timeout and uncertain side effect.

### 8.6 Telemetry plugins

- `OpenTelemetryTaskExporterPlugin`;
- `PrometheusTaskMetricsPlugin`;
- `JsonTaskTraceExporterPlugin`.

These are observer plugins. They receive bounded, already-redacted events and cannot mutate task state or authorize execution.

### 8.7 Skill plugins — planned v0.20

After the durable task MVP, add a static Skill boundary:

- `SkillManifest` with ID, version, description, parameters and required capabilities;
- `SkillRegistry` with explicit registration;
- `SkillTool` that validates arguments and capability requirements;
- local trusted Skill packages;
- optional MCP-backed Skill adapters.

Initial PaperClaw Skills should wrap existing verified workflows such as:

- code review;
- cloud development handoff;
- release acceptance;
- research-method tailoring.

Skills are reusable workflow contracts, not unrestricted prompt aliases. Skill execution must still pass tool authorization and task budget checks.

### 8.8 Plan Mode policy plugin — planned v0.20

Add explicit runtime modes:

```text
execute ↔ plan
```

In Plan Mode:

- file writes and high-risk Bash are denied;
- read/search/retrieval tools remain available;
- the Agent produces a structured plan artifact;
- execution begins only after explicit approval or a trusted caller transition.

Proposed extension points:

- `RuntimeModePolicyPlugin`;
- `PlanApprovalPlugin`;
- `PlanArtifactStorePlugin`.

A Worker/subagent cannot independently elevate itself from Plan Mode to Execute Mode.

### 8.9 LSP plugins — planned v0.21

Add read-only semantic code intelligence first:

- diagnostics;
- go to definition;
- references;
- symbols;
- hover/type information.

Proposed boundary:

`LanguageServicePlugin`

The plugin owns server lifecycle, workspace initialization, request timeout, capability negotiation and bounded result normalization.

The first implementation must remain read-only. Code actions, rename and workspace edits require a later authorization design.

### 8.10 Agent communication plugin — future

A future `AgentMessageBusPlugin` may support explicit Worker-to-Coordinator messages, but it is not part of v0.19.

It must not become an unbounded hidden chat channel. Messages require schema, size limits, task ownership and durable correlation.

## 9. API and UI integration boundaries

### CLI

Proposed commands:

```text
paperclaw task create ...
paperclaw task get <task_id>
paperclaw task list --run-id <run_id>
paperclaw task stop <task_id>
paperclaw task output <task_id>
paperclaw task worker --database <path>
```

### TUI/Desktop

MVP display should include:

- task ID and title;
- state;
- parent Run;
- dependencies;
- Worker/attempt;
- queue and execution duration;
- model/tool counters;
- cancellation control;
- output summary.

The UI is a projection layer. It must not directly update SQLite, execute tools or decide recovery.

### Service

The Service API must reuse the durable application service. No second in-memory-only task implementation is allowed.

The default development deployment should remain loopback/local unless an authentication boundary is explicitly configured. v0.19 does not claim secure public multi-tenant hosting.

## 10. Evaluation plan

Add deterministic evaluation dimensions:

- task completion rate;
- acceptance-criteria satisfaction;
- dependency correctness;
- duplicate execution rate;
- recovery correctness;
- cancellation correctness;
- permission violation count;
- context-isolation violations;
- queue latency;
- execution latency;
- model/tool calls;
- cost/token usage when available;
- parent-context compression ratio;
- `unknown_outcome` rate.

Compare at least:

1. single Agent baseline;
2. v0.18 synchronous subagent delegation;
3. v0.19 durable background tasks with one Worker;
4. v0.19 durable background tasks with bounded parallel Workers.

The comparison must hold task set, provider/model, workspace fixture, limits and verification criteria constant where possible.

A performance improvement without task correctness and safety evidence is not sufficient for acceptance.

## 11. Required tests

### 11.1 Unit tests

1. request and state contract validation;
2. legal and illegal state transitions;
3. idempotency key equivalence and conflict;
4. dependency DAG validation and cycle rejection;
5. budget reservation and exhaustion;
6. authorization fail-closed behavior;
7. retry classification;
8. output bounding and redaction;
9. plugin duplicate IDs and failure isolation;
10. Worker tool registry excludes recursive delegation.

### 11.2 SQLite integration tests

1. create task and event atomically;
2. only one Worker wins a claim;
3. heartbeat renews the correct lease;
4. stale lease can be reclaimed only after classification;
5. terminal state is immutable;
6. dependency success releases downstream task;
7. dependency failure blocks downstream task;
8. idempotency survives service recreation;
9. event replay survives service recreation;
10. schema migration preserves existing databases;
11. uncertain side effect becomes `unknown_outcome`;
12. cancellation races produce one valid terminal state.

### 11.3 Process acceptance tests

Use real subprocesses and SQLite files to verify:

1. process A creates and starts a task;
2. process A exits or is terminated;
3. process B starts with the same database;
4. expired lease is classified correctly;
5. safe work resumes or uncertain work stops;
6. SSE/task event replay returns the durable history.

This test must not claim recovery of an in-flight provider TCP response or arbitrary Python instruction pointer.

### 11.4 UI and API tests

- FastAPI create/get/list/cancel/output;
- `Last-Event-ID` replay;
- disconnect default detaches;
- explicit cancel-on-disconnect policy;
- Desktop/TUI task list projection;
- stale and duplicate UI event rejection;
- protected browser asset and package smoke remain green.

### 11.5 Real-provider acceptance

At least one real-provider scenario must:

- create two independent read-only tasks;
- demonstrate bounded parallel execution;
- prove fresh Worker contexts;
- record parent and child trace identifiers;
- return compact structured outputs;
- show aggregate budget accounting;
- complete without recursive delegation.

A second scenario should cancel an active task and record whether the terminal result is `cancelled` or `unknown_outcome`.

FakeModel, Mock API, static tests and browser bridges prove control flow only and must not be reported as real-provider or real-OS validation.

## 12. Implementation sequence

### Phase A — freeze contracts

- task request/state/output/error contracts;
- SQLite schema and migration;
- transition table;
- event schema;
- plugin protocol stubs;
- architecture decision record.

### Phase B — durable store

- create/get/list;
- event append/replay;
- idempotency;
- dependency storage;
- CAS transitions;
- lease and heartbeat.

### Phase C — background executor

- bounded Worker pool;
- claim loop;
- isolated runtime adapter;
- budget ledger;
- cancellation;
- terminal finalization.

### Phase D — recovery

- startup scan;
- safe retry classification;
- durable receipts;
- unknown outcome;
- process-restart tests.

### Phase E — interfaces

- Agent tools;
- CLI;
- FastAPI and SSE;
- TUI/Desktop projection.

### Phase F — acceptance

- focused tests;
- full regression;
- process acceptance;
- Desktop package smoke;
- real-provider scenarios;
- artifacts and Handoff.

Each phase must retain a runnable baseline. Do not implement UI before durable store semantics are executable and tested.

## 13. Non-goals

- Kafka, Kubernetes or distributed scheduler deployment;
- production Redis requirement in MVP;
- distributed exactly-once execution;
- automatic retry of destructive or uncertain operations;
- arbitrary nested model-created subagent trees;
- remote public multi-tenant service without authentication;
- autonomous approval by another LLM;
- full plugin marketplace or untrusted dynamic code loading;
- Plan Mode implementation in v0.19;
- Skill runtime implementation in v0.19;
- LSP implementation in v0.19;
- recovery of an in-flight provider socket or Python stack frame;
- replacing the existing Run, Trace, Context, MCP, Retrieval or Evaluation foundations.

## 14. Definition of done

v0.19 MVP is complete only when:

- tasks are durable first-class objects linked to parent Runs;
- task creation is idempotent and survives service restart;
- dependency-aware queue and single-winner claim behavior are verified;
- bounded background Workers execute isolated subagent runtimes;
- task and parent cancellation semantics are explicit and tested;
- safe retry and unknown-side-effect recovery are distinguished;
- task events replay through SSE after restart;
- TaskCreate/Get/List/Stop/Output interfaces use the same application service;
- parent context receives compact output rather than full Worker history;
- authorization is deterministic and fails closed;
- observer plugins are fail isolated;
- unit, SQLite integration, process acceptance and full non-live regression pass;
- Desktop/TUI/API projections do not bypass the durable service;
- at least one real-provider parallel-subagent scenario is recorded;
- Fake/Mock evidence is clearly separated from real-provider evidence;
- exact-head CI runs, artifact digests, known limitations and Handoff are written under `artifacts/v0_19/` and `docs/handoff/`.

## 15. Planned follow-up order

```text
v0.18  Isolated synchronous subagent delegation + Desktop i18n
  ↓
v0.19  Durable background Task & Subagent Runtime
  ↓
v0.20  Plan Mode + AskUserQuestion + static Skills
  ↓
v0.21  Read-only LSP semantic tools
  ↓
future Remote Workers / Redis or PostgreSQL queue / Agent message bus
```

The priority rule is:

> First make task lifecycle, recovery, idempotency and authorization correct on one durable node; only then add distributed queues, richer plugins and semantic tooling.
