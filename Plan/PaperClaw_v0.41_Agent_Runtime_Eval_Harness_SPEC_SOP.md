# PaperClaw v0.41 — Agent Runtime Eval, Replay & Fault Injection Harness SPEC / SOP

## 1. Objective

Extend PaperClaw's existing deterministic Trace evaluation and v0.31 aggregate latency/token/cost metrics into an Agent Runtime evaluation harness that can measure context, memory, recovery and sandbox policies using repeatable cases and ablations.

This release MUST reuse existing `src/paperclaw/eval/**`, durable Trace and runtime entrypoints. Do not create a disconnected benchmark framework.

## 2. Problem statement

Current evaluation proves useful run/trace quality and aggregate operational metrics. The next gap is causal/runtime evaluation:

- Does a memory/context policy improve task success under a fixed budget?
- Does compaction preserve required tool/evidence state?
- Can the runtime recover from injected failures?
- Does sandboxing change task success/latency while preserving security constraints?
- Can one exact trace be replayed for diagnosis without causing external side effects?

## 3. Existing implementation to inspect first

Before coding inspect at minimum:

- `src/paperclaw/eval/**`;
- v0.31 aggregate eval CLI/reporting;
- deterministic trace scorers from earlier releases;
- durable Trace event schema/storage;
- team/single-agent runtime entrypoints;
- current pricing policy handling;
- current context/memory implementation after v0.39;
- current sandbox implementation after v0.40;
- existing failure injection/retry/DLQ tests;
- existing real-provider test marker conventions.

## 4. Benchmark case schema

Define a versioned data contract, JSON/YAML according to repository conventions.

Minimum structure:

```text
case_id
schema_version
task/input
workspace_fixture
runtime_mode
allowed_tools
acceptance assertions
forbidden assertions
budgets:
  max_steps
  max_model_calls
  max_tokens | null
  max_wall_time
faults[]
expected_terminal_class
metadata/tags
```

Assertions should prefer durable, machine-checkable facts such as file hashes, terminal status, specific tool invocations, trace events and forbidden path/network access.

Avoid LLM-judge-only acceptance for P0.

## 5. Required benchmark suites

Provide a small but meaningful checked-in suite for at least:

```text
basic_tool_use
context_pressure
memory_recall
memory_conflict
crash_recovery
retryable_tool_failure
ambiguous_side_effect
sandbox_denial
sandbox_timeout
long_horizon_bounded
```

Use deterministic/fake model plans where necessary so CI failures are reproducible.

## 6. Replay contract

Replay has two modes with explicit names:

### 6.1 Recorded replay (default)

- reconstruct state and scorer inputs from durable events/results;
- do NOT re-run external model or tool side effects;
- verify event ordering, context snapshot links, state projection and scoring;
- suitable for debugging/regression.

### 6.2 Re-execution replay (opt-in)

- starts from a fixture/snapshot under explicit operator request;
- may invoke model/tool/sandbox according to current policy;
- generates a new run id linked to the source run;
- never mutates the original trace;
- cannot be described as deterministic if a live model is used.

## 7. Fault injection

Implement bounded, named injection points at existing seams rather than arbitrary monkeypatching scattered through production code.

Minimum fault classes:

```text
model_timeout
model_malformed_response
tool_timeout
tool_command_failure
tool_unknown_outcome
memory_read_failure
context_compaction_failure
trace_write_failure or persistence failure where safely testable
sandbox_unavailable
sandbox_denied
sandbox_cleanup_failure
worker/process interruption
```

Each fault has:

```text
fault_id
injection_point
trigger condition/count
expected recovery class
```

Production behavior with injection disabled must be identical to baseline.

## 8. Metrics

Reuse existing metric names where possible. Add runtime-specific metrics only when missing.

Required report fields:

```text
task_success_rate
tool_success_rate
tool_failure_rate
recovery_success_rate
resume_success_rate
forbidden_action_rate
context_overflow_or_compaction_rate
memory_selection_precision/recall where benchmark labels exist
steps
model_calls
input_tokens
output_tokens
total_tokens
latency p50/p95/p99 where sample count permits
estimated_cost using existing pricing policy
unpriced_call_count
failure_taxonomy
```

For very small sample counts, report raw values and avoid misleading percentiles.

## 9. Ablation runner

Support at least these policy comparisons after v0.39:

```text
A: recent transcript only / legacy-compatible path
B: deterministic compaction
C: compaction + durable selected memory/context policy
```

