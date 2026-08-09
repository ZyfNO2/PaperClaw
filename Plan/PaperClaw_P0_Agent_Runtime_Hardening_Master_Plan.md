# PaperClaw P0 — Agent Runtime Interview Hardening Master Plan

## Status

Planning branch: `plan/p0-agent-runtime-hardening`
Base: `main @ 5891d87ec2a68f434fe8f728ba9be0999932c325`

This plan defines the next three P0 increments for PaperClaw. The goal is not to add more horizontal Agent features. The goal is to turn existing runtime capabilities into one interview-grade, falsifiable system story:

```text
User / Task
  -> durable Session/Event state
  -> Context Builder
       -> user/project memory
       -> evidence/artifacts
       -> compacted transcript
       -> token policy
  -> Model
  -> Tool Runtime
       -> first-class Sandbox execution boundary
  -> durable Trace
  -> Replay / Fault Injection / Eval
  -> Resume after interruption
```

## Repository facts this plan must preserve

PaperClaw already contains substantial foundations and they MUST be reused rather than replaced:

- v0.17: bounded file-backed long memory, frozen prompt snapshots, runtime history compaction and context/memory tests;
- current memory implementation: `src/paperclaw/memory/store.py`;
- current compaction seam: `src/paperclaw/context/runtime_compaction.py` and `tests/unit/context/test_runtime_history_compaction.py`;
- current shell/process lifecycle: `src/paperclaw/tools/bash.py`, including timeout, cancellation, portable process-tree cleanup and bounded output;
- v0.31+: durable Trace, aggregate latency/token/cost/failure evaluation and provider-capable team execution;
- v0.33/v0.34+: retry, DLQ, outbox, cancellation and distributed runtime foundations;
- v0.37+: project extension permission ceiling, call-time policy recheck and invocation audit.

No P0 increment may create a parallel memory store, parallel tool registry, parallel trace system, parallel task state machine or duplicate multi-agent scheduler unless repository inspection proves the existing seam cannot satisfy the requirement.

## P0 release sequence

### P0.1 — v0.39 Durable Memory, Context Snapshot & Resume

Primary outcome: one model call can be explained and reconstructed from durable facts.

Required capabilities:

- durable session/event model with strict ordering and idempotent append;
- memory provenance and source linkage;
- memory conflict/supersession decisions;
- deterministic Context Builder with explicit token budget and priority policy;
- tool-call/tool-result pairing protection during compaction;
- durable context snapshot before model invocation;
- crash/restart reconstruction and bounded resume;
- CLI or equivalent operator surface to inspect/replay a session.

Detailed contract: `Plan/PaperClaw_v0.39_Durable_Memory_Context_Resume_SPEC_SOP.md`.

### P0.2 — v0.40 First-Class Sandbox Execution Boundary

Primary outcome: untrusted/agent-generated commands execute behind one explicit isolation contract instead of being synonymous with host process execution.

Required capabilities:

- `SandboxBackend` abstraction;
- existing host/local process behavior preserved as an explicit backend;
- Docker backend as the first isolated implementation;
- workspace mount policy, environment filtering, timeout, memory/CPU/PID limits and process cleanup;
- explicit network policy;
- bounded stdout/stderr and artifact export;
- typed execution result and durable trace/audit metadata;
- safe fallback behavior when Docker is unavailable.

Detailed contract: `Plan/PaperClaw_v0.40_Sandbox_Execution_SPEC_SOP.md`.

### P0.3 — v0.41 Agent Runtime Eval, Replay & Fault Injection Harness

Primary outcome: runtime design claims are measured by repeatable benchmark cases instead of feature existence.

Required capabilities:

- versioned benchmark case schema;
- deterministic/offline execution path;
- trace replay without re-running external side effects;
- fault injection at model/tool/context/memory/sandbox/runtime boundaries;
- ablation runner for context and memory policies;
- task success, tool success/failure, recovery, step, token, latency and cost metrics;
- regression thresholds suitable for CI;
- opt-in live-provider acceptance clearly separated from offline evidence.

Detailed contract: `Plan/PaperClaw_v0.41_Agent_Runtime_Eval_Harness_SPEC_SOP.md`.

## Cross-cutting architecture rules

1. **Preserve old paths by default.** A feature flag or backend selection must allow legacy behavior where practical.
2. **Durable facts before derived projections.** Events, source links and execution results are authoritative; summaries, snapshots and aggregate metrics are projections.
3. **Idempotency is explicit.** Retried appends, replay, resume and tool execution must have documented duplicate behavior.
4. **No fake E2E claims.** Fake models, mocks and deterministic fixtures prove control flow only. Real provider, Docker isolation and OS-specific acceptance are reported separately.
5. **No hidden truncation.** Context/memory/output truncation must expose counts, hashes or locators sufficient for audit.
6. **No silent privilege escalation.** Sandbox and extension permissions may become stricter, never broader, during retry/resume.
7. **No side-effect replay by default.** Replay reads recorded results unless an operator explicitly selects a re-execution mode.
8. **One trace vocabulary.** New events extend the existing trace/event model rather than creating a second observability system.

## Dependency order

```text
v0.39 Memory/Context/Resume
       |
       +----> v0.41 Eval can benchmark context and resume
       |
v0.40 Sandbox
       |
       +----> v0.41 Eval can inject sandbox/tool failures
```

v0.39 and v0.40 may be implemented on separate branches after both have inspected current `main`; v0.41 should be rebased/implemented after their stable contracts exist.

## Hard completion gate for the P0 program

The P0 program is complete only when all three increments have:

- focused unit/integration tests;
- full non-live regression;
- correctness lint/type/build gates already used by the repository where applicable;
- exact-commit CI evidence;
- explicit `verified / pending / blocked` boundaries;
- implementation Handoff under `artifacts/`;
- no unresolved BLOCKER/HIGH review finding;
- an interview demo path showing: context construction -> tool sandbox -> trace -> failure/recovery -> eval report.

## Program non-goals

- more Agent roles or another scheduler;
- another vector database;
- provider proliferation;
- Kubernetes or hosted multi-tenant control plane;
- a marketplace;
- production-grade VM isolation beyond the Docker backend in this P0;
- automatic memory extraction whose quality cannot be evaluated;
- exactly-once external side effects.

## Safe interview claim after completion

> PaperClaw implements a durable Agent Runtime that reconstructs context from ordered state and provenance-linked memory, executes agent-generated commands behind a selectable sandbox boundary, persists model/tool/runtime evidence, survives bounded interruption through replay/resume, and evaluates runtime policies through deterministic benchmarks, fault injection and ablation with latency/token/cost/recovery metrics.

Do not claim production-scale multi-tenant isolation, exactly-once side effects, or scientific superiority unless separate evidence exists.
