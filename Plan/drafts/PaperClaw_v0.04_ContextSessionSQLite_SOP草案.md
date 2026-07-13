# PaperClaw v0.04：Context Engineering、Session 与 SQLite SOP 草案

> 状态：SOP 草案，待 v0.03 完成后冻结  
> 前置：v0.03 MultiAgent 通过验收  
> 目标：让单 Agent 和多 Agent 获得按任务、角色和预算裁剪的上下文，并支持压缩与恢复

> 执行前参考：[`PaperClaw_参考项目与可复用模块索引.md`](../../docs/reference/PaperClaw_参考项目与可复用模块索引.md) 中 v0.04 清单，重点阅读 AutoResearchClaw `hitl/context_manager.py`、`memory/*`，Draftpaper-loop `DPL_SCHEMA.md`，以及 PaperAgent `evidence_context.py`。

## 目录

- [问题、模块与上下文分层](#1-要解决的问题)
- [压缩、持久化与演示](#5-压缩原则)
- [技术选型与遗漏检查](#10-技术选型草案)
- [风险预案与实施阶段](#12-风险推演与预案)
- [验收 Gate 与交付](#14-go--降级--no-go)

## 1. 要解决的问题

- 当前 history 随工具调用线性增长；
- Worker 不应看到与自身 Task 无关的全部会话；
- Coordinator、Worker、Reviewer 需要不同的 Context View；
- 工具大输出会挤占模型窗口；
- 压缩可能丢失用户约束、失败原因和待办；
- Session 中断后无法稳定恢复；
- 多 Agent 共享 dict 容易造成状态污染。

## 2. 核心模块候选

```text
ContextItem
ContextSource
ContextPolicy
ContextBuilder
ContextBudget
ContextSnapshot
CompactionEngine
Checkpoint
TaskState
MemoryStore
RoleContextView
```

## 3. 六层上下文

```text
L0 Runtime Constitution
L1 Role / Mode
L2 Workspace Rules
L3 Task State
L4 Working Context
L5 Retrieved Memory
```

详细基线见：

- [`PaperClaw_上下文系统与提示词工程骨架.md`](../../docs/desgin/PaperClaw_上下文系统与提示词工程骨架.md)

## 4. MultiAgent Context View

| 角色 | 默认看到 |
|---|---|
| Coordinator | 用户目标、Task DAG、Worker Result、全局 Evidence |
| Worker | 单个 AgentTask、允许文件、相关项目规则、局部 history |
| Reviewer | 用户目标、验收条件、Diff、Verify Evidence、已知限制 |

Worker 不默认继承完整 Conversation；Reviewer 不默认读取 Worker 的自由推理。

## 5. 压缩原则

- 原始消息和工具结果可外置，Context 中保留摘要和引用；
- 目标、约束、决策、失败尝试、待办和 Evidence ID 不得被摘要丢失；
- 区分 `fact / decision / hypothesis / todo`；
- 工具结果先做确定性裁剪，再考虑模型摘要；
- 每次压缩生成 ContextSnapshot 和 Checkpoint；
- 压缩前后测 Constraint Retention 和 Compaction Drift。

## 6. 持久化候选

MVP 使用 SQLite：

```text
conversations
runs
messages
task_states
context_items
context_snapshots
checkpoints
memory_items
```

向量数据库不是 v0.04 的前置条件。先用 metadata、全文检索和混合规则验证 Memory 价值。

## 7. 最小演示

1. 运行一个超过上下文预算的工具链；
2. 自动压缩旧 Observation；
3. 用户目标和关键约束保持；
4. 中断进程并恢复 Session；
5. Worker 只收到自身 Task Context；
6. Reviewer 仍能用 Evidence 独立判断。

## 8. 草稿验收方向

- Context 中每个 item 都能说明来源和进入原因；
- 超预算时有确定性裁剪顺序；
- 压缩后关键约束保持率可量化；
- Session Resume 不依赖模型凭空回忆；
- Worker Context 泄漏率为 0；
- 过期 Memory 能失效或被标记；
- ContextSnapshot 可以用于 Offline Replay。

## 9. 暂不设计

- 最终 token 分配算法；
- 向量数据库选型；
- Knowledge Graph；
- 跨项目全局 Memory；
- 自动 Memory 写入策略；
- 完整 Prompt Cache；
- 多用户隔离。

等 v0.03 产出真实 MultiAgent Trace 后，再据此编写 v0.04 正式 SOP。

## 10. 技术选型草案

| 能力 | 推荐选型 | 备选 | 当前判断 |
|---|---|---|---|
| 持久化 | Python `sqlite3` + 显式 Repository | SQLAlchemy | MVP 数据模型较小，先避免 ORM 隐式行为 |
| Schema migration | 版本表 + 顺序 SQL migration | Alembic | 先保持轻量，但 migration 必须从第一版存在 |
| 数据模型 | `dataclasses` + 显式 validator | Pydantic | 与 v0.01 一致，后续 API 边界再评估 Pydantic |
| token 估算 | ModelAdapter 提供 tokenizer；缺失时保守估算 | 固定字符比例 | 不允许把字符数永久当 token 数 |
| 全文搜索 | SQLite FTS5 | Python 扫描 | FTS5 自带全文查询与 `bm25()`，适合本地 MVP |
| Checkpoint | SQLite transaction + immutable snapshot | JSON 文件 | JSON 只保留导出/调试用途 |
| Memory retrieval | metadata + FTS5 起步 | Dense vector | 先证明记忆有用，再引入 embedding |

## 11. 用户尚未覆盖的关键问题

- **数据库 migration**：ContextItem 和 Session 字段会快速变化，不能只 `CREATE TABLE IF NOT EXISTS`。
- **幂等恢复**：恢复时必须知道最后一个已提交事件，避免工具执行两次或重复写文件。
- **事实与摘要分离**：Checkpoint summary 不能覆盖原始 Evidence；摘要是派生物。
- **删除与保留策略**：Session、Trace、工具输出和外部文档需要 retention / purge 边界。
- **Prompt injection**：Retrieved Memory、AGENTS.md、网页和工具结果必须带 trust / source，外部文本不能升级为系统指令。
- **角色隔离**：MultiAgent Worker 只看任务相关 Context；Reviewer 不看实现者自由推理。
- **并发写数据库**：多个 Worker 同时写 SQLite 时要处理 busy timeout、短事务和 writer serialization。
- **跨模型迁移**：不同 tokenizer、context window 和 system message 语义会变化，ContextSnapshot 不能只存渲染后字符串。
- **时钟与顺序**：使用 sequence / revision 判断状态，不只依赖 timestamp。

## 12. 风险推演与预案

| 场景 | 可能后果 | 预案 |
|---|---|---|
| Compaction 把 hypothesis 写成 fact | 后续 Agent 基于错误事实行动 | 强制 fact/decision/hypothesis/todo 类型；Evidence 不可由摘要生成 |
| SQLite 在多 Worker 下 locked | Session 写入失败、状态半完成 | WAL、busy timeout、短事务、单 writer queue；失败回退 append-only journal |
| 恢复后重复执行 Bash | 外部副作用重复发生 | tool_call_id + idempotency key；副作用工具默认需人工确认恢复 |
| Context 预算估算偏低 | Provider 拒绝请求 | 预留安全余量；模型返回 context error 后触发一次确定性二次裁剪 |
| Memory 检索出过时规则 | Agent 使用 stale decision | `valid_from/valid_to/supersedes`；stale item 只能作历史信息 |
| 用户删除文件但 cache 仍旧 | Agent 基于幽灵文件修改 | FileSnapshot hash + mtime + existence recheck |
| Migration 中断 | 数据库不可读 | migration transaction、升级前 backup、schema version、不支持降级时明确阻止启动 |
| 外部文档含指令注入 | Prompt 权限层级被污染 | 所有外部内容封装为 data block；禁止直接拼进 system section |

## 13. 初步实施阶段

### Phase A：状态与数据库契约

- Conversation、Run、Message、TaskState、ContextItem、ContextSnapshot、Checkpoint Schema；
- migration v1；
- Repository protocol；
- transaction 与 idempotency 规则。

### Phase B：ContextBuilder

- 六层收集；
- priority / trust / scope / expiry；
- 去重、冲突、预算与 exclusion reason；
- RoleContextView。

### Phase C：Compaction

- 工具输出确定性裁剪；
- 结构化 Checkpoint；
- fact/decision/hypothesis/todo lint；
- Constraint Retention fixture。

### Phase D：Session Resume

- crash fixture；
- checkpoint restore；
- pending tool reconciliation；
- 文件状态重验；
- MultiAgent task / lease 恢复。

### Phase E：验收

- 多轮长会话；
- 多次压缩漂移；
- SQLite lock / corruption / migration failure injection；
- Windows 路径和中文 Context；
- Offline Replay 一致性。

## 14. GO / 降级 / NO-GO

- `GO`：约束保持、恢复幂等、角色隔离和 migration 全部可复现。
- `降级`：Dense Memory 延后，只保留 SQLite metadata + FTS5。
- `NO-GO`：恢复会重复副作用、摘要可覆盖 Evidence、外部文本可进入高优先级指令、数据库升级无回滚/备份。

## 15. 预期交付

```text
artifacts/v0_04/
├── schema.md
├── migration_report.md
├── context_budget_report.md
├── compaction_eval.json
├── resume_failure_injection.md
└── implementation_summary.md
```
