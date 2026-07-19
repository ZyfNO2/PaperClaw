# PaperClaw v0.27 Forgotten Debt / Product Foundation — Handoff

## Status

**COMPLETE / DRAFT PR READY FOR OWNER REVIEW**

- Repository: `ZyfNO2/PaperClaw`
- Stack base: `feat/v0.26-agent-message-bus @ d089719abebb7a1a66ffb31ba49be6245eb306ea`
- Branch: `feat/v0.27-forgotten-debt-product-foundation`
- Draft PR: `#56`
- Exact validated implementation SHA: `0cc3e95ec211ba5b893d8e53248d341d56d360d8`
- Validation run: `29659299612`
- Plan: `Plan/PaperClaw_v0.27_Forgotten_Debt_Product_Foundation.md`

## Audit inputs

This line was produced from a combined review of:

1. current repository code and stacked PRs #51-#55;
2. the Agent / Multi-Agent / MCP / RAG interview knowledge base;
3. current Claude product patterns around Projects, project knowledge/instructions, Skills, Connectors, Artifacts, reviewable coding tasks and auditable scientific workflows.

The comparison was used to identify missing product boundaries. It was not used to claim feature parity.

## Correctness debt fixed

### Message Bus public API

`AgentMessageBus` is now exported from `paperclaw.message_bus` and covered by Agent-facing send/receive/ack tests.

### Deep immutable message values

`MessageDraft`, `MessageEnvelope` and durable event metadata now normalize and detach JSON input.

- nested mappings become immutable mapping proxies;
- arrays become tuples;
- original caller dict/list mutation cannot alter the validated message;
- canonical serialization explicitly thaws immutable values;
- frozen values may safely be reused as later message inputs;
- non-string JSON object keys are rejected;
- credential-shaped nested fields cannot be injected after construction.

### Message size bounds

Defaults:

```text
payload <= 1 MiB
headers <= 64 KiB
complete draft <= 1.25 MiB
```

Bounds are checked before durable message insertion.

### Durable capacity-rejection audit

Topic-capacity rejection no longer writes its audit event in the rolled-back publish transaction.

The final flow is:

```text
publish transaction detects capacity
  -> rollback / release writer lock
  -> independent audit transaction
  -> MessageBusCapacityError
```

An exact idempotent retry at capacity can still return the existing message.

## Capability Catalog delivered

Public contracts:

```text
CapabilityDescriptor
CapabilityCatalog
default_capability_catalog()
```

Maturity values:

```text
shipped
foundation
experimental
planned
```

Supported surface labels:

```text
library
cli
tui
desktop
service
```

CLI:

```bash
paperclaw capabilities
paperclaw capabilities --format json
paperclaw capabilities --status foundation
paperclaw capabilities --surface desktop
```

The catalog records limitations such as:

- Remote Gateway idempotency being process-lifetime only;
- SQLite fencing being same-filesystem evidence only;
- Message Bus not yet wired into Coordinator choreography;
- Artifact revisions and aggregate evaluation remaining planned.

## Project Workspace delivered

Manifest:

```text
.paperclaw/project.json
```

Schema v1 fields:

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

CLI:

```bash
paperclaw project --workspace . init --name "My Project"
paperclaw project --workspace . show
paperclaw project --workspace . validate
paperclaw project --workspace . index
```

### Manifest policy

- strict known fields;
- strict arrays containing strings;
- bounded UTF-8 JSON;
- credential-shaped fields rejected;
- workspace-relative paths only;
- absolute and parent traversal paths rejected;
- external/broken symlinks rejected;
- symlink manifest rejected consistently by direct load and runtime discovery;
- atomic save.

### Project instructions

The manifest reuses the existing `ProjectInstructionLoader`; it does not create a competing instruction mechanism.

Declared instruction files feed the existing foundational Context source.

### Project knowledge

Supported source files:

```text
.md
.markdown
.txt
```

The index pipeline:

```text
manifest knowledge_paths
  -> deterministic file collection
  -> UTF-8 and byte-bound validation
  -> existing IncrementalIndexer
  -> temporary SQLite index
  -> WAL checkpoint
  -> atomic database replacement
  -> per-file SHA-256 metadata
  -> aggregate source fingerprint
```

