# PaperClaw

PaperClaw 是一个面向 Coding、Research 与多 Agent 工作流的可审计 Agent Runtime。

本 README 描述当前 **v0.30 stacked Draft 开发线**。`main` 只有在仓库所有者按依赖顺序审查并合并对应 PR 后，才会具备这里列出的能力；Plan、Handoff 或 Draft PR 不等于正式发布。

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
  ↓
v0.28 Project Knowledge Runtime
  ↓
v0.29 Artifact Revisions
  ↓
v0.30 Desktop Product Integration
```

当前顶部开发线对应 Draft PR #59。所有 stacked PR 均保持未合并状态。

## Capability Catalog

PaperClaw 不再简单使用“有/没有”描述能力：

| 状态 | 含义 |
|---|---|
| `shipped` | 已接入正常运行路径并有验收证据 |
| `foundation` | 合同与参考实现完成，但产品整合或外部基础设施仍有限制 |
| `experimental` | 可使用，但接口、生命周期或产品表面仍可能调整 |
| `planned` | 仅进入后续计划，不得描述为已实现 |

查看机器可读事实源：

```bash
paperclaw capabilities
paperclaw capabilities --format json
paperclaw capabilities --status foundation
paperclaw capabilities --surface desktop
```

v0.30 catalog 已明确记录：

- `project.knowledge_runtime`：v0.28 foundation；
- `retrieval.hybrid_rrf`：v0.28 foundation；
- `artifact.revisions`：v0.29 foundation；
- `desktop.product_management`：v0.30 experimental。

## 核心运行层

### Agent、验证与工具

- 有界 ReAct Runtime；
- allowlisted 工具、路径权限与权限二次检查；
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
- 显式 `require_current / allow_stale / disabled` 索引策略；
- 显式 start/stop 的 bounded polling watcher；
- backend-neutral Retriever Protocol；
- deterministic citation-preserving weighted RRF Hybrid fusion。

内置检索仍以本地 lexical BM25 为主。Semantic/Vector backend 只是 adapter seam，不包含托管 embedding 服务或外部向量数据库。

### Multi-Agent、任务与远程执行

- Coordinator / Worker / Reviewer；
- Task DAG、并行 Worker、权限与 FileLease；
- durable background task lifecycle；
- subprocess isolation 与跨平台进程树终止；
- authenticated Remote Worker Gateway；
- generation-fenced durable ownership；
- durable ordered Agent Message Bus foundation。

限制：

- Message Bus 尚未自动接入 Coordinator choreography；
- Remote Gateway 内存幂等只保证同一 Gateway 进程生命周期；
- SQLite fencing 只证明同文件系统多进程竞争安全；
- 没有声称 PostgreSQL、Redis、NATS 或 Kafka 已实现。

## Project Workspace

项目清单：

```text
.paperclaw/project.json
```

初始化与检查：

```bash
paperclaw project --workspace . init --name "My Research Project"
paperclaw project --workspace . show
paperclaw project --workspace . validate
```

Manifest v1：

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

- 固定字段和严格 JSON 数组；
- credential-shaped 字段拒绝；
- 只允许工作区内相对路径；
- `..`、绝对路径、外部/broken symlink 和 symlink manifest 拒绝；
- manifest、知识文件与索引操作都有 byte bound；
- 不隐式访问网络。

## Project Knowledge Runtime

构建、刷新与显式检查：

```bash
paperclaw project --workspace . index
paperclaw project --workspace . refresh
paperclaw project --workspace . watch --once
paperclaw project --workspace . watch --once --rebuild-on-change
```

支持 UTF-8：

```text
.md
.markdown
.txt
```

索引：

```text
.paperclaw/data/project-knowledge.sqlite3
.paperclaw/data/project-index.json
```

每次构建记录文件路径、大小、SHA-256 和 aggregate source fingerprint。

默认 Runtime 使用 `require_current`：只有 fingerprint 当前时才注册 Project Retrieval Source。`allow_stale` 只接受结构有效、单纯源 fingerprint 变化的旧索引；metadata 损坏或 project ID 不匹配继续 fail-closed。

Memory 默认路由为：

```text
~/.paperclaw/memories/USER.md
~/.paperclaw/memories/projects/<project_id>/MEMORY.md
```

USER profile 全局共享，项目经验和约定按 Project 隔离。

## Artifact Revisions

v0.29 引入一等 Product Artifact，独立于 Chat Message 和 Retrieval SourceArtifact。

存储：

```text
.paperclaw/artifacts/
  artifacts.sqlite3
  blobs/sha256/<prefix>/<content_hash>
