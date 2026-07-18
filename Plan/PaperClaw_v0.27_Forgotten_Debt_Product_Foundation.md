# PaperClaw v0.27 Forgotten Debt / Product Foundation

> Status: implementation in progress  
> Stack base: `feat/v0.26-agent-message-bus @ d089719abebb7a1a66ffb31ba49be6245eb306ea`  
> Branch: `feat/v0.27-forgotten-debt-product-foundation`

## 1. Why this release exists

v0.22-v0.26 added verification hardening, subprocess execution, remote gateway, fenced durable ownership and a durable message-bus foundation. A code/product audit shows that several earlier promises are now individually implemented but still lack one coherent product boundary.

The audit used three evidence sets:

1. current code and stacked PRs #51-#55;
2. the interview knowledge base covering Tool Calling, MCP, RAG, Memory, Multi-Agent coordination, evaluation, cost and latency;
3. current Claude product patterns such as Projects, project knowledge/instructions, Skills, Connectors, Artifacts and remote coding tasks.

The goal is not to copy Claude. The goal is to fix correctness defects and add the missing truth/project boundary that PaperClaw should already have had before more feature growth.

## 2. Code-review findings

### P0 correctness defects

#### D-001 `AgentMessageBus` public export missing

`service.py` defines `AgentMessageBus`, and tests import it from `paperclaw.message_bus`, but `message_bus/__init__.py` does not export it.

Impact:

- import-time failure;
- façade tests cannot collect;
- documented Agent-facing API is not actually public.

#### D-002 frozen message contracts are not deeply immutable

`MessageDraft` and `MessageEnvelope` are frozen dataclasses, but `payload` and `headers` are caller-owned mutable mappings.

A caller can mutate nested data after validation/digest calculation, causing:

- idempotency digest drift;
- secret-shaped data appearing after validation;
- envelope state changing after publication.

#### D-003 payload/header byte limits are missing

The v0.26 plan says payload and headers are bounded, but the implementation only verifies JSON serializability.

Impact:

- unbounded SQLite row/event growth;
- memory/CPU pressure during canonical serialization;
- mismatch between documentation and implementation.

#### D-004 capacity-rejection audit is rolled back

`message.publish_rejected_capacity` is inserted inside the same transaction that raises `MessageBusCapacityError`. The exception rolls back the audit event.

Impact:

- rejection is not durably auditable;
- operational evidence contradicts the documented contract.

#### D-005 stale documentation is a product correctness defect

The root README still describes the repository as complete only through v0.08 even though the current stacked implementation reaches v0.26.

Impact:

- users and interview notes cannot distinguish shipped, foundation-only and deferred capabilities;
- future agents may plan against obsolete constraints;
- release evidence is fragmented across Plan/Handoff files.

## 3. Interview-driven missing boundaries

The interview material repeatedly expects an Agent system to explain and demonstrate:

- Tool discovery/schema validation/permission recheck;
- MCP lifecycle and reconnect/idempotency;
- context compression and project instructions;
- RAG ingestion, hybrid retrieval, grounding and citation quality;
- short/session/long-term memory;
- orchestrated and choreographed Multi-Agent collaboration;
- task success, tool-call accuracy, collaboration efficiency, latency P50/P99 and token/API cost.

PaperClaw already contains many foundations, but the following integration debt remains:

### D-006 capabilities have no machine-readable source of truth

Feature state is currently inferred from README, Plan files, Handoffs and code paths.

Needed:

- stable capability IDs;
- version introduced;
- maturity (`shipped`, `foundation`, `experimental`, `planned`);
- supported surfaces (`library`, `cli`, `tui`, `desktop`, `service`);
- dependencies and explicit limitations;
- JSON/text output for doctor/UI/interview evidence.

### D-007 project-level boundary is incomplete

Existing `ProjectInstructionLoader` already loads `PAPERCLAW.md`, `CLAUDE.md` and `AGENTS.md`, and long memory is integrated into Context assembly. However there is no explicit project manifest that declares:

- project identity/name;
- instruction files;
- knowledge paths;
- enabled Skills;
- enabled Connectors/MCP servers;
- project-local data/cache paths;
- validation status.

Without this, RAG, Skills, MCP and Memory remain separate mechanisms rather than one project workspace.

### D-008 Local RAG is not a default project knowledge path

v0.09.1 proves incremental BM25 and grounded citations, but normal runtime composition does not automatically bind a project knowledge declaration to a retrieval source.

This release will establish the manifest and deterministic index command. Automatic live reindexing remains deferred until lifecycle/close semantics are explicit.

### D-009 newer runtime capabilities are not discoverable from product surfaces

Tasks, Plan Mode, Skills, LSP, subprocess execution, Remote Gateway, fenced queue and Message Bus are largely library/CLI foundations. Desktop/provider UX does not expose a unified capability/availability view.

A machine-readable catalog is the required predecessor to Desktop settings/Inspector work.

## 4. Claude-product comparison and deferred product debt

Current Claude patterns highlight product expectations that PaperClaw does not yet implement end-to-end:

