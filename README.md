# PaperClaw

PaperClaw 是一个面向 Coding、Research 与多 Agent 工作流的可审计 Agent Runtime。

当前开发版本：**0.33.0**。v0.33 在 v0.32 的 Team Run / Trace / Eval 闭环上增加
终态 Outbox、故障注入、崩溃恢复、持久化取消和显式重试分类。

## 当前主链路

```text
JSON Team Plan
  -> paperclaw-team-run
  -> durable Message Bus request
  -> existing Coordinator
  -> Worker / Reviewer / Fix Round
  -> atomic terminal state + terminal Outbox
  -> exact-idempotent Bus publication
  -> request Ack
  -> durable Trace / Aggregate Eval
```

`Coordinator` 仍是唯一调度权威。v0.33 不复制 DAG、Worker、Reviewer、预算、租约或
进程取消逻辑，只强化外围持久化边界。

## 快速开始

```bash
python -m pip install -e ".[dev]"
```

配置 OpenAI-compatible Provider：

```bash
export PAPERCLAW_API_KEY="..."
export PAPERCLAW_BASE_URL="https://api.mistral.ai/v1"
export PAPERCLAW_MODEL="mistral-small-latest"
export PAPERCLAW_PROVIDER="mistral"
```

运行 Team Plan：

```bash
paperclaw-team-run \
  --workspace . \
  --plan examples/v0_31/team-plan.json \
  --database .paperclaw/team-bus.sqlite3 \
  --state-database .paperclaw/team-choreography.sqlite3 \
  --trace-database .paperclaw/traces.sqlite3 \
  --pricing examples/v0_31/pricing.example.json
```

同一次运行使用稳定身份：

```text
request_id -> team_run_id(request_id) -> durable Trace -> Aggregate Eval
```

查询：

```bash
paperclaw-observe \
  --database .paperclaw/traces.sqlite3 \
  --request-id interview-research-check \
  --pricing examples/v0_31/pricing.example.json
```

## v0.33 Resilient Choreography

### Terminal Outbox

`SQLiteResilientChoreographyStore` 在一个 SQLite 事务内写入：

- terminal attempt state；
- terminal snapshot；
- `team.run.metrics` publication intent；
- `team.run.terminal` 或 DLQ publication intent。

执行顺序：

```text
Coordinator result
  -> commit terminal state + Outbox
  -> publish Outbox row with stable idempotency key
  -> mark delivered
  -> Ack request
```

崩溃恢复规则：

- terminal commit 后崩溃：不重新运行 Coordinator，只补发 Outbox；
- Bus publish 后、delivered 标记前崩溃：使用原 idempotency key 重放，不产生重复消息；
- delivered 后、Ack 前崩溃：只补 Ack；
- Outbox 未完全送达时，请求不能 Ack。

### Failure Injection

可重复检查点：

```text
after_attempt_started
after_coordinator_completed
after_terminal_committed
after_outbox_published
before_request_ack
```

`InjectedCrash` 是测试中的进程死亡替身，不会被转换成普通业务失败。

### Retry Taxonomy

| 分类 | 默认行为 |
|---|---|
| `retryable` | Timeout、Connection、Interrupted、OS transport 错误，受 max_attempts 限制 |
| `permanent` | 无效输入、类型、权限、缺失配置，首次即 DLQ |
| `unknown` | 不能安全识别时进行有界重试 |

错误分类、attempt 和 disposition 都进入终态快照或 DLQ payload。

### Durable Cancellation

取消入口：

```bash
paperclaw-team-cancel \
  --workspace . \
  --database .paperclaw/team-bus.sqlite3 \
  --request-id interview-research-check \
  --task-id runtime-review \
  --reason "operator stop"
```

取消链路：

```text
paperclaw-team-cancel
  -> multiagent.team.cancellations.v1
  -> request-specific cancellation consumer
  -> existing Coordinator.cancel(task_id, tasks)
  -> existing Worker cancel event / subprocess-tree termination
```

- `cancellation_id` 是精确幂等边界；
- 不提供 `--task-id` 时取消该请求的全部任务；
- 未知 Task ID 被记录为 rejected；
- 调用现有 Coordinator 取消入口后才 Ack 取消消息。

## v0.32 Observability Closure

`SQLiteTeamTraceBridge` 将成功发布的 Team Event 投影到既有 `SessionEvent` 表，
`SQLiteTraceReader` 和 `paperclaw-observe` 读取同一个 Run。

`TraceUsageCollector` 持久化：