```

能力：

- stable Artifact ID/type；
- append-only contiguous revisions；
- content-addressed SHA-256 blob；
- Project / Run / Task / Trace source links；
- deeply immutable bounded metadata；
- exact idempotent create/revise；
- conflicting idempotency key fail-closed；
- blob hash/length verification；
- destination-root-confined export；
- default no-overwrite。

CLI：

```bash
paperclaw artifact --workspace . create ...
paperclaw artifact --workspace . list
paperclaw artifact --workspace . show <artifact_id>
paperclaw artifact --workspace . revise <artifact_id> ...
paperclaw artifact --workspace . export <artifact_id> ...
```

当前仍是本地文件/SQLite foundation：没有公共分享、协同编辑、云对象存储或 blob garbage collector。

## Desktop Product Integration

运行：

```bash
paperclaw gui
```

v0.30 在现有 thin pywebview / protected loopback Desktop 上增加 Product Panel：

- Overview：Project、Artifact、Capability 状态；
- Capabilities：版本、成熟度、surface 与限制；
- Project：manifest、validation、index 状态和显式 refresh；
- Artifacts：bounded list、revision detail、latest export。

Desktop 仍然是 projection：

```text
Desktop HTML/JS
  -> allow-listed DesktopAPI
  -> DesktopProductService
  -> CapabilityCatalog / ProjectKnowledgeRuntime / FileArtifactStore
```

安全边界：

- Product API 只针对当前 Workspace；
- Workspace、Artifact root 和数据库 symlink 拒绝；
- 不接受任意 SQLite/Blob 路径；
- export 固定在 `.paperclaw/exports`；
- artifact list、revision history 和 public JSON 均有上限；
- Artifact summary 不返回任意 metadata；
- Product API 不接受或返回 Provider API key、Authorization 或 Cookie；
- UI 使用 `textContent`，不执行 Artifact HTML/Script。

当前 Desktop 不提供：

- Skill 安装/启停；
- Connector OAuth/密钥管理；
- Artifact 编辑；
- Artifact 分享/发布；
- 后台 Project watcher。

## Message Bus 安全边界

v0.27 已修复：

- `AgentMessageBus` 公共导出；
- payload/header JSON 规范化与深层冻结；
- 非字符串 JSON object key 拒绝；
- payload/header/draft byte limit；
- capacity rejection audit 独立事务；
- topic 满容量时 exact idempotent retry 仍返回旧消息。

## 常用入口

```bash
# 单 Agent / Multi-Agent
paperclaw agent "检查这个项目"
paperclaw team --plan plan.json

# TUI / Desktop / Service
paperclaw tui
paperclaw gui
paperclaw api

# 产品能力
paperclaw capabilities --format json
paperclaw project --workspace . validate
paperclaw project --workspace . refresh
paperclaw artifact --workspace . list
```

部分入口需要对应 optional dependency，例如 `.[tui]`、`.[gui]` 或 `.[service]`。

## 明确保留的开发债务

1. **Project-scoped Skills / Connectors**：发现、启停、信任来源、版本、MCP Auth/Permission 与真正的项目级激活。
2. **Aggregate Eval Dashboard**：Task Success、Tool-call Accuracy、协作效率、P50/P95/P99、Token/API Cost 和多运行失败分类。
3. **Message Bus choreography wiring**：Coordinator、Worker、Reviewer 与 durable Task runtime 的消费身份、重试、poison message 和 causal trace。
4. **真实外部设施适配器**：PostgreSQL、Redis、NATS、Kafka 或外部 Vector DB 必须在真实共享服务上验收。
5. **Artifact Lifecycle v2**：Blob GC、分享/发布、协同编辑和可控预览。
6. **Desktop v2**：Skill/Connector 管理、Artifact 编辑、完整 i18n 和更细粒度产品权限。
7. **Hybrid Retrieval v2**：实际 Semantic/Vector adapter、Reranker 与离线质量评估。

## 安全与架构边界

- Secret 不写入 Manifest、Message Bus、ExecutionRequest、Trace 或 Artifact metadata；
- Remote Workspace 由 Worker Host 白名单验证；
- 不允许远程上传任意 Python module/function；
- 网络取消未确认时返回 `UNKNOWN_OUTCOME`；
- stale lease generation 不能 heartbeat、标记 side effect、complete 或 requeue；
- SQLite 多进程证据不等于多机分布式共识；
- Draft PR、Plan 与 foundation 不自动等于正式发布。

## 开发与验收

```bash
python -m pip install -e ".[dev]"
python -m pytest -q -m "not real_llm"
python -m ruff check src/paperclaw tests --select E9,F63,F7,F82 --ignore F821
```

涉及 Provider 的测试必须明确标记 `real_llm`；Fake/Mock、离线 Provider 和真实 Provider 证据必须分别记录。
