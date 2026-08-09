# SPEC — PaperClaw v0.39 Structured Persistent Memory

## Status

```text
PROPOSED
```

## Objective

PaperClaw SHALL provide bounded, persistent, cross-session Memory without changing the semantics of SessionEvent, Transcript, Artifact, Evidence, ContextSnapshot, Checkpoint, QueryEngine, or ToolRegistry.

---

## M39-R01 — Persistent Memory

The system SHALL persist Memory across Conversations.

### Scenario

Given:

```text
Session A writes memory M
Session A ends
Session B starts
```

Then:

```text
M is available to Session B according to its scope and activation state
```

---

## M39-R02 — Scope Isolation

Every Memory SHALL belong to exactly one supported MVP scope:

```text
USER
PROJECT
```

PROJECT Memory SHALL NOT appear in another project.

USER Memory MAY appear across projects belonging to the same resolved user context.

Unknown or unsupported scopes SHALL be rejected fail-closed.

---

## M39-R03 — Memory Is Not Transcript

The system SHALL NOT treat complete Conversation history as Memory.

Conversation history SHALL remain in Message / Session persistence.

Memory SHALL contain only selected durable information.

Session/history search SHALL remain conceptually separate from Memory search.

---

## M39-R04 — Memory Is Not Evidence

Memory SHALL NOT replace Evidence.

A Memory MAY reference Evidence through `source_refs`.

```text
Memory.source_refs
    → Evidence
```

Deleting or replacing Memory SHALL NOT modify referenced Evidence.

Evidence SHALL remain the source of truth for externally grounded claims.

---

## M39-R05 — Memory Is Not Artifact

Artifact bodies SHALL NOT be copied into Memory by default.

Memory MAY contain:

```text
artifact reference
bounded artifact summary
important durable conclusion
```

The Artifact remains the source object.

---

## M39-R06 — Immutable Mutation History

Memory replacement SHALL create a new MemoryItem.

Old Memory SHALL remain auditable.

```text
M1
 ↓ superseded by
M2
```

Deletion SHALL create a tombstone or equivalent immutable deletion record.

Physical history deletion is outside the MVP.

---

## M39-R07 — Active Memory Projection

The system SHALL expose a deterministic active projection over immutable Memory history.

An active Memory SHALL be the current non-tombstone head of its lineage.

Historical superseded records SHALL NOT appear as active Memory unless explicitly requested through history/audit APIs.

---

## M39-R08 — Frozen Session Snapshot

At Conversation/Session initialization, the system SHALL capture the active pinned Memory set for the resolved USER and PROJECT scopes.

```text
MemoryStore
   ↓
MemorySnapshot
```

The pinned snapshot SHALL remain immutable for that Conversation.

---

## M39-R09 — Mid-Session Write Semantics

Given:

```text
Session S starts with memory A
```

When:

```text
A is replaced by B during S
```

Then:

```text
persistent MemoryStore = B
current pinned snapshot(S) = A
```

A new Session SHALL observe B if B is active and in scope.

This behavior is REQUIRED.

---

## M39-R10 — Prompt Stability

Pinned Memory SHALL use the frozen MemorySnapshot for every model call in the same Conversation.

Memory writes SHALL NOT alter the pinned Memory prefix during the current Conversation.

The system SHALL expose or persist a deterministic:

```text
rendered_hash
```

for the pinned snapshot.

Dynamic Recall Memory SHALL be treated separately from pinned-prefix stability.

---

## M39-R11 — Context Layer

Memory presented to the model SHALL enter:

```text
Context Layer L5
```

Memory SHALL NOT automatically enter L0 or L1.

Existing L0-L4 semantics SHALL remain unchanged.

---

## M39-R12 — Pinned Memory

A MemoryItem MAY be:

```text
pinned = true
```

Pinned Memory SHALL be considered during Session-start snapshot creation.

Pinned Memory SHALL have a bounded independent token budget.

Unbounded pinned injection is prohibited.

---

## M39-R13 — Recall Memory

