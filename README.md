# PaperClaw

PaperClaw 是一个面向 Coding、Research 与多 Agent 工作流的可审计 Agent Runtime。

本 README 描述的是当前 **v0.27 stacked Draft 开发线**。`main` 只有在仓库所有者按顺序审查并合并对应 PR 后才会具备这些能力；Plan 文件或 Draft PR 不等于已发布版本。

## 当前开发栈

```text
main
  ↓
v0.22 Verification Reliability
  ↓
v0.23 Executor Isolation / Subprocess Worker
  ↓
v0.24 Remote Worker Gateway
  ↓
v0.25 Durable Queue Fencing
  ↓
v0.26 Agent Message Bus
  ↓
v0.27 Forgotten Debt / Product Foundation
```

当前 v0.27 开发线对应 Draft PR #56。它不会自动合并，也不声称 SQLite 已具备多机分布式数据库或外部 Broker 能力。

## 能力状态不是二元值

PaperClaw 使用以下成熟度：

| 状态 | 含义 |
|---|---|
| `shipped` | 已接入正常运行路径，并有相应验收证据 |
| `foundation` | 底层合同和参考实现已完成，但产品整合或外部基础设施仍有限制 |
| `experimental` | 可使用，但接口、生命周期或产品表面仍可能调整 |
| `planned` | 仅进入开发债务/计划，不得描述为已实现 |

机器可读事实源：

```bash
paperclaw capabilities
paperclaw capabilities --format json
paperclaw capabilities --status foundation
paperclaw capabilities --surface desktop
```

Capability Catalog 会返回稳定 capability ID、引入版本、成熟度、支持表面、依赖与明确限制。

## 已实现的主要层次

### Agent 与验证

- 有界 ReAct Runtime；
- allowlisted 工具与路径权限；
- deterministic evidence verification；
- semantic acceptance judge 与执行模型解耦；
- Plan Mode、AskUserQuestion 和静态 Skills；
- read-only LSP diagnostics / definition / references / symbols / hover。

### Context、Memory 与 Retrieval

- trust-aware Context Orchestration；
- Session、Checkpoint 与安全恢复；
- bounded user profile / long-term memory；
- `PAPERCLAW.md`、`CLAUDE.md`、`AGENTS.md` 项目说明；
- 本地增量 BM25、citation anchors、grounding 与 abstention；
- v0.27 Project Manifest 将说明文件、知识路径、Skills 与 Connectors 声明放入同一项目边界。

### Multi-Agent 与任务执行

- Coordinator / Worker / Reviewer；
- Task DAG、并行 Worker、权限与 FileLease；
- durable background task lifecycle；
- subprocess isolation 与跨平台进程树终止；
- authenticated Remote Worker Gateway；
- generation-fenced queue ownership；
- durable ordered Agent Message Bus foundation。

当前限制：Message Bus 尚未自动接入 Coordinator choreography；Remote Gateway 的内存幂等只保证同一 Gateway 进程生命周期；SQLite fencing 只证明同文件系统多进程竞争安全。

### Trace 与产品表面

- durable redacted Trace；
- inspect / replay / per-trace evaluation；
- CLI、TUI、Desktop thin client 与 Service API；
- Provider/Model policy 与 bounded fallback；
- v0.27 Capability Catalog 与 Project CLI。

## Project Workspace

v0.27 引入工作区内的项目清单：

```text
.paperclaw/project.json
```

初始化：

```bash
paperclaw project --workspace . init --name "My Research Project"
```

检查：

```bash
paperclaw project --workspace . show
paperclaw project --workspace . validate
```

项目清单 v1 可以声明：

```json
{
  "schema_version": 1,
  "project_id": "my-research-project",
  "name": "My Research Project",
  "instruction_files": ["PAPERCLAW.md", "CLAUDE.md", "AGENTS.md"],
  "knowledge_paths": ["knowledge"],
  "enabled_skills": [],
  "enabled_connectors": [],
  "data_directory": ".paperclaw/data"
}
```

安全规则：

