# PaperClaw v0.27 Forgotten Debt / Product Foundation

> Status: implementation complete / acceptance complete  
> Stack base: `feat/v0.26-agent-message-bus @ d089719abebb7a1a66ffb31ba49be6245eb306ea`  
> Branch: `feat/v0.27-forgotten-debt-product-foundation`  
> Draft PR: `#56`  
> Validated implementation SHA: `0cc3e95ec211ba5b893d8e53248d341d56d360d8`

## 1. Purpose

v0.22-v0.26 added verification hardening, subprocess execution, a remote worker gateway, generation-fenced durable ownership and a durable Agent Message Bus foundation.

A combined code/product audit showed that several earlier capabilities existed independently but still lacked:

- a correct and fully bounded Message Bus public contract;
- a machine-readable source of truth for capability maturity;
- one safe project boundary joining instructions, local knowledge, Skills and Connector declarations;
- current documentation that distinguishes implemented, foundation-only, experimental and planned work.

The audit used:

1. the current repository and stacked Draft PRs;
2. the Agent / Multi-Agent / MCP / RAG interview knowledge base;
3. current Claude product patterns such as Projects, project knowledge/instructions, Skills, Connectors, Artifacts and reviewable remote coding tasks.

The goal is not to clone Claude. The goal is to repair correctness defects and establish product boundaries PaperClaw should have had before further feature growth.

## 2. Code-review findings and disposition

### D-001 — `AgentMessageBus` public export missing

**Finding:** `service.py` defined the façade, while package-level imports used by tests and callers did not export it.

**Disposition:** fixed. `AgentMessageBus` is exported from `paperclaw.message_bus` and covered by import/roundtrip tests.

### D-002 — frozen message contracts were not deeply immutable

**Finding:** frozen dataclasses still held caller-owned mutable mappings/lists. Mutation after validation could change envelope state, inject credential-shaped fields or desynchronize idempotency expectations.

**Disposition:** fixed.

- JSON objects are normalized at construction;
- mappings are detached and wrapped in `MappingProxyType`;
- arrays become tuples;
- canonical output explicitly thaws immutable values;
- frozen payload/header values can safely be reused as new validated inputs;
- non-string JSON object keys are rejected rather than silently coerced.

### D-003 — payload/header/draft byte bounds missing

**Finding:** v0.26 documented bounded messages but only checked JSON serializability.

**Disposition:** fixed with configurable limits checked before DB mutation:

- payload: 1 MiB default;
- headers: 64 KiB default;
- complete draft: 1.25 MiB default.

### D-004 — capacity rejection audit rolled back

**Finding:** the rejection event was written in the same transaction that raised `MessageBusCapacityError`; rollback removed the audit evidence.

**Disposition:** fixed. Capacity detection rolls back the publish transaction, then records `message.publish_rejected_capacity` in a distinct transaction before returning the public error.

### D-005 — README stopped at v0.08

**Finding:** product truth was materially stale compared with the v0.22-v0.26 development stack.

**Disposition:** fixed. README now explains the current stacked Draft line, maturity states, Project commands, capability discovery, limitations and deferred debt.

### D-006 — no machine-readable capability truth source

**Finding:** capability state had to be inferred from README, code, Plans and Handoffs.

**Disposition:** fixed with:

```text
CapabilityDescriptor
CapabilityCatalog
default_capability_catalog()
```

Catalog fields include:

- stable capability ID;
- introduced version;
- maturity: `shipped`, `foundation`, `experimental`, `planned`;
- supported surfaces;
- dependencies;
- explicit limitations.

CLI:

```bash
paperclaw capabilities
paperclaw capabilities --format json
paperclaw capabilities --status foundation
paperclaw capabilities --surface desktop
```

### D-007 — project-level boundary incomplete

**Finding:** project instructions, Memory, RAG, Skills and MCP existed as separate mechanisms without one project declaration.

**Disposition:** fixed at foundation level with `.paperclaw/project.json`.

Manifest v1 declares:

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

