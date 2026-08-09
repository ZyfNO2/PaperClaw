# PaperClaw v0.40 — First-Class Sandbox Execution Boundary SPEC / SOP

## 1. Objective

Introduce an explicit execution isolation contract for agent-generated commands while preserving PaperClaw's existing `BashTool` timeout, cancellation, output bounding and process-tree cleanup semantics.

The first isolated backend is Docker. This release does not claim VM-grade isolation.

## 2. Problem statement

Current `BashTool` provides a useful host-process safety layer, including command validation, a small environment allowlist, workspace cwd, bounded timeout/output and process-tree cleanup. However, process policy is not equivalent to filesystem/network/resource isolation.

The runtime needs a clear seam:

```text
Tool request
 -> authorization/policy
 -> SandboxManager
 -> SandboxBackend
      -> LocalProcessBackend (compatibility)
      -> DockerBackend (isolated)
 -> bounded SandboxResult
 -> ToolResult / Trace / Audit
```

## 3. Existing implementation to inspect first

Before coding, inspect at minimum:

- `src/paperclaw/tools/bash.py`;
- `src/paperclaw/tools/base.py`;
- `src/paperclaw/tools/registry.py`;
- scoped/cancellable multi-agent tool wrappers;
- project extension permissions and call-time recheck;
- process cancellation registry;
- trace/audit event conventions;
- workspace/path authorization helpers;
- current CI OS matrix.

Do not fork `BashTool` into unrelated implementations with divergent cancellation semantics.

## 4. Required public contracts

### 4.1 SandboxBackend

Define a narrow interface equivalent to:

```text
prepare(spec, context) -> SandboxSession
execute(session, command_spec) -> SandboxResult
collect_artifacts(session, rules) -> ArtifactManifest
close(session) -> None
```

Exact Python API may follow repository conventions.

### 4.2 SandboxSpec

Minimum policy fields:

```text
backend
workspace
workspace_mode: read_only | read_write
working_directory
network_mode: none | allowlist | host_compatible
allowed_hosts[]
wall_timeout_seconds
cpu_limit
memory_limit_bytes
pid_limit
env_allowlist[]
output_limit_bytes
artifact_export_rules
```

Unsupported policy MUST fail closed rather than silently becoming broader.

### 4.3 SandboxResult

Return a typed result with at least:

```text
status
exit_code | null
stdout
stderr
started_at
finished_at
duration_ms
timed_out
cancelled
output_truncated
backend
sandbox/session id
resource/policy summary
cleanup_status
```

Do not expose secrets or Docker daemon internals unnecessarily.

## 5. Backends

### 5.1 LocalProcessBackend

Purpose: preserve current behavior and enable environments without Docker.

Requirements:

- reuse existing portable shell/process lifecycle logic;
- preserve timeout, cancellation and process-tree cleanup;
- preserve environment filtering;
- report `isolation_level=host_process` or equivalent;
- never market this backend as a sandbox.

### 5.2 DockerBackend

Required minimum isolation:

- create an ephemeral container per bounded session or execution according to the simplest safe current architecture;
- read-only container root filesystem where feasible;
- workspace mounted only at the authorized path;
- explicit read-only/read-write workspace mode;
- no privileged mode;
- no host PID namespace;
- no Docker socket mount into the container;
- bounded memory;
- bounded CPU;
- bounded PIDs;
- wall timeout enforced by host runtime;
- deterministic process/container cleanup on success, failure, timeout and cancellation;
- environment constructed from explicit allowlist only;
- default network policy is `none` for coding/test workloads unless a task policy explicitly enables access;
- artifact export is restricted to authorized workspace-relative paths.

If Docker cannot express an `allowlist` network policy without additional infrastructure, fail that policy as unsupported in v0.40; do not silently map it to unrestricted network access.

## 6. Integration with Tool Runtime

The existing tool authorization path remains authoritative.

Expected flow:

```text
ToolRegistry / project permission
 -> BashTool validation
 -> Sandbox policy selection
 -> execute
 -> bounded/redacted ToolResult
 -> existing invocation/Trace audit
```

A sandbox backend must not bypass project path/tool permissions.

The same cancellation token used by current runtime must propagate to sandbox execution.

## 7. Configuration

Provide an explicit configuration surface, e.g. conceptually:

```text
sandbox.backend = local | docker
sandbox.network = none
sandbox.memory_mb = ...
sandbox.cpus = ...
sandbox.pids = ...
```

