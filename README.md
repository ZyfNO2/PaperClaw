# PaperClaw

PaperClaw 是一个面向 Coding、Research 与多 Agent 工作流的可审计 Agent Runtime。

当前开发版本：**0.37.0**。

```text
Team Plan
  -> SQLite / Redis Streams Message Bus
  -> Coordinator / Worker / Reviewer
  -> SQLite / PostgreSQL terminal state + ordered Outbox
  -> durable Trace / Aggregate Eval

Project Knowledge
  -> BM25 + persistent local semantic vectors
  -> weighted RRF + evidence-aware reranker
  -> retrieval / citation / grounding / abstention / cost evaluation

Project Extensions
  -> project-scoped descriptors
  -> trust policy + permission ceiling
  -> bounded Skill activation / application-registered Connector runtime
  -> filtered Tool discovery + call-time policy recheck
  -> bounded/redacted Tool execution + mutation/invocation audit
```

## 安装

```bash
python -m pip install -e ".[dev]"
```

分布式运行：

```bash
python -m pip install -e ".[distributed]"
```

## v0.37 Extension Execution Closure

v0.37 将 v0.36 的注册与激活能力接入现有 `ToolRegistry`，但 Connector 的
transport、认证存储和 runtime factory 仍由宿主应用控制。

执行闭环：

```text
extensions.json
  -> ProjectExtensionActivator
  -> filtered discovery
  -> frozen JSON Schema
  -> stable project_<extension>_<tool>_<digest> Tool name
  -> invocation-time descriptor/trust/permission recheck
  -> host runtime call_tool(...)
  -> bounded + redacted ToolResult
  -> content-free SQLite invocation audit
```

宿主 runtime 实现：

```python
from paperclaw.projects import ConnectorCallResult

class SearchRuntime:
    def discover_tools(self):
        return [{
            "name": "search",
            "description": "Search project evidence",
            "input_schema": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
                "additionalProperties": False,
            },
        }]

    def call_tool(self, name, arguments, context):
        # context.auth_value is host-resolved and excluded from public projections.
        return ConnectorCallResult(True, {"matches": []})

    def close(self):
        pass
```

注册到现有 Tool Registry：

```python
from paperclaw.projects import (
    ExtensionPermissions,
    MappingProjectSecretResolver,
    ProjectExtensionActivator,
    ProjectExtensionExecutor,
    ProjectExtensionRegistry,
)
from paperclaw.tools.registry import ToolRegistry

project_registry = ProjectExtensionRegistry(".")
activator = ProjectExtensionActivator(
    project_registry,
    permission_ceiling=ExtensionPermissions(
        tools=("search",),
        network_hosts=("search.example.com",),
    ),
    connector_factories={"search": lambda descriptor, permissions: SearchRuntime()},
)
executor = ProjectExtensionExecutor(
    activator,
    secret_resolver=MappingProjectSecretResolver({
        "secret://project/search": "host-owned-value",
    }),
)
tools = ToolRegistry()
registration = executor.register_tools(tools)
```

每次调用都会重新读取 registry。扩展被删除、禁用、修改，或权限 ceiling 收紧后，
调用会在远程执行前失败。调用审计只记录状态、时延、字节数和 schema hash，
不记录参数、结果、`secret://` reference 或解析后的 secret。

`paperclaw-project-extensions audit` 同时返回：

- `events`：register/replace/enable/disable/remove；
- `invocations`：success/error/timeout/cancelled/denied。

## v0.36 Project Extensions

扩展描述符保存在：

```text
.paperclaw/extensions.json
```

变更审计保存在：

```text
.paperclaw/extensions-audit.sqlite3
```

描述符包括：

- `extension_id`、类型和 semantic version；
- enabled state 与 trust source；
- Tool、read path、write path 和 network host 权限；
- Skill 相对路径或 `mcp:<factory_id>` Connector entrypoint；
- 公开 JSON metadata。

Registry 会同步 `project.json` 中的 `enabled_skills` 和 `enabled_connectors`。

有效权限始终为：

```text
project descriptor permissions
∩ runtime permission ceiling
```

Skill 激活要求：

- 位于当前 workspace；
- 不是 symlink；
- 不位于 `.paperclaw`；
- 是有大小上限的 UTF-8 普通文件；
- trust source 被运行时策略允许。

Connector 激活要求：

- entrypoint 使用 `mcp:<factory_id>`；
- factory 由宿主应用注册；
- 项目文件不能声明 Python module 或 import path；
- 只暴露有效 Tool 权限允许的 discovery 结果；
- discovery schema 必须是公开、可序列化 JSON；
- Session 按逆序关闭。