Safety rules:

- strict known fields;
- strict JSON arrays containing strings;
- bounded UTF-8 JSON;
- credential-shaped fields rejected;
- only workspace-relative paths;
- absolute paths and `..` rejected;
- external or broken symlinks rejected;
- manifest symlink explicitly rejected in both CLI load and runtime discovery.

CLI:

```bash
paperclaw project --workspace . init --name "My Project"
paperclaw project --workspace . show
paperclaw project --workspace . validate
paperclaw project --workspace . index
```

### D-008 — local RAG not bound to project knowledge lifecycle

**Finding:** v0.09.1 proved incremental BM25 and citations, but ordinary runtime composition did not consume a project knowledge declaration.

**Disposition:** fixed at deterministic local foundation level.

- supported knowledge files: UTF-8 `.md`, `.markdown`, `.txt`;
- deterministic recursive ordering;
- per-file path, byte length and SHA-256 metadata;
- aggregate source fingerprint;
- atomic SQLite index replacement;
- metadata written to `.paperclaw/data/project-index.json`;
- runtime registers `project.bm25_retrieval` only when the index fingerprint is current;
- missing/stale/invalid index is explicit and is not silently used;
- no implicit network call or background watcher.

### D-009 — newer capabilities not discoverable from product surfaces

**Finding:** Tasks, Plan Mode, Skills, LSP, subprocess, Remote Gateway, fenced queue and Message Bus had fragmented visibility.

**Disposition:** capability catalog and current README now provide the stable predecessor for later Desktop/Service management UI.

## 3. Interview-driven debt retained for later releases

The interview material expects the system to explain and measure:

- Tool discovery, schema validation and permission recheck;
- MCP lifecycle, reconnect and idempotency;
- RAG ingestion, hybrid retrieval, reranking, grounding and citations;
- short/session/long-term memory boundaries;
- orchestrated and choreographed Multi-Agent collaboration;
- task success, tool-call accuracy, collaboration efficiency, latency percentiles and Token/API cost.

v0.27 deliberately does not mislabel the following as complete.

### D-010 — first-class Artifact model

Needed:

- Artifact ID/type/version;
- immutable revisions;
- Run/Task/Trace source linkage;
- preview/edit/export metadata;
- optional publish/share policy.

### D-011 — Skills and Connector management surface

Needed:

- discover/list/enable/disable;
- source, trust and version metadata;
- MCP Auth/Permission state;
- per-project activation;
- Desktop UI and Service API.

The v0.27 manifest declares enabled IDs but does not yet perform full lifecycle management.

### D-012 — aggregate evaluation and observability

Needed:

- task success rate;
- tool-call accuracy;
- collaboration efficiency;
- P50/P95/P99 latency;
- Token/API cost;
- failure taxonomy across runs;
- exportable benchmark suites.

Current evaluation remains primarily per trace.

### D-013 — Message Bus runtime choreography

The durable Bus foundation is not automatically wired into Coordinator/Worker/Reviewer or durable Task execution.

Required first:

- stable consumer identity;
- delivery/retry semantics;
- poison-message and failure policy;
- correlation and causal trace linkage;
- explicit backpressure behavior in orchestration.

### D-014 — real external store/broker adapters

SQLite tests prove same-filesystem multi-process behavior only.

PostgreSQL, Redis, NATS or Kafka claims require real shared-service adapters and independent validation of:

- idempotency;
- ordering;
- lease/fencing;
- recovery;
- transport uncertainty;
- multi-host contention.

## 4. Claude-product comparison

The audit identified useful product boundaries rather than copying UI details:

- Projects demonstrate the value of one workspace containing instructions and scoped knowledge;
- Skills and Connectors demonstrate discoverable, configurable capability ecosystems;
- Artifacts demonstrate outputs as first-class editable/versioned objects separate from chat;
- remote coding tasks demonstrate long-running work that produces reviewable repository changes;
- scientific workflows emphasize reproducible, auditable outputs.