Runtime registers `project.bm25_retrieval` only when the stored fingerprint matches current project knowledge.

Missing, stale, invalid or mismatched metadata never becomes implicit trusted Context.

## Documentation truth fixed

The root README no longer stops at v0.08. It now records:

- stacked Draft status;
- capability maturity semantics;
- project/capability commands;
- Message Bus hardening;
- distributed-system limitations;
- explicit deferred debt.

## Deferred debt

### Artifact model

Still required:

- Artifact identity and type;
- immutable revisions;
- Run/Task/Trace source linkage;
- preview/edit/export metadata;
- sharing/publication policy.

### Skills / Connector management

Still required:

- discovery, enable/disable and versions;
- trust/source metadata;
- MCP auth and permission state;
- project activation;
- Desktop and Service management surfaces.

The manifest currently declares IDs only.

### Aggregate evaluation

Still required:

- task success;
- tool-call accuracy;
- collaboration efficiency;
- latency P50/P95/P99;
- Token/API cost;
- multi-run failure taxonomy;
- benchmark suites.

### Runtime Message Bus choreography

Still required:

- consumer identity;
- delivery/retry policy;
- poison-message handling;
- correlation and causal trace linkage;
- orchestration backpressure semantics.

### External shared infrastructure

No PostgreSQL, Redis, NATS or Kafka support is claimed. A later adapter must be validated against a real shared service.

## Validation

Exact implementation SHA:

```text
0cc3e95ec211ba5b893d8e53248d341d56d360d8
```

GitHub Actions run:

```text
29659299612
```

Results:

- Ubuntu focused acceptance — SUCCESS
- Windows focused acceptance — SUCCESS
- Context / Memory / Retrieval compatibility on both platforms — SUCCESS
- v0.25-v0.26 regression slices on both platforms — SUCCESS
- focused Ruff — SUCCESS
- full Windows non-live repository regression — SUCCESS
- repository correctness Ruff — SUCCESS

Machine-readable full regression:

```text
904 passed / 0 failed
10 marker-driven setup skips
artifact: v027-full-regression-29659299612
digest: sha256:ac01227611a90ff479194b5a83b3f6e77867f6ae98b22c0ae390f8775d17c44a
```

Focused evidence:

```text
Linux artifact digest:
sha256:e2007a230b095268c6f8117306f171b268aa4c3cf5c454c5def23a31bfd7b0e8

Windows artifact digest:
sha256:23b875c4c0c18cd25036fc011777466c29cd9634b0c84b6df1bf6839a5aba52a
```

## Preserved negative evidence

1. Capability metadata helper iterated a scalar limitation by character; focused report isolated the single failure and scalar normalization was fixed.
2. Initial workflow used brittle explicit compatibility paths; stable keyword selection and focused report artifacts replaced it.
3. Frozen message data initially could not be reused as another validated message; normalization now thaws immutable values.
4. Python mapping keys could be silently coerced by JSON; recursive string-key validation was added.
5. Manifest array fields could accept string-like iterables; strict array validation was added.
6. Manifest discovery could silently ignore a symlink configuration; it now surfaces an explicit policy error.

No product assertion was weakened to make CI pass.

## Main files

```text
src/paperclaw/message_bus/contracts.py
src/paperclaw/message_bus/store.py
src/paperclaw/message_bus/__init__.py
src/paperclaw/capabilities/catalog.py
src/paperclaw/projects/manifest.py
src/paperclaw/projects/indexing.py
src/paperclaw/memory/runtime.py
src/paperclaw/product_cli.py
src/paperclaw/entrypoint.py
README.md
tests/unit/message_bus/
tests/unit/capabilities/
tests/unit/projects/
tests/unit/test_product_cli.py
.github/workflows/v027-forgotten-debt-product-foundation.yml
```

## Recommended next sequence

```text
v0.28 Project Knowledge Runtime + lifecycle
  -> Hybrid/vector retrieval
  -> stale-index policy and watcher
  -> project-scoped memory isolation

v0.29 Artifact revisions / source linkage / preview / export

v0.30 Desktop capabilities / projects / skills / connectors

v0.31 Aggregate evaluation / cost / latency dashboard
```

## Final classification

**COMPLETE**

PR #56 remains Draft and unmerged. No stacked PR was merged or deleted.