Default choice must prioritize backward compatibility for existing users unless the repository already has a safe migration mechanism. The CLI/diagnostics must make the selected backend visible.

Do not auto-fallback from requested `docker` to `local` after Docker startup failure; return a typed unavailable/blocked result. Silent fallback would violate the isolation contract.

## 8. Threat/negative tests required

Automated acceptance must attempt at least:

1. workspace escape/read outside authorized mount;
2. write outside allowed workspace;
3. fork/PID exhaustion attempt;
4. memory pressure above configured bound;
5. long-running process timeout;
6. child process survival after timeout/cancel;
7. network access when `network=none`;
8. environment secret discovery attempt;
9. artifact export with traversal path;
10. container cleanup after failed command.

Platform/environment limitations must be reported honestly. Do not claim a Docker negative test passed if Docker is unavailable and the test was skipped.

## 9. Normal workload acceptance

At least one realistic coding loop must succeed in Docker:

```text
read/write authorized workspace file
 -> run targeted pytest or equivalent command
 -> collect bounded output
 -> export a declared artifact/log
```

It must not require the container to receive host credentials.

## 10. Trace / audit

Record bounded execution facts using existing Trace/audit paths:

```text
sandbox.execution.started
sandbox.execution.completed
sandbox.execution.denied
sandbox.execution.timeout
sandbox.execution.cancelled
sandbox.cleanup.failed
```

Metadata should include backend, policy fingerprint, duration, status, byte counts and cleanup outcome. Do not persist full secrets or unbounded command output in audit metadata.

## 11. Tests and CI

### Unit

- spec validation;
- unsupported policy fails closed;
- local backend preserves existing BashTool behavior;
- cancellation propagation;
- result normalization;
- artifact path validation;
- no silent Docker->local fallback.

### Integration

- Docker normal workload;
- negative isolation cases listed above;
- timeout/process cleanup;
- trace event projection.

### CI

Add a dedicated Linux Docker job if current hosted runner supports Docker. Keep non-Docker unit tests cross-platform. Docker-required tests must use an explicit marker such as `sandbox_docker` rather than pretending to run on unsupported environments.

## 12. Acceptance gates

- [ ] existing local shell tests remain green;
- [ ] `SandboxBackend` is the single execution seam for newly integrated shell execution;
- [ ] Docker backend enforces workspace mount mode, memory/CPU/PID and network-none policy;
- [ ] timeout/cancel leaves no known child/container process alive;
- [ ] unsupported isolation policy fails closed;
- [ ] Docker unavailability does not silently execute on host;
- [ ] negative tests have real Docker evidence when marked passed;
- [ ] normal coding/test workload succeeds in Docker;
- [ ] focused tests and full non-live regression pass;
- [ ] exact-head CI evidence and Handoff are recorded.

## 13. Non-goals

- Firecracker/gVisor/Kata/VM backend;
- production multi-tenant hostile-code guarantee;
- Kubernetes orchestration;
- hosted image registry management;
- unrestricted internet access;
- package installation by default;
- replacing extension permission/audit systems.

## 14. Required implementation SOP

1. Inspect current execution, cancellation, authorization and trace seams.
2. Branch from current `main`; do not implement against stale v0.40 assumptions.
3. Extract/reuse existing process lifecycle into the smallest backend-neutral seam without changing legacy behavior.
4. Add contract/spec/result tests.
5. Implement LocalProcessBackend and prove parity.
6. Implement DockerBackend with fail-closed policy validation.
7. Wire BashTool through the sandbox seam while preserving authorization and ToolResult compatibility.
8. Add Docker threat tests and a normal workload integration test.
9. Add diagnostics/configuration and trace metadata.
10. Run focused tests, Docker integration, full non-live regression, lint/type/build gates used by repository.
11. Record skipped/unavailable Docker evidence separately from passed evidence.
12. Finish `artifacts/v0_40/HANDOFF.md` and final commit(s).

## 15. Safe interview claim boundary

Safe after real Docker acceptance:

> PaperClaw routes agent-generated shell execution through a selectable sandbox backend. The Docker backend applies bounded filesystem, process, resource, environment and default network isolation, propagates cancellation/timeout, exports only authorized artifacts, and emits auditable execution metadata; legacy host-process execution remains explicit and is not represented as isolated.

Do not claim VM-grade or production multi-tenant isolation.
