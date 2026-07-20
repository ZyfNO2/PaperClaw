# PaperClaw

PaperClaw 是一个面向 Coding、Research 与多 Agent 工作流的可审计 Agent Runtime。

当前开发版本：**0.32.0**。v0.32 的重点不是继续增加孤立模块，而是把已经存在的
MultiAgent、Message Bus、Trace 与 Aggregate Eval 接成一个可运行、可查询的闭环。

## 当前主链路

```text
JSON Team Plan
  -> paperclaw-team-run
  -> durable Message Bus request
  -> existing Coordinator
  -> Worker / Reviewer / Fix Round
  -> durable Message Bus events
  -> SessionEvent / Trace database
  -> paperclaw-observe
```

同一次 Team Run 使用一个稳定身份：

```text
request_id -> team_run_id(request_id) -> durable Trace -> Aggregate Eval
```

`Coordinator` 仍是唯一调度权威。v0.32 没有复制 DAG、Worker、Reviewer、预算、租约或取消逻辑。

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

Windows PowerShell：

```powershell
$env:PAPERCLAW_API_KEY="..."
$env:PAPERCLAW_BASE_URL="https://api.mistral.ai/v1"
$env:PAPERCLAW_MODEL="mistral-small-latest"
$env:PAPERCLAW_PROVIDER="mistral"
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

输出包含：

```json
{
  "request_id": "interview-research-check",
  "run_id": "team-interview-research-check",
  "trace_database": "/workspace/.paperclaw/traces.sqlite3",
  "terminal": true,
  "metrics": {}
}
```

直接按 Request ID 查询同一次运行：

```bash
paperclaw-observe \
  --database .paperclaw/traces.sqlite3 \
  --request-id interview-research-check \
  --pricing examples/v0_31/pricing.example.json
```

也可以继续使用底层 Run ID：

```bash
paperclaw-observe \
  --database .paperclaw/traces.sqlite3 \
  --run-id team-interview-research-check
