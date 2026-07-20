# PaperClaw

PaperClaw 是一个面向 Coding、Research 与多 Agent 工作流的可审计 Agent Runtime。

当前开发版本：**0.34.0**。v0.34 在 v0.33 的 Outbox、恢复与取消基础上，引入真实
Redis Streams Message Bus 与 PostgreSQL Choreography Store，并通过多个独立 Python
进程共享同一 Consumer Group 的验收。

## 当前主链路

```text
JSON Team Plan
  -> paperclaw-team-run
  -> Redis Streams or SQLite Message Bus
  -> existing Coordinator / Worker / Reviewer
  -> PostgreSQL or SQLite terminal state + ordered Outbox
  -> exact-idempotent terminal publication
  -> contiguous logical Ack
  -> SQLite Trace projection / Aggregate Eval
```

`Coordinator` 仍是唯一调度权威。Redis 和 PostgreSQL 实现的是既有接口，不引入另一套
DAG、Worker、Reviewer、预算、租约或取消协议。

## 安装

本地 SQLite 运行：

```bash
python -m pip install -e ".[dev]"
```

只安装分布式后端依赖：

```bash
python -m pip install -e ".[distributed]"
```

配置 OpenAI-compatible Provider：

```bash
export PAPERCLAW_API_KEY="..."
export PAPERCLAW_BASE_URL="https://api.mistral.ai/v1"
export PAPERCLAW_MODEL="mistral-small-latest"
export PAPERCLAW_PROVIDER="mistral"
```

## SQLite 单机模式

```bash
paperclaw-team-run \
  --workspace . \
  --plan examples/v0_31/team-plan.json \
  --bus-backend sqlite \
  --database .paperclaw/team-bus.sqlite3 \
  --state-backend sqlite \
  --state-database .paperclaw/team-choreography.sqlite3 \
  --trace-database .paperclaw/traces.sqlite3
```

## Redis + PostgreSQL 多进程模式

环境变量：

```bash
export PAPERCLAW_REDIS_URL="redis://localhost:6379/0"
export PAPERCLAW_POSTGRES_DSN="postgresql://paperclaw:paperclaw@localhost:5432/paperclaw"
```

运行：

```bash
paperclaw-team-run \
  --workspace . \
  --plan examples/v0_31/team-plan.json \
  --bus-backend redis \
  --redis-url "$PAPERCLAW_REDIS_URL" \
  --redis-namespace paperclaw-prod \
  --state-backend postgres \
  --postgres-dsn "$PAPERCLAW_POSTGRES_DSN" \
  --postgres-schema paperclaw \
  --trace-database .paperclaw/traces.sqlite3
```

当前 CLI 是“一次提交并等待终态”的入口。多个 Runtime 进程可以使用同一个
`--consumer-id` 和相同 Redis/PostgreSQL 配置，共享 Consumer Group 与 Choreography State。

## v0.34 Redis Streams Message Bus

公开实现：

```python
from paperclaw.message_bus import RedisStreamsMessageBusStore
```

特性：

- 一个 Redis Stream 对应一个逻辑 Topic；
- Lua 原子完成容量检查、Topic Sequence、Stream append、幂等绑定和审计事件；
- 幂等范围与 SQLite 一致：`(topic, sender_id, idempotency_key)`；
- 每个逻辑 `consumer_id` 对应一个 Consumer Group；
- 每个进程使用独立 Consumer 名称；
- `XAUTOCLAIM` 回收崩溃进程遗留的 Pending Entry；
- direct recipient 在 Consumer Group 内进行资格检查；
- Redis `XACK` 可以乱序发生，但 PaperClaw 只推进连续的逻辑 Ack Cursor；
- Message Bus audit events、count 和 latest sequence 保留。

### 连续 Ack

假设两个进程分别完成 Sequence 2 和 Sequence 1：

```text
Ack(2) -> logical cursor remains 0
Ack(1) -> logical cursor advances to 2
```

因此上游不会把尚未确认的 Sequence 1 错误地视为已完成。

## v0.34 PostgreSQL Choreography Store

公开实现：

```python
from paperclaw.multiagent import PostgreSQLResilientChoreographyStore
```

一个 PostgreSQL 事务写入：

- attempt state；
- failure category/disposition；
- terminal snapshot；
- ordered terminal Outbox。

Outbox 使用显式 `ordinal`，不依赖哈希 ID 或时间戳排序。跨进程 Publisher 可以使用：

```sql
FOR UPDATE SKIP LOCKED
```

安全 Claim 不同 Outbox 行，并支持过期 Claim 接管。

