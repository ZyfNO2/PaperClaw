# PaperClaw v0.04：Context、Session 与 SQLite MVP 收口 SOP

> 版本：v0.04
> 状态：**已完成 / GO（MVP）**
> 更新：2026-07-14
> 目标：证明 PaperClaw 能把结构化 Context 持久化到 SQLite，在预算内生成可解释的模型上下文，并从安全 step boundary 恢复。
> 原则：已经实现的扩展代码可以保留，但不自动成为 v0.04 的完成 Gate。

## 目录

- [1. 为什么重新拆分](#1-为什么重新拆分)
- [2. MVP 用户故事](#2-mvp-用户故事)
- [3. MVP 范围](#3-mvp-范围)
- [4. 最小契约](#4-最小契约)
- [5. 最小运行闭环](#5-最小运行闭环)
- [6. 当前实现快照](#6-当前实现快照)
- [7. 收口工作包](#7-收口工作包)
- [8. MVP 测试与 Gate](#8-mvp-测试与-gate)
- [9. 最小演示与交付](#9-最小演示与交付)
- [10. 后续增强边界](#10-后续增强边界)
- [11. 既有实现参考](#11-既有实现参考)

---

## 1. 为什么重新拆分

旧版 v0.04 虽然名为 MVP，但把下列能力同时放进完成条件：

- schema upgrade、backup、rollback；
- 并发 writer 与完整 idempotency ledger；
- 多角色完整演示；
- migration / lock / crash fault injection；
- pending 副作用、lease 与 active Worker 恢复边界；
- 大量 artifacts 和完整工程审查。

这些能力有价值，但不是证明 Context MVP 成立的最短路径。v0.04 现在只回答三个问题：

1. Session 退出后能否重新打开；
2. Context 是否能在预算内保留关键约束并解释取舍；
3. Runtime 是否只在可证明安全的边界恢复，遇到未知副作用会停止。

### 两种处理方式

| 方案 | 做法 | 成本 | 风险 |
|---|---|---:|---|
| A：保留原验收面 | 把所有已设计能力都做完再宣布 v0.04 完成 | 高 | 继续重复 v0.03 的过度设计 |
| B：硬切 MVP Gate | 保留已有实现，只验收用户可见闭环；其余进入候选池 | 低 | 需要明确“不代表生产级可靠性” |

本 SOP 采用方案 B。

---

## 2. MVP 用户故事

```text
用户让 Agent 完成一个多步文件任务
→ Runtime 保存消息、事件和 ContextItem
→ history 超过预算
→ ContextBuilder 保留目标、约束、失败和 Evidence 引用
→ 生成并保存 ContextSnapshot
→ 在一个已提交 step boundary 退出
→ 重新打开 SQLite Session
→ 文件状态一致时继续
→ 存在未知副作用时返回 recovery_required
```

演示成功即可证明 v0.04 的核心价值。它不需要同时证明任意时刻 crash recovery、跨进程 Worker 恢复或生产级数据库升级。

---

## 3. MVP 范围

### 3.1 必做

- 本地单用户、单项目；
- Python `sqlite3`；
- fresh database schema 初始化；
- Conversation / Run / Message / SessionEvent 基础持久化；
- `ContextItem` 的 source、trust、scope、priority；
- `ContextBuilder` 的角色过滤与确定性选择；
- 保守 token 估算和硬预算；
- 结构化 compaction；
- required constraint 与 Evidence 引用保持；
- immutable `ContextSnapshot`；
- clean reopen；
- step-boundary `Checkpoint`；
- pending mutation 或文件状态变化时 fail-closed。

### 3.2 不作为 v0.04 Gate

- 旧版本数据库 upgrade、自动 backup / restore；
- 多 writer 压测和高并发 SQLite；
- 完整 operation ledger；
- 任意时刻 crash 自动继续；
- Bash、外部 API 和 file mutation 自动 reconciliation；
- durable mailbox、Worker、Task 和 FileLease 恢复；
- Global Verify 和 Semantic Reviewer；
- 自动长期 Memory；
- Dense retrieval、向量数据库或 Knowledge Graph；
- LLM compaction、精确 tokenizer 与 Prompt Cache；
- 完整 MultiAgent 端到端演示。

已经存在的相关实现只算“额外能力候选”，不能反向扩大当前验收范围。

---

## 4. 最小契约

MVP 只冻结以下概念，不冻结所有未来字段：

```text
ContextItem
  item_id
  run_id / task_id
  kind
  content
  source_ref / trust_level
  scope / priority
  estimated_tokens

ContextSnapshot
  snapshot_id
  run_id / role
  included_item_ids
  excluded_items + reason
  rendered_hash
  estimated_tokens / estimator

SessionEvent
  event_id
  run_id
  sequence
  event_type
  payload

Checkpoint
  checkpoint_id
  run_id
  last_committed_sequence
  pending_operations
  file_snapshots
  state_hash
```

硬约束：

- 原始消息、工具结果和 Evidence 是事实源；
- Snapshot、摘要和 Checkpoint 都是派生物；
- hypothesis 不得在压缩后升级为 fact；
- external content 只能作为 data，不得覆盖 Runtime / Role 指令；
- 超预算时返回明确错误，不静默删除硬约束；
- unknown side effect 不得自动重放。

---

## 5. 最小运行闭环

### 5.1 Context 编译

```text
collect
→ validate trust / scope
→ remove expired or superseded items
→ estimate
→ deterministic select
→ compact when necessary
→ verify required IDs
→ persist snapshot
```

MVP 必须保留：

- 当前用户目标；
- 当前 Task 与 acceptance；
- 工具和路径约束；
- 最新失败与 blocker；
- unresolved todo；
- Evidence ID / source reference。

允许优先剔除：重复输出、过期项、已替代项、已完成步骤细节和可重新读取的大段内容。

### 5.2 Session reopen

```text
open existing SQLite
→ load last committed sequence
→ restore materialized state
→ load latest safe checkpoint
→ revalidate file snapshots
→ resume or recovery_required
```

自动 resume 仅要求：

- Checkpoint 存在且可读取；
- 没有 pending mutating operation；
- 文件 snapshot 仍一致；
- state hash 与 schema version 可接受。

任何一项无法证明，返回 `recovery_required`，不尝试“聪明地猜测”。

---

## 6. 当前实现快照

以下仅用于说明 v0.04 最终实现来源，不替代测试验收：

| 能力 | 已观察到的提交 | 状态解释 |
|---|---|---|
| Context contract / SQLite / Repository | `4c2a5f4`、`a08c522` | 已实现并纳入 MVP 回归 |
| SessionService / EventSink | `2a482ab`、`d4eaa5c` | 已实现并纳入 MVP 回归 |
| PocketFlow runtime adapter | `0c68c76`–`af86ebb` | 已实现并纳入 MVP 回归 |
| ContextBuilder / RoleContextView | `94f84f1` | 已实现并纳入 MVP 回归 |
| Compaction | `f7c5336` | 已实现并纳入 MVP 回归 |
| Safe resume boundary | `4968b9c`、`e52ebfc` | 已实现并通过 Phase E Review 修正 |

Phase F 已完成最小闭环验证与留档；后续只从 v0.04.1 候选池按真实失败或下游阻塞提取独立小型 SOP。

---

## 7. 收口工作包

### WP1：最小契约回归

- [x] 对 Context contract、Repository、Session、ContextBuilder、Compaction、Checkpoint、Resume 运行定向测试；
- [x] 修正文档与实现字段漂移；
- [x] 确认未增加新的数据库表或恢复状态。

### WP2：一条集成演示

- [x] 构造超预算的长工具输出并完成 Context 编译；
- [x] 验证 required constraints 和 Evidence refs 保留；
- [x] 保存 Snapshot / Checkpoint，关闭并 reopen；
- [x] 验证安全状态继续、pending mutation 返回 `recovery_required`。

### WP3：最小留档

- [x] 记录测试命令与结果并导出一条演示 Trace；
- [x] 写明 known limitations；
- [x] 同步 README / Context 设计文档；
- [x] 完成只针对 MVP Claim 的独立 Review。

WP1–WP3 已完成，v0.04 判定为 **GO**。发现增强需求只登记，不在当前版本顺手实现。

---

## 8. MVP 测试与 Gate

| 编号 | 场景 | 通过标准 |
|---|---|---|
| M04-01 | fresh database | schema 初始化并可写入 Session |
| M04-02 | clean reopen | 消息、事件和最后 sequence 一致 |
| M04-03 | role scope | 不相关私有 ContextItem 不进入 Snapshot |
| M04-04 | budget overflow | 结果不超预算，选择顺序确定 |
| M04-05 | constraint retention | required IDs 与 Evidence refs 保留率 100% |
| M04-06 | compaction safety | hypothesis 不升级、原始 source 不被覆盖 |
| M04-07 | safe resume | 文件一致且无 pending mutation 时从 checkpoint 恢复 |
| M04-08 | unsafe resume | pending mutation 或文件变化时返回 recovery_required |

### GO

- M04-01–M04-08 全部通过；
- 一条集成演示可复现；
- 未出现 Context 跨 scope 泄漏；
- 未丢失 required constraint / Evidence ref；
- 未自动重放未知副作用；
- 交付物只描述已验证能力。

### NO-GO

- 摘要覆盖或伪造 Evidence；
- 超预算仍发送模型请求；
- Session reopen 后状态或 sequence 漂移；
- unsafe state 被自动 resume；
- 为通过测试修改原始事实或放宽硬约束。

数据库 upgrade、并发 writer、自动 recovery 等增强项失败，不阻止 v0.04 MVP GO，因为它们已不在当前 Gate。

---

## 9. 最小演示与交付

### 演示

只保留一条 3–5 分钟演示：

```text
长任务 → Context 超预算 → 确定性压缩
→ 约束/Evidence 保留 → Snapshot
→ 退出/reopen → safe resume
→ 注入 pending mutation → recovery_required
```

### 交付物

```text
artifacts/v0_04/
├── test_report.md
├── mvp_demo_trace.json
├── known_limitations.md
├── implementation_summary.md
└── file_manifest.txt
```

现有更细的 JSON artifact 可以保留，但不要求为了填满旧清单继续制造报告。

---

## 10. 后续增强边界

后续候选统一进入：

[`PaperClaw_v0.04.1_RuntimeProtocolRecovery_SOP草案.md`](PaperClaw_v0.04.1_RuntimeProtocolRecovery_SOP草案.md)

该文件已降级为增强候选池，不再是“v0.04 完成后必须整体执行”的 SOP。每次最多提取一个独立用户故事重新冻结。

---

## 11. 既有实现参考

| 参考项目 | 必读路径 | 借鉴目标 | 禁止照搬 |
|---|---|---|---|
| AutoResearchClaw | `researchclaw/hitl/context_manager.py` | Context 分区和 artifact summary | 字符硬截断、stage 强耦合 |
| AutoResearchClaw | `researchclaw/hitl/chat.py` | Session 序列化与 reopen | 复制其科研 stage state |
| AutoResearchClaw | `researchclaw/memory/store.py` | provenance、confidence、生命周期字段 | 在 MVP 引入自动长期 Memory |
| AutoResearchClaw | `researchclaw/pipeline/runner.py` | checkpoint 与安全恢复边界 | 任意副作用自动恢复 |
| Draftpaper-loop | `docs/DPL_SCHEMA.md`、`draftpaper_cli/loop_contract.py` | 稳定 ID、原始记录与派生物分离 | 论文流水线数据模型 |
| PaperAgent | `apps/api/app/services/agents/graph/nodes/evidence_context.py` | Evidence Context 与来源追踪 | LangGraph State 强耦合 |

Implementation Summary 只需说明实际借鉴的契约、测试和失败策略，以及为何没有复制原模块。