CLI：

```bash
paperclaw-project-extensions --workspace . list
paperclaw-project-extensions --workspace . validate
paperclaw-project-extensions --workspace . audit

paperclaw-project-extensions --workspace . register-skill \
  --id skill.review \
  --version 1.0.0 \
  --entrypoint skills/review.md \
  --enabled \
  --tool file_read \
  --read-path docs

paperclaw-project-extensions --workspace . register-connector \
  --id connector.search \
  --version 1.0.0 \
  --entrypoint mcp:search \
  --trust-source verified \
  --tool search \
  --network-host search.example.com

paperclaw-project-extensions --workspace . enable skill.review
paperclaw-project-extensions --workspace . disable skill.review
paperclaw-project-extensions --workspace . remove skill.review
```

## v0.35 Hybrid Retrieval

```text
SQLiteBM25Retriever
  + SQLiteHashingVectorRetriever
  -> HybridRetriever(weighted RRF)
  -> EvidenceAwareReranker
  -> version/hash/ChunkLocator-bound candidates
```

本地 Semantic Retriever 提供 SQLite persistence、encoder/corpus fingerprint、原子 replace、
bounded upsert、deterministic cosine ranking 和 canonical `ChunkLocator` round trip。

它使用 deterministic feature hashing，不声称等价于 transformer embedding。

质量评测：

```bash
paperclaw-retrieval-quality \
  --benchmark examples/v0_35/research-quality-benchmark.json \
  --predictions examples/v0_35/hybrid-predictions.json \
  --baseline examples/v0_35/lexical-baseline.json
```

指标包括 Recall@5/10、MRR、nDCG@10、Document Recall@10、Citation Precision/Recall、
Grounded Claim Rate、Claim Coverage、Abstention Accuracy、Latency、Token 和 Cost Delta。

## v0.34 Distributed Runtime

```bash
paperclaw-team-run \
  --workspace . \
  --plan examples/v0_31/team-plan.json \
  --bus-backend redis \
  --redis-url "$PAPERCLAW_REDIS_URL" \
  --state-backend postgres \
  --postgres-dsn "$PAPERCLAW_POSTGRES_DSN" \
  --trace-database .paperclaw/traces.sqlite3
```

包括 Redis Streams Consumer Group、`XAUTOCLAIM`、连续逻辑 Ack Cursor、PostgreSQL
Attempt/Terminal/Ordered Outbox 与 `FOR UPDATE SKIP LOCKED` Claim。

## v0.33 Resilience

```text
Coordinator result
  -> terminal state + ordered Outbox in one transaction
  -> idempotent publication
  -> mark delivered
  -> request Ack
```

包含 durable cancellation、failure injection、retry taxonomy 与 DLQ。

## v0.32 Observability Closure

```text
request_id -> team_run_id(request_id) -> durable Trace -> Aggregate Eval
```

```bash
paperclaw-observe \
  --database .paperclaw/traces.sqlite3 \
  --request-id interview-research-check \
  --pricing examples/v0_31/pricing.example.json
```

## Capability Catalog

```bash
paperclaw capabilities --format json
paperclaw capabilities --status shipped
paperclaw capabilities --surface cli
```

当前新增能力：

```text
multiagent.resilient_choreography [shipped]
multiagent.distributed_runtime [shipped]
retrieval.semantic_hybrid [foundation]
evaluation.research_quality [shipped]
project.extensions [shipped]
```

## 验收

```bash
python -m pytest -q tests/unit/projects/test_v037_extension_execution.py tests/unit/projects
python -m pytest -q tests/unit/retrieval/test_v035_semantic_quality.py tests/unit/retrieval
python -m pytest -q -m "not real_llm and not distributed"
python -m ruff check src/paperclaw tests --select E9,F63,F7,F82 --ignore F821
python -m build
```

## 明确边界

- Message delivery 是 at-least-once；
- PostgreSQL 和 Redis 不构成同一事务；
- Trace projection 仍为 SQLite reference backend；
- 外部 Tool 副作用要求 Tool-level idempotency；
- 本地 hashing vector 不等于 transformer embedding；
- 质量评测依赖人工维护的相关性与 claim-support 标签；
- Connector runtime 与 `secret://` resolver 由宿主应用提供；
- timeout/cancellation 会关闭 runtime，但无法强制终止任意宿主线程；
- 不包含 hosted OAuth、扩展市场或 Desktop 安装 UI；
- 项目提供的动态 Python/import-path 加载被明确禁止。
