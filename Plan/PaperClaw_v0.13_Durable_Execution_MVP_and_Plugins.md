# PaperClaw v0.13 Durable Execution — MVP + Plugin Plan

> Status: READY FOR IMPLEMENTATION  
> Dependency: v0.12 application-service contracts should be stable  
> Baseline: existing SQLite Session/Checkpoint/Trace infrastructure plus the v0.12 service run model  
> Goal: make service-level Agent runs durable across process interruption without claiming transparent recovery of unsafe external side effects.

## 1. Problem statement

PaperClaw already persists Session events, Checkpoints, and durable Trace facts. The service layer still needs an authoritative durable execution record for:

- queued and active runs;
- optimistic state transitions;
- worker leases and heartbeats;
- idempotency records;
- restart reconciliation;
- recovery classification;
- duplicate action protection.

Durability means preserving truth and making safe decisions after failure. It does not mean pretending that every Provider or shell process can resume from the exact instruction pointer.

## 2. Authoritative state machine

```text
created
  -> queued
  -> running
  -> cancelling
  -> completed
  -> failed
  -> stopped
  -> recovery_required
```

Allowed recovery transitions:

```text
queued  -> queued
running -> queued              only when replay is explicitly classified safe
running -> recovery_required   default when external side effects are uncertain
cancelling -> stopped          when stop outcome is proven
cancelling -> recovery_required otherwise
```

Terminal states are immutable.

Every transition requires:

- expected current state;
- expected integer version;
- next state;
- timestamp;
- transition reason;
- actor/worker identifier;
- optional sanitized metadata.

## 3. MVP scope

### 3.1 SQLite durable run store

Add a dedicated store using the existing repository conventions:

Tables should cover:

- durable runs;
- state-transition journal;
- worker leases;
- idempotency records;
- action receipts.

Requirements:

- WAL mode where supported;
- explicit transactions;
- foreign keys enabled;
- stable schema version;
- migrations are additive and tested;
- public APIs return immutable domain objects;
- no secret values are persisted.

### 3.2 Compare-and-swap transitions

The store exposes operations similar to:

```python
create_run(...)
get_run(run_id)
transition(run_id, expected_state, expected_version, next_state, ...)
claim_queued_run(worker_id, lease_seconds)
renew_lease(run_id, worker_id, expected_version, lease_seconds)
release_lease(...)
list_recovery_candidates(...)
```

Two workers must not successfully claim the same run.

### 3.3 Lease and heartbeat

- a worker claim has an expiry;
- heartbeat renewal is explicit;
- stale lease ownership is rejected;
- service shutdown releases only leases it owns;
- expired leases are reconciled on startup;
- wall-clock timestamps are stored in UTC;
- tests use an injectable clock.

### 3.4 Recovery classifier

Introduce a pure policy contract:

```python
class RecoveryClassifier(Protocol):
    def classify(self, run: DurableRun, evidence: RecoveryEvidence) -> RecoveryDecision: ...
```

MVP default policy:

- `created` / `queued`: safe to queue;
- `running` without any external action receipt: safe to requeue once;
- `running` with uncertain external side effects: `recovery_required`;
- `cancelling`: `recovery_required` unless a terminal stop event is durable;
- terminal: no action.

The policy must preserve uncertainty rather than silently retrying.

### 3.5 Action idempotency receipts

Before an externally visible tool action:

1. derive a stable action key from run ID, logical step ID, tool name, and canonical arguments hash;
2. reserve the action key;
3. execute only if reservation is new;
4. record sanitized outcome metadata;
5. duplicate delivery returns the existing receipt.

MVP integration may use a test tool adapter and a narrow hook rather than rewriting all tools.

### 3.6 Startup reconciliation

On application startup:

- scan non-terminal runs;
- inspect lease expiry and durable terminal events;
- apply recovery classifier;
- transition with CAS;
- emit a reconciliation report;
- never start duplicate work before reconciliation finishes.

## 4. MVP deliverables