## v0.33 Resilient Choreography

终态顺序：

```text
Coordinator result
  -> commit terminal state + ordered Outbox
  -> publish with stable idempotency key
  -> mark Outbox delivered
  -> Ack request
```

恢复规则：

- terminal commit 后崩溃：不重新运行 Coordinator，只补发 Outbox；
- publish 后、delivered 标记前崩溃：按原幂等键重放，不重复产生消息；
- delivered 后、Ack 前崩溃：只补 Ack；
- Outbox 未完全送达时，请求不能 Ack。

失败分类：

| 分类 | 默认行为 |
|---|---|
| `retryable` | Timeout、Connection、Interrupted、OS transport 错误，有界重试 |
| `permanent` | 无效输入、类型、权限、缺失配置，首次即 DLQ |
| `unknown` | 无法安全分类时按 `max_attempts` 有界重试 |

## Durable Cancellation

SQLite：

```bash
paperclaw-team-cancel \
  --bus-backend sqlite \
  --database .paperclaw/team-bus.sqlite3 \
  --request-id interview-research-check \
  --task-id runtime-review
```

Redis：

```bash
paperclaw-team-cancel \
  --bus-backend redis \
  --redis-url "$PAPERCLAW_REDIS_URL" \
  --redis-namespace paperclaw-prod \
  --request-id interview-research-check \
  --task-id runtime-review
```

取消消息调用现有 `Coordinator.cancel(task_id, tasks)`，继续复用 Worker cooperative cancel 与
subprocess-tree termination。

## v0.32 Trace / Eval Closure

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

当前 Trace projection 仍使用本地 SQLite。v0.34 将 Message Bus 和 Choreography State
扩展到共享服务，但没有声称 Trace 已经是多机共享数据库。

Aggregate Eval 当前统计：

- Run success rate；
- Tool failure rate；
- P50 / P95 / P99 wall latency；
- Model / Tool duration 与 calls；
- retries；
- input / output / total tokens；
- estimated USD cost 与 unpriced calls；
- failure categories。

Citation Precision/Recall、Groundedness、Abstention Accuracy 和检索质量基准属于 v0.35。

## Capability Catalog

```bash
paperclaw capabilities --format json
paperclaw capabilities --status shipped
paperclaw capabilities --surface service
```

当前新增：

```text
multiagent.distributed_runtime [shipped]
```

## 真实分布式验收

GitHub Actions 启动：

- Redis 7；
- PostgreSQL 16；
- 两个 `multiprocessing.spawn` Worker 进程。

验收覆盖：

1. Redis exact idempotency 与 conflict；
2. 不同 sender 可复用相同 idempotency key；
3. 乱序 Ack 只推进连续 Cursor；
4. 崩溃 Worker 的 Pending Entry 被另一进程 Claim；
5. PostgreSQL terminal + ordered Outbox 原子提交；
6. `SKIP LOCKED` Claim 不重复；
7. 两个进程处理八个请求且每个请求只有一个 acknowledged terminal；
8. v0.33 崩溃恢复和 v0.32 Trace/Eval 兼容；
9. `0.34.0[distributed]` wheel 安装与 CLI smoke。

本地执行：

```bash
export PAPERCLAW_TEST_REDIS_URL="redis://localhost:6379/15"
export PAPERCLAW_TEST_POSTGRES_DSN="postgresql://paperclaw:paperclaw@localhost:5432/paperclaw"
python -m pytest -q tests/integration/test_v034_distributed_backends.py -m distributed
```

## 安全与架构边界

- Secret 不写入 Manifest、Message Bus、ExecutionRequest、Trace 或 Artifact metadata；
- delivery 是 at-least-once，不是 exactly-once；
- PostgreSQL 和 Redis 不构成一个分布式事务；
- Outbox replay 依赖 Message Bus exact idempotency；
- Redis Cluster cross-slot Lua 部署未验收；
- Trace projection 仍为 SQLite；
- 外部 Tool 副作用仍要求 Tool-level idempotency；
- TLS、凭证轮换、备份和托管运维属于部署责任；
- 没有声称 Kafka、NATS 或 RabbitMQ 已实现。

## 开发与验收

```bash
python -m pytest -q -m "not real_llm and not distributed"
python -m pytest -q tests/integration/test_v034_distributed_backends.py -m distributed
python -m ruff check src/paperclaw tests --select E9,F63,F7,F82 --ignore F821
python -m build
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
Plan/PaperClaw_v0.34_PostgreSQL_Redis_Multiprocess.md
CHANGELOG.md
```
