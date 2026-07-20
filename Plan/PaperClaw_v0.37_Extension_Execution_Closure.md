# PaperClaw v0.37 — Project Extension Execution Closure

## Objective

Advance the v0.36 project extension foundation from declarative registration and bounded activation to a complete, host-controlled Connector Tool execution lifecycle.

## Execution closure

```text
project descriptor
  -> activation
  -> frozen Tool schema
  -> ToolRegistry registration
  -> invocation-time policy recheck
  -> host runtime call
  -> bounded and redacted result
  -> content-free invocation audit
```

## Required behavior

- Stable NodeRegistry-safe Tool names bind exact extension and remote Tool identities.
- Unsupported schemas, non-executable runtimes and registry collisions fail before ToolRegistry mutation.
- Every call rechecks registration, enabled state, descriptor identity, trust and effective permissions.
- Host credential references are resolved only at invocation time and are not persisted in audit rows.
- Arguments and results are bounded JSON values.
- Timeout and cooperative cancellation close the affected runtime.
- Invocation audit stores only identity, status, duration, byte counts and schema hash.

## Runtime boundary

An executable Connector runtime implements:

```python
def call_tool(name, arguments, context) -> ConnectorCallResult: ...
```

PaperClaw owns validation, policy rechecks, timeout/cancellation observation, result normalization and audit. The host owns transport behavior and should make `close()` interrupt or invalidate outstanding I/O where possible.

## Acceptance

- Existing v0.36 extension tests remain green.
- Success, denial, timeout, cancellation and redaction paths have focused tests.
- Linux and Windows focused suites pass.
- Full non-live regression, correctness lint and package smoke pass.

## Explicit non-goals

- arbitrary Python or import-path extension loading;
- project-owned executable modules;
- hosted browser credential flows;
- extension marketplace or Desktop installation UI;
- provisioning a specific remote transport;
- forcibly killing arbitrary host threads after timeout.