Suggested modules:

```text
src/paperclaw/durability/
  __init__.py
  contracts.py
  sqlite_store.py
  recovery.py
  action_receipts.py
  coordinator.py
```

Tests:

```text
tests/unit/durability/
tests/integration/durability/
```

Artifacts:

```text
artifacts/v0_13/implementation_summary.md
artifacts/v0_13/test_report.md
artifacts/v0_13/known_limitations.md
docs/handoff/PaperClaw_v0.13_Durable_Execution_HANDOFF.md
```

## 5. Plugin layer

### 5.1 Durable store adapter

After the SQLite MVP is frozen:

```python
class DurableRunStore(Protocol):
    ...
```

Potential plugins:

- PostgreSQL store;
- Redis lease accelerator;
- cloud database adapter;
- external workflow-engine bridge.

The SQLite implementation remains the reference semantics.

### 5.2 Recovery policy plugin

Alternative policies may classify specific tools as replay-safe or compensation-required.

Restrictions:

- policy receives sanitized metadata;
- a plugin cannot force replay when the core safety guard says evidence is insufficient;
- decisions are journaled with policy ID and version;
- policy exceptions fail closed to `recovery_required`.

### 5.3 Action receipt plugin

Optional plugins may implement:

- provider request idempotency keys;
- transactional outbox;
- compensation handlers;
- remote action ledger.

No plugin may mark an action successful without durable evidence.

## 6. Failure-injection test matrix

| Scenario | Expected result |
|---|---|
| process dies while queued | run remains/re-enters queued |
| process dies before any external action | one safe requeue allowed |
| process dies after uncertain tool action | `recovery_required` |
| two workers claim one run | exactly one succeeds |
| stale worker renews lease | rejected |
| duplicate transition | CAS conflict |
| duplicate action delivery | one execution, same receipt returned |
| terminal run receives update | rejected |
| corrupted/incompatible schema | fail closed with typed error |
| clock advances past lease | reconciliation candidate |
| plugin classifier raises | `recovery_required` |
| restart reconciliation repeated | idempotent result |

## 7. Delivery sequence

### Segment 0 — State and schema design

- map existing Session, Trace, Checkpoint, and service run contracts;
- document which store is authoritative for which fact;
- freeze transition table and schema;
- add migration tests.

### Segment 1 — Store and CAS

- implement SQLite store;
- implement transitions, journal, idempotency, and lease claims;
- add concurrency tests using separate connections.

### Segment 2 — Recovery coordinator

- implement classifier and startup reconciliation;
- add injectable clock;
- add crash-state fixture tests.

### Segment 3 — Action receipts

- implement reservation and outcome recording;
- integrate one deterministic tool path or adapter;
- prove duplicate delivery does not repeat the side effect.

### Segment 4 — Plugins and verification

- add static store/recovery plugin contracts;
- run focused tests, full regression, Ruff;
- perform a manual kill/restart smoke;
- update Handoff and artifacts.

## 8. Non-goals

The MVP does not include:

- transparent resumption of an in-flight LLM HTTP request;
- reattachment to arbitrary child processes;
- exactly-once semantics across all external systems;
- distributed consensus;
- Kafka or a mandatory message broker;
- automatic compensation for unknown tools;
- MultiAgent durable mailbox implementation;
- production HA or cross-region failover.

## 9. Definition of Done

MVP is complete only when:

- the state machine and transition journal are enforced in SQLite;
- CAS prevents conflicting updates;
- leases prevent double claim;
- startup reconciliation is deterministic and idempotent;
- uncertain side effects become `recovery_required`;
- duplicate action receipts prevent a tested side effect from running twice;
- failure-injection tests pass;
- existing Session/Trace facts are not silently redefined;
- full non-live regression and Ruff pass.

Plugin phase is complete only when:

- store and recovery policy protocols are stable;
- SQLite remains the reference implementation;
- plugin failures fail closed;
- plugin identity/version is included in decisions.