If implementation supports it safely, add:

```text
D: memory disabled
E: alternate memory priority/budget
```

Ablations must run the same benchmark cases, fixture versions, provider/model mode and budgets. The report must show configuration fingerprints so comparisons are reproducible.

Do not hard-code a claim that memory improves results. The harness must allow a negative result.

## 10. Security/sandbox eval

After v0.40 include cases where success means the dangerous action is denied, e.g.:

- network access under `network=none`;
- read/write outside authorized workspace;
- PID/resource exhaustion attempt;
- artifact traversal export.

Security guardrail success must be reported separately from task success where appropriate.

## 11. CLI/operator surface

Provide commands equivalent to:

```bash
paperclaw eval run BENCHMARK_PATH
paperclaw eval replay RUN_ID
paperclaw eval ablate BENCHMARK_PATH --variants ...
paperclaw eval report RUN_OR_SUITE_ID
```

Exact naming may integrate with existing `paperclaw-observe` or eval CLI to avoid duplicate interfaces.

Output formats should include machine-readable JSON plus a concise human-readable table/Markdown artifact.

## 12. CI policy

### Required offline gate

- deterministic benchmark subset;
- no live provider;
- no external mutable web dependency;
- regression thresholds checked against explicit baseline artifact/config;
- trace/replay integrity;
- at least one fault-recovery case;
- at least one sandbox-denial case when Docker job is available.

### Live provider gate

Opt-in/manual or secret-gated:

- clearly tagged `real_llm`;
- same benchmark schema but bounded case count;
- record model/provider/config fingerprint;
- report cost/latency without treating one run as statistical proof.

Fake/offline results must never be labeled live-provider evidence.

## 13. Regression threshold design

Start with hard invariants rather than unstable quality thresholds:

- forbidden action rate must remain 0 for denial cases;
- deterministic benchmark success must remain 100% for fixed fixtures;
- replay integrity mismatch must remain 0;
- duplicate side-effect count in resume cases must remain 0;
- required trace/context links must remain complete.

Latency/token thresholds may initially be reported-only until sufficient stable baseline samples exist.

## 14. Acceptance gates

- [ ] benchmark schema versioned and validated;
- [ ] checked-in deterministic suite covers all required categories;
- [ ] recorded replay performs no external side effect;
- [ ] re-execution replay creates a new linked run;
- [ ] fault injection is disabled by default and does not alter normal path;
- [ ] recovery/resume cases produce machine-checkable metrics;
- [ ] ablation report compares identical fixtures/budgets with config fingerprints;
- [ ] security denial cases are represented as guardrail success;
- [ ] offline CI gate is deterministic;
- [ ] live-provider evidence is separately labeled;
- [ ] existing eval/observe interfaces remain compatible or have documented migration;
- [ ] full non-live regression passes;
- [ ] exact-head CI evidence and Handoff are recorded.

## 15. Non-goals

- claiming model quality leadership;
- replacing external benchmark ecosystems;
- LLM-as-judge as the only acceptance oracle;
- large public benchmark hosting;
- production telemetry warehouse;
- automatic provider price scraping;
- forcing every test through live Docker/LLM.

## 16. Required implementation SOP

1. Inspect current eval/trace interfaces and latest v0.39/v0.40 contracts.
2. Branch from current stable base; record exact SHA.
3. Define benchmark schema and validator first.
4. Add deterministic fixtures/cases using existing runtime seams.
5. Implement recorded replay before re-execution replay.
6. Add named fault injection points behind explicit configuration.
7. Extend existing aggregate report with runtime/recovery metrics.
8. Implement ablation runner with immutable config fingerprints.
9. Add security/sandbox cases and CI separation.
10. Run focused deterministic suite repeatedly to check reproducibility.
11. Run full non-live regression, lint/type/build gates and exact-head CI.
12. Run live-provider acceptance only if credentials are available; otherwise mark pending without blocking offline implementation.
13. Produce `artifacts/v0_41/HANDOFF.md`, benchmark result artifact and final implementation commit(s).

## 17. Safe interview claim boundary

Safe after acceptance:

> PaperClaw evaluates Agent Runtime behavior with versioned deterministic cases, trace replay, named fault injection and policy ablation. Reports distinguish task success, recovery, guardrail failures, steps, tokens, latency and estimated cost, while live-provider evidence remains separate from offline control-flow evidence.

Do not claim the harness proves general model quality.