- provider / model；
- duration；
- retry count；
- input / output / total tokens；
- operator-supplied estimated cost；
- succeeded / failed。

`ObservedWorker` 只投影 Tool name、step、status 和 error code，不复制 Tool arguments、
Tool output、Prompt、隐藏推理或 Secret。

## Aggregate Eval

当前可统计：

- Run success rate；
- Tool failure rate；
- P50 / P95 / P99 wall latency；
- Model / Tool duration；
- Model / Tool call count；
- retries；
- input / output / total tokens；
- estimated USD cost；
- unpriced model calls；
- failure categories。

科研质量指标如 Citation Precision / Recall、Groundedness、Abstention Accuracy、
单 Agent 与 Multi-Agent 成本—质量曲线属于 v0.35。

## 核心能力

### Agent、验证与工具

- bounded ReAct Runtime；
- allowlisted 工具、路径权限与二次检查；
- deterministic evidence verification；
- semantic acceptance judge；
- Plan Mode、AskUserQuestion、静态 Skills；
- read-only LSP；
- MCP discovery、schema adaptation、permission recheck 与调用 foundation。

### Context、Memory 与 Retrieval

- trust-aware Context Orchestration；
- Session、Checkpoint 与安全恢复；
- bounded USER profile 与 project-scoped MEMORY；
- 本地增量 BM25、citation anchors、grounding 与 abstention；
- fingerprint freshness policy；
- backend-neutral Retriever Protocol；
- citation-preserving weighted RRF。

Semantic/Vector backend 仍是 adapter seam，没有内置托管 embedding、外部向量数据库或 reranker。

### Multi-Agent、任务与远程执行

- Coordinator / Worker / Reviewer；
- Task DAG、并行 Worker、权限与 FileLease；
- durable task lifecycle；
- subprocess isolation 与跨平台进程树终止；
- authenticated Remote Worker Gateway；
- generation-fenced ownership；
- durable ordered Message Bus；
- Bus-driven choreography；
- Team Run / Trace / Eval 统一身份；
- terminal Outbox recovery；
- durable cancellation；
- retry taxonomy 与 DLQ。

### Project、Artifact 与 Desktop

- 安全 Project Manifest；
- Project Knowledge fingerprint 与 freshness policy；
- append-only Artifact revisions；
- content-addressed blobs；
- Project / Run / Task / Trace source links；
- Desktop Product Panel 与 allowlisted API。

## Capability Catalog

```bash
paperclaw capabilities --format json
paperclaw capabilities --status shipped
paperclaw capabilities --surface cli
```

v0.33 新增：

```text
multiagent.resilient_choreography [shipped]
```

## 安全与架构边界

- Secret 不写入 Manifest、Message Bus、ExecutionRequest、Trace 或 Artifact metadata；
- Remote Workspace 由 Worker Host 白名单验证；
- stale lease generation 不能 heartbeat、标记 side effect、complete 或 requeue；
- delivery 是 at-least-once，不是 exactly-once；
- Outbox 与 terminal state 在本地 SQLite 中原子提交，但不与外部 Broker 构成分布式事务；
- live progress events 仍是 direct best-effort publication；
- 外部 Tool 副作用仍要求 Tool-level idempotency；
- SQLite 多进程证据不等于多机分布式共识。

## 开发与验收

```bash
python -m pytest -q \
  tests/unit/multiagent/test_resilient_runtime.py \
  tests/unit/multiagent/test_observed_runtime.py \
  tests/unit/multiagent/test_bus_runtime.py \
  tests/unit/eval/test_aggregate.py

python -m pytest -q -m "not real_llm"
python -m ruff check src/paperclaw tests --select E9,F63,F7,F82 --ignore F821
python -m build
```

真实 Provider 崩溃恢复验收：

```bash
python -m pytest -q tests/real_llm/test_v033_outbox_recovery_live.py -m real_llm
```

## 版本路线

1. **v0.32**：Team Run、Trace、Eval 闭环；
2. **v0.33**：故障注入、恢复、取消、Outbox、幂等；
3. **v0.34**：PostgreSQL + Redis Streams 真实多进程运行；
4. **v0.35**：Hybrid Retrieval 与科研质量评测；
5. **v0.36**：Project-scoped Skills / Connectors。

详细范围：

```text
Plan/PaperClaw_v0.32_Observability_Closure.md
Plan/PaperClaw_v0.33_Resilience_Outbox_Cancellation.md
CHANGELOG.md
```