v0.27 implements only the prerequisite project/capability truth boundaries. Artifact UI, connector management, remote-task product UX and aggregate scientific/evaluation dashboards remain explicit debt.

## 5. Implemented architecture

```text
paperclaw.entrypoint
  ├─ legacy Agent / Team / TUI / Trace paths
  └─ product CLI routing
       ├─ capabilities
       └─ project init/show/validate/index

ProjectManifest
  ├─ instruction_files -> existing ProjectInstructionLoader
  ├─ knowledge_paths -> deterministic local index
  ├─ enabled_skills -> declaration only
  ├─ enabled_connectors -> declaration only
  └─ data_directory -> workspace-confined project data

build_memory_runtime()
  ├─ foundational Memory + project instructions
  └─ current project BM25 index -> Retrieval Context Source
```

Existing non-project workspaces remain backward compatible.

## 6. Acceptance evidence

Validated implementation SHA:

```text
0cc3e95ec211ba5b893d8e53248d341d56d360d8
```

GitHub Actions run:

```text
29659299612
```

Results:

- Ubuntu v0.27 focused acceptance: SUCCESS;
- Windows v0.27 focused acceptance: SUCCESS;
- Ubuntu/Windows Context and Retrieval compatibility: SUCCESS;
- Ubuntu/Windows v0.25-v0.26 regression slices: SUCCESS;
- focused Ruff: SUCCESS;
- full Windows `-m "not real_llm"` repository regression: SUCCESS;
- repository correctness Ruff: SUCCESS.

Machine-readable full regression:

```text
904 passed / 0 failed
10 marker-driven setup skips
artifact: v027-full-regression-29659299612
digest: sha256:ac01227611a90ff479194b5a83b3f6e77867f6ae98b22c0ae390f8775d17c44a
```

Focused artifacts:

```text
Linux digest:  sha256:e2007a230b095268c6f8117306f171b268aa4c3cf5c454c5def23a31bfd7b0e8
Windows digest: sha256:23b875c4c0c18cd25036fc011777466c29cd9634b0c84b6df1bf6839a5aba52a
```

## 7. Preserved negative evidence

Development surfaced and fixed:

1. the initial catalog helper treated a scalar limitation string as an iterable of characters; a machine-readable focused report isolated the single failing test, and scalar/iterable normalization was corrected;
2. the first workflow referenced brittle explicit compatibility test paths; it was replaced with stable keyword-based selection and focused report artifacts;
3. a frozen Message Bus payload initially could not safely be reused as another message input; normalization now thaws before canonical JSON validation;
4. Python non-string mapping keys could be silently converted by JSON; raw keys are now recursively required to be strings;
5. manifest discovery initially treated a symlink manifest as absent while direct load rejected it; discovery now surfaces the same explicit policy error;
6. manifest JSON array fields initially risked string-to-character coercion; arrays are now strictly typed.

No tests were skipped or assertions weakened to hide these findings.

## 8. Non-goals preserved

- no Desktop redesign;
- no Artifact editor/share implementation;
- no OAuth connector directory;
- no vector embedding, Hybrid Search or reranker;
- no automatic filesystem watcher;
- no Coordinator choreography rewrite;
- no external distributed broker/store claim;
- no automatic merge of stacked PRs.

## 9. Follow-on development plan

```text
v0.28 Project Knowledge Runtime + lifecycle
  -> hybrid/vector retrieval adapter
  -> stale-index policy and watcher
  -> project-scoped memory isolation

v0.29 Artifact model
  -> revisions / source linkage / preview / export

v0.30 Desktop product integration
  -> capabilities / projects / skills / connectors

v0.31 Aggregate Eval / Cost / Latency
  -> multi-run metrics and benchmark suites

later external infrastructure line
  -> real PostgreSQL/Redis/NATS/Kafka adapters with service evidence
```

## 10. Final classification

**COMPLETE / DRAFT PR READY FOR OWNER REVIEW**

PR #56 remains Draft and unmerged.