- 只允许工作区内相对路径；
- `..`、绝对路径、外部 symlink 和 symlink manifest 被拒绝；
- manifest 只允许固定字段和严格 JSON 数组；
- credential-shaped 字段被拒绝；
- manifest、知识文件与索引操作都有 byte bound；
- 不会隐式访问网络。

## Project Knowledge

构建项目本地索引：

```bash
paperclaw project --workspace . index
```

当前支持 UTF-8 Markdown 和纯文本：

```text
.md
.markdown
.txt
```

索引产生：

```text
.paperclaw/data/project-knowledge.sqlite3
.paperclaw/data/project-index.json
```

每次构建会记录知识文件路径、大小、SHA-256 和 source fingerprint。正常 Runtime 只会在 metadata 与当前知识文件 fingerprint 一致时注册 `project.bm25_retrieval`；缺失或 stale 索引不会被静默使用。

当前 Project Knowledge 是本地 lexical BM25 foundation，不包含向量 Embedding、Hybrid Search、Reranker 或后台文件 watcher。

## Message Bus 安全修复

v0.27 对 v0.26 审查发现的债务进行了修复：

- `AgentMessageBus` 正式公开导出；
- payload/header 在构造时 JSON 规范化并深层冻结；
- 修改原始 dict/list 不会改变已校验消息或幂等 digest；
- 非字符串 JSON object key 被拒绝，不做静默强制转换；
- payload、headers 和完整 draft 有独立 byte limit；
- topic 容量拒绝审计在独立事务中持久化，不再随业务异常回滚；
- 满容量时，同内容幂等重试仍可返回既有消息。

## 常用入口

```bash
# 单 Agent
paperclaw agent "检查这个项目"

# Multi-Agent
paperclaw team --plan plan.json

# TUI / Desktop / Service
paperclaw tui
paperclaw gui
paperclaw api

# 能力与项目
paperclaw capabilities --format json
paperclaw project --workspace . validate
paperclaw project --workspace . index
```

部分入口需要对应 optional dependency，例如 `.[tui]`、`.[gui]` 或 `.[service]`。

## 明确保留的开发债务

以下内容没有在 v0.27 冒充已实现：

1. **Artifact revisions**：一等 Artifact ID、不可变 revision、Run/Task/Trace 来源、预览、编辑、导出与分享策略。
2. **Project-scoped Skills / Connector 管理**：发现、启停、信任来源、版本、MCP Auth/Permission 状态与 Desktop UI。
3. **Aggregate Eval Dashboard**：Task Success、Tool-call Accuracy、协作效率、P50/P95/P99、Token/API Cost 和多运行失败分类。
4. **Message Bus choreography wiring**：Coordinator、Worker、Reviewer 和 durable Task runtime 的消费身份、重试与失败策略。
5. **真实外部基础设施适配器**：PostgreSQL、Redis、NATS 或 Kafka 必须在实际共享服务上通过同等幂等、fencing、ordering 和恢复矩阵。
6. **Project Knowledge v2**：向量检索、Hybrid Search、Reranker、stale-index policy 与 watcher。
7. **Desktop 产品整合**：Capabilities、Projects、Skills、Connectors、Artifacts 的统一管理表面。

详细审计和开发计划：

```text
Plan/PaperClaw_v0.27_Forgotten_Debt_Product_Foundation.md
```

## 安全与架构边界

- Secret 不写入 manifest、Message Bus payload、ExecutionRequest、Trace 或普通配置文件；
- Remote Workspace 路径由 Worker Host 白名单验证；
- 不允许远程上传任意 Python module/function；
- 网络取消未确认时返回 `UNKNOWN_OUTCOME`，不伪造成功取消；
- stale lease generation 不能 heartbeat、标记 side effect、complete 或 requeue；
- SQLite 多进程测试不等价于多机分布式共识；
- Draft PR、Plan 和基础合同不自动等价于最终产品能力。

## 开发与验收

```bash
python -m pip install -e ".[dev]"
python -m pytest -q -m "not real_llm"
python -m ruff check src/paperclaw tests --select E9,F63,F7,F82 --ignore F821
```

涉及 Provider 的测试必须明确标记 `real_llm`；Fake/Mock、离线 Provider 和真实 Provider 证据必须分开记录。