Active Memory not included in the pinned snapshot SHALL be searchable.

Retrieval SHALL apply at minimum:

```text
scope filter
active-only filter
query relevance
top-k
memory token budget
```

Retrieved results SHALL be rendered as L5 ContextItems with provenance metadata.

---

## M39-R14 — MVP Retrieval Boundary

v0.39 SHALL use a local deterministic lexical/SQLite retrieval implementation or an equivalent existing repository-native mechanism.

v0.39 SHALL NOT require:

```text
external embedding API
external vector database
external Memory provider
LLM reranker
```

Those integrations belong to a later provider layer.

---

## M39-R15 — Provenance

Each MemoryItem SHALL contain sufficient provenance to answer:

```text
Where did this memory come from?
```

Minimum provenance fields:

```text
source_refs
trust_level
created_from_run_id
created_from_sequence
created_at
```

If a field is legitimately unavailable, its absence SHALL be explicit rather than fabricated.

---

## M39-R16 — Trust Preservation

Creating Memory SHALL NOT increase source trust.

Content originating as:

```text
external_untrusted
```

SHALL NOT be automatically promoted to trusted persistent Memory.

A trusted Evidence transformation or explicit user confirmation is required before such information can become durable trusted Memory.

---

## M39-R17 — Memory Kinds

MVP SHALL support a bounded vocabulary equivalent to:

```text
user_preference
project_fact
decision
constraint
workflow
lesson
```

Implementation MAY use enums/constants consistent with repository conventions.

Additional kinds SHALL require explicit future design or schema evolution rather than free-form uncontrolled categories.

---

## M39-R18 — Memory Service Boundary

All Memory mutation SHALL pass through a MemoryService or equivalent single domain-service boundary.

The following SHALL NOT directly manipulate Memory persistence:

```text
QueryEngine
AgentRuntime
ContextBuilder
Memory Tool adapter
```

ContextBuilder MAY read Memory through a defined read-only service/retriever/provider interface.

---

## M39-R19 — Repository Boundary

Memory persistence SHALL be behind a Repository abstraction consistent with PaperClaw's existing persistence architecture.

Domain services SHALL NOT issue ad-hoc sqlite3 writes outside the persistence boundary.

Schema migration SHALL preserve existing Context/Session data.

---

## M39-R20 — Tool Boundary

Memory actions SHALL reuse the existing ToolRegistry and existing validation/execution lifecycle.

Required MVP actions:

```text
add
replace
remove
list
search
```

No Memory-specific Tool execution path SHALL be added to QueryEngine.

---

## M39-R21 — Audit Events

Memory lifecycle operations SHALL emit auditable events.

Minimum event semantics:

```text
memory.added
memory.replaced
memory.removed
memory.snapshot_created
memory.retrieved
```

Actual event names MAY follow current repository naming conventions if they remain stable and documented.

Audit payloads SHOULD store IDs, hashes, scope and bounded metadata rather than duplicate large Memory content.

Existing redaction rules SHALL still apply.

---

## M39-R22 — ContextSnapshot Traceability

When Memory contributes to a model call, the resulting ContextSnapshot or associated immutable context records SHALL make it possible to identify contributing `memory_id` values.

Pinned and retrieved Memory SHALL be distinguishable, for example through metadata equivalent to:

```text
memory_mode = pinned | retrieved
```

---

## M39-R23 — Backward Compatibility

With Memory disabled or no active Memory available:

```text
PaperClaw behavior SHALL remain equivalent to pre-v0.39 behavior.
```

Existing public behavior for the following SHALL remain compatible unless separately documented:

```text
Context
Session
Checkpoint / Resume
QueryEngine
ToolRegistry
Trace
MultiAgent paths
```

---

## M39-R24 — No Automatic Extraction Requirement in MVP

v0.39 SHALL NOT require automatic LLM-based Memory extraction after every turn.

The initial implementation SHALL prefer:

```text
explicit Memory Tool writes
deterministic system writes
user-confirmed writes
```