- Projects: isolated workspace, instructions, knowledge and scoped memory;
- Skills/Connectors: discoverable, configurable capability ecosystem;
- Artifacts: first-class editable/versioned output separate from chat;
- interactive connector views;
- remote coding tasks that continue and create reviewable PRs;
- auditable scientific artifacts with reproducible code/history.

Deferred after v0.27:

### D-010 first-class Artifact model

Needed later:

- artifact ID/type/version;
- source run/task/trace linkage;
- immutable revisions;
- file/export metadata;
- preview/edit boundary;
- optional publish/share policy.

### D-011 Skills and Connector management surface

Needed later:

- list/enable/disable;
- trust/source/version metadata;
- MCP auth/permission state;
- per-project selection;
- Desktop UI and Service API.

### D-012 aggregate evaluation and observability dashboard

Existing per-trace eval is insufficient for interview/production claims.

Needed later:

- task success/tool accuracy;
- collaboration efficiency;
- latency P50/P95/P99;
- token/API cost;
- failure taxonomy over multiple runs;
- exportable benchmark suites.

### D-013 Message Bus runtime wiring

The bus exists as a durable foundation but is not yet wired into Coordinator/Worker/Reviewer or Task runtime choreography.

This must wait until delivery semantics, consumer identity and failure policy are defined. v0.27 will not silently change Multi-Agent behavior.

### D-014 external shared store/broker adapters

SQLite multi-process evidence is not a multi-host claim. PostgreSQL/Redis/NATS/Kafka adapters require real-service validation.

## 5. v0.27 implementation scope

### Phase A — Message Bus correctness hardening

- export `AgentMessageBus` publicly;
- canonical deep copy/freeze payload and headers;
- add configurable payload/header/envelope byte limits;
- ensure canonical digest uses normalized immutable data;
- persist capacity rejection audit outside the rolled-back publish transaction;
- remove unused imports and run focused lint;
- add mutation, oversize and durable-audit regressions.

### Phase B — Capability Catalog

Add:

```text
paperclaw.capabilities
  CapabilityDescriptor
  CapabilityCatalog
  default_capability_catalog()
```

CLI:

```text
paperclaw capabilities
paperclaw capabilities --format json
paperclaw capabilities --status shipped
paperclaw capabilities --surface desktop
```

Catalog rules:

- explicit maturity and limitations;
- no capability inferred as available merely because a Plan exists;
- no secret/config values in output;
- deterministic ordering and JSON schema version.

### Phase C — Project Workspace manifest

Add `.paperclaw/project.json` contract and CLI:

```text
paperclaw project init --name <name>
paperclaw project show
paperclaw project validate
paperclaw project index
```

Manifest v1:

```text
schema_version
project_id
name
instruction_files
knowledge_paths
enabled_skills
enabled_connectors
data_directory
```

Safety:

- manifest and declared paths stay inside workspace;
- no credential-shaped fields;
- bounded JSON size;
- deterministic normalization;
- symlink/path traversal rejected;
- project index only accepts supported text/Markdown files and uses existing incremental BM25 store.

Runtime integration:

- `build_memory_runtime()` discovers a manifest when present;
- manifest instruction files feed the existing `ProjectInstructionLoader`;
- an existing validated project RAG index may be registered as a Context source;
- no implicit network calls;
- no background watcher in this release.

### Phase D — truth/documentation sync

- update README capability/version overview through v0.27;
- add debt matrix and explicit deferred list;
- add Handoff with exact SHA/run/test artifact;
- keep PR Draft and unmerged.

## 6. Acceptance matrix

### Message Bus

- `from paperclaw.message_bus import AgentMessageBus` works;
- caller mutation cannot change validated draft/envelope;
- nested mutation is blocked/detached;
- credential-shaped fields cannot be injected after construction;
- oversize payload/header/envelope rejected before DB write;
- capacity rejection leaves a durable audit event;
- idempotent retry still works at capacity.

### Capability Catalog

- stable deterministic catalog;
- shipped/foundation/experimental/planned distinguished;
- surface/status filters correct;
- JSON/text CLI output;
- README generated/validated against catalog version table where practical.

### Projects

- safe init/show/validate;
- existing non-project workspace remains backward compatible;
- instruction file selection affects Context snapshot;
- path traversal and external symlink rejected;
- deterministic project BM25 index;
- runtime can use a prebuilt valid index;
- missing/stale index is explicit, not silently treated as current.

### Regression

- Linux and Windows focused tests;
- v0.26 Message Bus regression;
- memory/context/retrieval regression;
- CLI regression;
- full Windows non-live repository regression;
- Ruff high-signal correctness checks.

## 7. Non-goals

- no Desktop redesign in this PR;
- no Artifact editor/share implementation;
- no OAuth connector directory;
- no vector embedding/reranker;
- no automatic filesystem watcher;
- no Coordinator choreography rewrite;
- no external distributed broker/store claim;
- no merge of stacked PRs.

## 8. Planned follow-on

```text
v0.28 Project Knowledge Runtime + lifecycle
  -> hybrid/vector retrieval adapter
  -> stale-index policy and watcher
  -> project-scoped memory isolation

v0.29 Artifact model + revision/export/preview

v0.30 Desktop capability/project/skill/connector management

v0.31 Aggregate Eval / Cost / Latency dashboard
```