```

## v0.32 Observability Closure

### Durable Trace Bridge

`SQLiteTeamTraceBridge` 是 Message Bus 的观察性装饰器：

- Message Bus 仍负责 publish、pull、cursor 和 ack；
- 成功发布的 Team Event 被投影到既有 `SessionEvent` 表；
- `SQLiteTraceReader` 读取同一数据库；
- Bus message ID 被用作 Trace Event 幂等边界；
- Coordinator EventEnvelope 的内层 payload 会被规范化展开；
- `run.completed` / `run.failed` 使用既有 Trace 终态词汇。

当前不是第二套事件系统，也不是新的调度器。

### Model Observability

`TraceUsageCollector` 在 Model 调用结束时持久化：

- provider / model；
- duration；
- retry count；
- input / output / total tokens；
- operator-supplied estimated cost；
- succeeded / failed。

价格仍然是外部策略，不写死在仓库中。未知价格显式记录为 `unpriced`。

### Tool Observability

`ObservedWorker` 只投影有限的 Tool 生命周期事实：

- `tool.started`；
- `tool.completed`；
- `tool.failed`；
- tool name、step、status、error code。

不会把 Tool arguments、Tool output、Prompt、隐藏推理或 Secret 复制进 Trace。

## Aggregate Eval

当前可统计：

- Run success rate；
- Tool failure rate；
- P50 / P95 / P99 wall latency；
- Model / Tool duration；
- Model / Tool call count；
- retry count；
- input / output / total tokens；
- estimated USD cost；
- unpriced model calls；
- failure categories。

当前仍未声称已经完成：

- Tool 参数正确率；
- Citation Precision / Recall；
- Groundedness；
- Abstention Accuracy；
- 单 Agent 与 Multi-Agent 的质量收益曲线；
- Desktop Eval Dashboard。

这些属于 v0.35 的科研质量评测范围。

## 核心能力

### Agent、验证与工具

- bounded ReAct Runtime；
- allowlisted 工具、路径权限与二次权限检查；
- deterministic evidence verification；
- semantic acceptance judge 与执行模型解耦；
- Plan Mode、AskUserQuestion、静态 Skills；
- read-only LSP diagnostics、definition、references、symbols、hover；
- MCP discovery、schema adaptation、permission recheck 与调用 foundation。

### Context、Memory 与 Retrieval

- trust-aware Context Orchestration；
- Session、Checkpoint 与安全恢复；
- bounded global USER profile；
- project-scoped MEMORY namespace；
- `PAPERCLAW.md`、`CLAUDE.md`、`AGENTS.md` 项目说明；
- 本地增量 BM25、citation anchors、grounding 与 abstention；
- `require_current / allow_stale / disabled` 索引策略；
- backend-neutral Retriever Protocol；
- citation-preserving weighted RRF Hybrid fusion。

Semantic/Vector backend 仍是 adapter seam，没有内置托管 embedding 服务、外部向量数据库或 reranker。

### Multi-Agent、任务与远程执行

- Coordinator / Worker / Reviewer；
- Task DAG、并行 Worker、权限与 FileLease；
- durable background task lifecycle；
- subprocess isolation 与跨平台进程树终止；
- authenticated Remote Worker Gateway；
- generation-fenced durable ownership；
- durable ordered Agent Message Bus；
- Bus-driven Coordinator choreography；
- retry、terminal state 与 DLQ；
- Team Run 到 durable Trace / Eval 的统一身份。

### Project、Artifact 与 Desktop

- 安全 Project Manifest；
- Project Knowledge fingerprint 与 freshness policy；
- append-only Artifact revisions；
- content-addressed SHA-256 blobs；
- Project / Run / Task / Trace source links；
- Desktop Product Panel；
- allowlisted Desktop API；
- 固定 workspace 与 export root。

## Capability Catalog

机器可读事实源：

```bash
paperclaw capabilities
paperclaw capabilities --format json
paperclaw capabilities --status foundation
paperclaw capabilities --surface cli
```

状态含义：

| 状态 | 含义 |
|---|---|
| `shipped` | 已接入正常运行路径并有验收设计 |
| `foundation` | 合同和参考实现完成，但基础设施或产品面仍有限制 |
| `experimental` | 可使用，但接口或生命周期仍可能调整 |
| `planned` | 仅进入后续计划，不得描述为已实现 |

## 安全与架构边界

- Secret 不写入 Manifest、Message Bus、ExecutionRequest、Trace 或 Artifact metadata；
- Remote Workspace 由 Worker Host 白名单验证；
- 不允许远程上传任意 Python module/function；
- stale lease generation 不能 heartbeat、标记 side effect、complete 或 requeue；
- 网络取消未确认时返回 `UNKNOWN_OUTCOME`；
- SQLite 多进程证据不等于多机分布式共识；
- 当前 delivery 是 at-least-once，不是 exactly-once；
- v0.32 Trace projection 与 choreography state 还不是一个原子 Outbox 事务；
- 外部副作用发生后、终态持久化前崩溃，仍依赖 Tool-level idempotency。

## 开发与验收

```bash
python -m pytest -q \
  tests/unit/multiagent/test_observed_runtime.py \
  tests/unit/multiagent/test_bus_runtime.py \
  tests/unit/eval/test_aggregate.py

python -m pytest -q -m "not real_llm"
python -m ruff check src/paperclaw tests --select E9,F63,F7,F82 --ignore F821
python -m build
```

真实 Provider 测试必须显式使用 `real_llm` marker：

```bash
python -m pytest -q tests/real_llm/test_v032_trace_eval_live.py -m real_llm
```

Fake、离线 Provider 与真实 Provider 证据必须分别记录，不得混用。

## 版本路线

1. **v0.32**：Team Run、Trace、Eval 闭环与正式版本元数据；
2. **v0.33**：故障注入、恢复、取消、Outbox、幂等；
3. **v0.34**：PostgreSQL + Redis Streams 真实多进程运行；
4. **v0.35**：Hybrid Retrieval 与科研质量评测；
5. **v0.36**：Project-scoped Skills / Connectors。

详细范围见：

```text
Plan/PaperClaw_v0.32_Observability_Closure.md
CHANGELOG.md
```