Automatic extraction, consolidation, decay and self-editing policies are future capabilities.

---

## M39-R25 — No External Memory Provider Requirement in MVP

v0.39 SHALL NOT depend on third-party Memory infrastructure.

Examples outside MVP:

```text
Mem0
OpenViking
Honcho
Hindsight
Supermemory
external vector DB
hosted user-memory service
```

Future external integration SHALL sit behind a dedicated MemoryProvider abstraction rather than bypassing core semantics.

---

## M39-R26 — Failure Isolation

Memory retrieval failure SHALL NOT corrupt Session state.

Memory write failure SHALL NOT be reported as success.

If dynamic Recall Memory fails, the current Run MAY continue without recalled Memory only if:

```text
the failure is surfaced in Trace/Event output
no required pinned state is silently substituted
```

Failure to capture required pinned Memory at Session initialization SHALL follow an explicit runtime policy and SHALL NOT silently fabricate an empty successful snapshot.

---

## M39-R27 — Deterministic Snapshot Assembly

Given identical active pinned Memory, scope resolution and configuration, snapshot assembly SHALL produce deterministic ordering and deterministic rendered content.

Ordering MUST NOT depend on unordered database iteration.

Recommended deterministic order:

```text
scope priority
→ importance DESC
→ kind
→ created_at
→ memory_id
```

Equivalent deterministic ordering is acceptable if documented and tested.

---

## M39-R28 — Memory Budget

Memory injection SHALL respect a separate Memory budget.

Suggested starting defaults:

```text
USER pinned memory: ~500 tokens
PROJECT pinned memory: ~1000 tokens
```

Exact defaults MAY change during implementation.

Unbounded Memory injection is prohibited.

Budget overflow behavior SHALL be deterministic and tested.

---

## M39-R29 — Content Boundary

Persistent Memory SHALL store compact durable knowledge, not arbitrary large source objects.

The system SHALL reject or bound attempts to use Memory as a substitute blob store for:

```text
complete Artifact bodies
complete Evidence bodies
full Transcript dumps
unbounded raw Tool output
```

References to those objects are permitted.

---

## M39-R30 — History Search Separation

The Memory subsystem SHALL NOT claim to provide complete historical Conversation reconstruction.

Session/Transcript search is a separate capability and MAY be implemented in v0.39.1 or later.

---

# Acceptance Gates

v0.39 SHALL NOT be marked GO until the following are proven:

```text
[ ] M39-01 schema migration
[ ] M39-02 add/list
[ ] M39-03 immutable replace
[ ] M39-04 tombstone remove
[ ] M39-05 USER scope isolation
[ ] M39-06 PROJECT scope isolation
[ ] M39-07 frozen pinned snapshot
[ ] M39-08 mid-session write isolation
[ ] M39-09 next-session refresh
[ ] M39-10 deterministic rendered_hash
[ ] M39-11 L5 pinned injection
[ ] M39-12 L5 recall injection
[ ] M39-13 provenance traceability
[ ] M39-14 external_untrusted promotion guard
[ ] M39-15 Memory/Transcript separation
[ ] M39-16 Memory/Evidence separation
[ ] M39-17 Memory/Artifact separation
[ ] M39-18 ToolRegistry integration
[ ] M39-19 audit events
[ ] M39-20 ContextSnapshot memory traceability
[ ] M39-21 empty/disabled-memory backward compatibility
[ ] M39-22 full non-live regression
```

Final decision:

```text
all required gates PASS
        ↓
      v0.39 GO

any scope/snapshot/provenance/backward-compatibility blocker
        ↓
      v0.39 NO-GO
```

---

# Explicit Non-Goals

The following are not acceptance requirements for v0.39:

```text
LLM automatic Memory extraction
LLM Memory consolidation
semantic embedding provider
external vector database
third-party Memory SaaS
knowledge graph
cross-device sync
multi-user hosted identity service
organization/team Memory scopes
full Transcript FTS/session search
```

They MUST NOT be pulled into v0.39 merely to make the implementation appear more complete.