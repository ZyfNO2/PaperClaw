# PaperClaw v0.04：Context Engineering、Session 与 SQLite MVP SOP

> 版本：v0.04  
> 状态：**已冻结 / READY FOR IMPLEMENTATION**  
> 前置：v0.03 进程内 MultiAgent MVP 已完成并通过验收  
> 目标：交付按角色裁剪、受预算约束、可持久化、可确定性压缩的 Context / Session 基线，并支持安全的 step-boundary resume。

> 本文件同时记录 v0.04.1 的延后范围，但 **v0.04 实施不得顺手实现 v0.04.1**。任意时刻 crash recovery、pending 副作用自动协调、完整消息通道和 Global Verify 均不属于 v0.04 完成条件。

## 1. 版本拆分结论

### 1.1 v0.04：本次执行范围

v0.04 只交付以下闭环：

```text
Raw Session Data
    ↓ persist
SQLite Session Store
    ↓ query
ContextBuilder
    ↓ role / trust / scope / budget
RoleContextView
    ↓ deterministic compaction
ContextSnapshot
    ↓ model call
Agent Runtime
    ↓ step boundary
Checkpoint
```

必须完成：

- `ContextItem`、`ContextSource`、`ContextPolicy`、`ContextBudget`；
- Coordinator / Worker / Reviewer 的 `RoleContextView`；
- SQLite schema、migration v1、Repository protocol；
- append-only `SessionEvent` 与单调 sequence；
- `ContextSnapshot` 与 `Checkpoint` 分离；
- 确定性裁剪和结构化压缩；
-关键约束、决策、失败和 Evidence 引用保持；
-正常退出后的 Session reopen；
-仅在安全 step boundary 上恢复；
-恢复前文件状态与 pending operation 检查；
-离线 fixture、故障注入和可复现验收报告。

### 1.2 v0.04.1：延后范围

下列能力只登记，不在 v0.04 中实现：

- 任意时刻进程崩溃后的自动继续；
-运行中的 Bash / file write /外部 API 自动恢复；
- pending side-effect reconciliation engine；
- durable FileLease 和 MultiAgent active-worker 恢复；
-完整 `AgentMessage` mailbox、recipient 路由和 dedup；
- Global Verify；
- Reviewer 语义审查和 acceptance-claim 覆盖；
- failed Worker 的完整 retry / repair 状态机；
-跨 Session 自动长期 Memory；
-Dense retrieval、向量数据库和 Knowledge Graph；
-跨机器、多用户和分布式 Session。

## 2. 要解决的问题

当前 Runtime 存在以下结构性问题：

- history 随模型和工具调用线性增长；
-工具大输出会挤占有效上下文；
-Worker 不应看到与自身 Task 无关的完整 Conversation；
-Coordinator、Worker、Reviewer 需要不同 Context View；
-压缩可能丢失用户约束、失败原因、决策和未完成事项；
-进程退出后缺少稳定 Session reopen；
-多 Agent 共享可变 dict 容易造成状态污染；
-当前 Prompt 无法解释每条上下文的来源、信任等级和进入原因。

v0.04 的目标不是“让模型记得更多”，而是让 Runtime 能回答：

1. 这条上下文来自哪里；
2. 为什么允许该角色看到；
3. 为什么进入或未进入本次 Prompt；
4. 是否被压缩、替代、过期或撤销；
5. Session 可以从哪个已提交边界安全恢复。

## 3. In Scope 与 Out of Scope

### 3.1 In Scope

-单项目、单用户、本地进程；
-Python `sqlite3`；
-显式 schema migration；
-Session、Run、Message、Event、TaskState 持久化；
-Context provenance、trust、priority、scope、expiry；
-角色上下文隔离；
-token 预算和安全余量；
-确定性裁剪；
-结构化 compaction；
-immutable ContextSnapshot；
-step-boundary Checkpoint；
-clean reopen 和 safe resume；
-Windows 路径、UTF-8 和中文上下文；
-Offline fixture 与 replay 输入导出。

### 3.2 Out of Scope

-自动长期记忆；
-跨项目全局 Memory；
-自动 Memory 写入策略；
-Dense vector retrieval；
-Knowledge Graph；
-完整 Prompt Cache；
-任意时刻 crash resume；
-pending mutating tool 自动重放；
-MultiAgent durable lease recovery；
-完整消息总线和 Global Verify；
-多用户隔离；
-远程数据库或跨机器运行。

## 4. 核心数据契约

### 4.1 ContextSource

```python
@dataclass(frozen=True)
class ContextSource:
    source_type: str       # user | runtime | file | tool | worker_result | evidence | external
    source_ref: str        # message_id / event_id / artifact_id / file path 等
    trust_level: str       # system | trusted_local | user | tool_output | external_untrusted
    created_sequence: int
```

规则：

- `external_untrusted` 永远只能作为 data，不得进入 Runtime Constitution 或 Role 指令层；
- source 必须可回溯；
-摘要不得伪造新的 Evidence source；
-文件内容必须绑定 path 和读取时 hash。

### 4.2 ContextItem

```python
@dataclass(frozen=True)
class ContextItem:
    item_id: str
    run_id: str
    task_id: str | None
    layer: str             # L0 | L1 | L2 | L3 | L4 | L5
    kind: str              # fact | decision | hypothesis | todo | constraint | evidence_ref | observation
    content: str
    source: ContextSource
    priority: int
    scope: list[str]       # coordinator / reviewer / worker:<task_id> / shared
    valid_from_sequence: int
    valid_to_sequence: int | None
    supersedes_item_id: str | None
    estimated_tokens: int
    metadata: dict
```

硬约束：

- `fact` 必须来自用户、确定性工具结果或已有 Evidence；
-模型生成内容默认不能直接升级为 `fact`；
- `hypothesis` 不得在 compaction 后变成 `fact`；
- `supersedes_item_id` 只改变有效性，不删除原始记录；
-原始 Evidence 不被 ContextItem 内容覆盖。

### 4.3 ContextBudget

```python
@dataclass(frozen=True)
class ContextBudget:
    max_input_tokens: int
    reserved_output_tokens: int
    safety_margin_tokens: int
    max_single_item_tokens: int
    max_tool_output_tokens: int
```

有效输入预算：

```text
usable_input = max_input_tokens
             - reserved_output_tokens
             - safety_margin_tokens
```

默认安全余量不得低于模型窗口的 10%。ModelAdapter 无 tokenizer 时使用保守估算，并在 Snapshot 中记录 estimator 类型。

### 4.4 ContextSnapshot

`ContextSnapshot` 表示 **某一次模型调用实际看到的上下文**，不等于恢复点。

```python
@dataclass(frozen=True)
class ContextSnapshot:
    snapshot_id: str
    run_id: str
    agent_id: str
    task_id: str | None
    role: str
    source_item_ids: list[str]
    excluded_items: list[dict]  # item_id + exclusion_reason
    rendered_hash: str
    estimated_tokens: int
    estimator: str
    created_sequence: int
```

要求：

- immutable；
-每个 included / excluded item 都有可解释原因；
-存 source item ID，不只存最终 Prompt 字符串；
-渲染字符串可导出，但不能作为唯一事实源。

### 4.5 SessionEvent

```python
@dataclass(frozen=True)
class SessionEvent:
    event_id: str
    conversation_id: str
    run_id: str
    sequence: int
    event_type: str
    payload: dict
    created_at: str
```

规则：

- `sequence` 在单个 Run 内严格单调递增；
- `SessionEvent` append-only；
-不得只依赖 timestamp 判断顺序；
-重复 `event_id` 必须幂等拒绝或返回既有记录；
-事件 payload 必须带 schema version。

### 4.6 Checkpoint

`Checkpoint` 表示 **Runtime 可以判断能否安全恢复的状态边界**。

```python
@dataclass(frozen=True)
class Checkpoint:
    checkpoint_id: str
    run_id: str
    last_committed_sequence: int
    task_state_revision: int
    budget_state: dict
    pending_operations: list[dict]
    file_snapshots: list[dict]
    state_hash: str
    schema_version: int
    created_at: str
```

Checkpoint 必须能回答：

-恢复从哪个 event sequence 开始；
-是否存在未决副作用；
-当前 Task / budget 状态；
-关键文件是否仍与 checkpoint 一致；
-能否自动恢复，或必须进入 `recovery_required`。

## 5. SQLite Schema 与权威状态

### 5.1 v0.04 最小表

```text
schema_migrations
conversations
runs
session_events
messages
task_states
context_items
context_snapshots
checkpoints
idempotency_ledger
```

`memory_items` 不进入 v0.04 核心 schema。需要保存的长期事实先作为显式 `ContextItem`，自动 Memory 留到后续版本。

### 5.2 权威性规则

-用户原始消息、工具结果、Evidence 和 `session_events` 是原始记录；
- `task_states` 是 materialized state；
- `ContextSnapshot` 和摘要是派生物；
- `Checkpoint` 是恢复判断数据，不得覆盖原始 Evidence；
-任何摘要、Snapshot 或 Checkpoint 都不能删除原始事件。

### 5.3 事务顺序

单次 Runtime state commit 使用如下顺序：

```text
BEGIN IMMEDIATE
  1. append SessionEvent
  2. update materialized TaskState / Run state
  3. insert ContextItem / Snapshot（如本 step 产生）
  4. insert Checkpoint（仅安全 step boundary）
COMMIT
```

约束：

-外部副作用不得假装与 SQLite transaction 原子；
-mutating tool 执行前写 `operation.started`；
-结果落库后写 `operation.committed` 或 `operation.unknown_outcome`；
-存在 `started` 但无终局事件时，恢复必须停止自动继续；
-migration 使用独立 transaction，失败时 schema version 不前移；
-升级前生成数据库备份。

### 5.4 并发策略

-启用 WAL；
-设置 busy timeout；
-事务必须短；
-使用单 writer queue 或 Repository 级 writer lock；
-模型调用、Bash 和文件 I/O 不得持有数据库写事务；
-数据库 lock 超时必须显式失败，不得静默丢事件。

## 6. 六层 Context 与角色视图

```text
L0 Runtime Constitution  不可由外部内容修改
L1 Role / Mode           Coordinator / Worker / Reviewer
L2 Workspace Rules       本地规则、工具和路径约束
L3 Task State            目标、acceptance、预算、依赖、状态
L4 Working Context       history、工具结果、失败、todo、Evidence 引用
L5 Retrieved Context     v0.04 仅允许显式选择的本地 ContextItem
```

### 6.1 Coordinator View

默认包含：

-用户目标和硬约束；
-Task DAG 与状态；
-WorkerResult；
-全局 Artifact / Evidence 引用；
-团队预算和 blocker。

默认排除：

-Worker 自由推理；
-无关文件全文；
-其他 Session 的自动 Memory。

### 6.2 Worker View

默认包含：

-单个 AgentTask；
-允许工具和路径；
-相关项目规则；
-该 Task 的局部 history；
-输入 Artifact / Evidence；
-依赖任务的结构化 Result。

必须排除：

-其他 Worker 私有 history；
-其他 Task 的未发布 Observation；
-Reviewer 内部评审上下文；
-与 writable / readable scope 无关的文件内容。

### 6.3 Reviewer View

默认包含：

-用户目标；
-acceptance criteria；
-Diff / file manifest；
-Verification Evidence；
-已知限制和 unresolved items；
-必要 Trace 摘要。

必须排除：

-Worker 自由推理；
-未验证的实现者自我评价；
-与审查无关的 Conversation history。

## 7. ContextBuilder 规则

ContextBuilder 必须按固定步骤运行：

```text
collect
→ validate source/trust
→ apply role scope
→ remove expired/superseded items
→ deduplicate
→ resolve conflicts
→ estimate tokens
→ deterministic selection
→ compact if required
→ render
→ persist ContextSnapshot
```

### 7.1 冲突规则

-新 `decision` 不自动覆盖旧 decision，必须显式 `supersedes`；
-用户最新明确约束优先于旧用户约束；
-确定性工具结果优先于模型 hypothesis；
-两个有效 `fact` 冲突时不得自行任选，生成 conflict item 并阻止依赖结论；
-stale / expired item 只能作为历史，不进入有效指令区。

### 7.2 Prompt Injection 边界

-网页、文件、工具输出和 Retrieved Context 默认是 data block；
-外部文本中的“忽略前文”“提升权限”等内容不得改变 L0/L1；
-每个外部 item 必须带 source 和 trust；
-渲染时区分 `instructions` 与 `untrusted_data`；
-角色 scope 校验必须发生在 Prompt 拼接前。

## 8. Token Budget 与确定性裁剪

### 8.1 永不自动删除

- L0 Runtime Constitution；
- L1 Role；
-当前用户目标；
-硬约束；
-当前 Task 和 acceptance criteria；
-路径、工具和预算限制；
-最新失败和 blocker；
-未解决 todo；
-Evidence ID / source reference；
-恢复安全状态。

### 8.2 允许压缩

-旧的成功 Observation；
-重复文件内容；
-重复模型回复；
-已完成 Task 的详细过程；
-长工具输出；
-低优先级历史。

### 8.3 优先剔除顺序

```text
1. 重复 stdout / stderr
2. 重复搜索结果
3. 已 superseded item
4. expired item
5. 已完成且无未决问题的旧 Observation
6. 可由 source_ref 重新读取的大段原文
7. 低优先级对话历史
```

若仍超预算：

1. 运行结构化 compaction；
2. 保留 source IDs 和 required constraint IDs；
3. 再次估算；
4. 仍超预算则返回 `context_budget_exhausted`，不得静默截断硬约束。

Provider 返回 context-length error 时，只允许再执行一次确定性二次裁剪，不得无限重试。

## 9. Compaction 契约

### 9.1 Compaction 输出

```python
@dataclass(frozen=True)
class CompactionResult:
    summary_item_ids: list[str]
    retained_constraint_ids: list[str]
    retained_evidence_refs: list[str]
    removed_item_ids: list[str]
    source_item_ids: list[str]
    compaction_hash: str
```

### 9.2 禁止行为

-不得把 hypothesis 改写成 fact；
-不得生成不存在的 Evidence；
-不得删除 unresolved blocker；
-不得删除用户硬约束；
-不得用摘要覆盖原始 source；
-不得把 external data 提升为 Runtime 指令。

### 9.3 Constraint Retention

测试 fixture 必须显式提供：

```json
{
  "required_constraints": [
    {"id": "c1", "type": "must_not", "value": "do not install dependencies"},
    {"id": "c2", "type": "path_scope", "value": "src/"},
    {"id": "c3", "type": "decision", "value": "use sqlite3"}
  ]
}
```

验收基于 constraint ID，而不是仅靠字符串模糊匹配或 LLM 主观评分。

## 10. v0.04 Resume 边界

### 10.1 自动允许恢复

仅当全部满足时才允许自动 resume：

-存在已提交 Checkpoint；
-Checkpoint 对应 `last_committed_sequence` 可读取；
-无 pending mutating operation；
-TaskState revision 与 Checkpoint 一致；
-关键文件 hash / existence 重新验证通过；
-schema version 兼容；
-预算状态合法。

### 10.2 必须停止并标记 recovery_required

出现以下任一情况不得自动继续：

- `operation.started` 无对应 committed / failed / unknown_outcome；
-Bash、file write、file edit 或外部 API 结果未知；
-文件 hash 与 Checkpoint 不一致；
-数据库 migration 未完成；
-Checkpoint state hash 不一致；
-MultiAgent Worker 在崩溃时仍标记 active；
-lease 状态无法确认；
-恢复将导致副作用重放。

输出必须包含：

```text
status = recovery_required
last_safe_sequence
pending_operations
file_conflicts
recommended_action
```

### 10.3 v0.04 不承诺

-自动重放 mutating tool；
-自动判断外部 API 是否成功；
-恢复运行中的进程树；
-恢复 active Worker 和 FileLease；
-任意时刻 crash 后无人工介入继续。

## 11. 实施阶段

### Phase A：数据契约与 migration

- [ ] A1. 定义 ContextSource / ContextItem / ContextBudget；
- [ ] A2. 定义 SessionEvent / ContextSnapshot / Checkpoint；
- [ ] A3. 建立 schema_migrations 和 migration v1；
- [ ] A4. 实现 Repository protocol；
- [ ] A5. 实现 WAL、busy timeout 和 writer serialization；
- [ ] A6. 实现升级前 backup 和 migration rollback fixture。

### Phase B：Session persistence

- [ ] B1. Conversation / Run / Message 持久化；
- [ ] B2. append-only SessionEvent 与单调 sequence；
- [ ] B3. TaskState revision；
- [ ] B4. idempotency ledger；
- [ ] B5. 正常退出后 reopen；
- [ ] B6. 原始 Evidence 与派生摘要分离。

### Phase C：ContextBuilder 与 RoleContextView

- [ ] C1. 六层 Context 收集；
- [ ] C2. trust / priority / scope / expiry；
- [ ] C3. Coordinator / Worker / Reviewer View；
- [ ] C4. conflict / supersedes / stale 规则；
- [ ] C5. inclusion / exclusion reason；
- [ ] C6. Prompt injection 数据边界。

### Phase D：Budget 与 Compaction

- [ ] D1. tokenizer adapter 与保守 fallback；
- [ ] D2. 确定性裁剪顺序；
- [ ] D3. 工具输出裁剪；
- [ ] D4. 结构化 compaction；
- [ ] D5. Constraint Retention fixture；
- [ ] D6. Compaction Drift fixture；
- [ ] D7. immutable ContextSnapshot。

### Phase E：Safe resume

- [ ] E1. step-boundary Checkpoint；
- [ ] E2. clean reopen；
- [ ] E3. last committed sequence restore；
- [ ] E4. pending operation 检测；
- [ ] E5. 文件 hash / existence 重验；
- [ ] E6. `recovery_required` 输出；
- [ ] E7. 禁止未知副作用自动重放。

### Phase F：集成与留档

- [ ] F1. 单 Agent 长上下文演示；
- [ ] F2. MultiAgent RoleContextView 演示；
- [ ] F3. 多次压缩演示；
- [ ] F4. SQLite lock / migration failure injection；
- [ ] F5. Windows 路径与中文 Context；
- [ ] F6. 生成 artifacts/v0_04；
- [ ] F7. 更新 README 和架构文档；
- [ ] F8. 独立 Reviewer 审核实现与证据。

## 12. 测试与验收

| 编号 | 场景 | 通过标准 |
|---|---|---|
| C-01 | RoleContextView | Worker A 看不到 Worker B 私有 ContextItem |
| C-02 | Reviewer 隔离 | Reviewer 看不到 Worker 自由推理 |
| C-03 | Provenance | 每个 included item 可回溯 source_ref |
| C-04 | Exclusion reason | 每个未进入 Prompt 的候选 item 有原因 |
| C-05 | Budget overflow | 按固定顺序裁剪且最终不超 usable_input |
| C-06 | Constraint retention | required constraint ID 保留率 100% |
| C-07 | Evidence integrity | compaction 不生成、不修改 Evidence |
| C-08 | Hypothesis safety | hypothesis 不得升级为 fact |
| C-09 | Repeated compaction | 多轮压缩后 required IDs 无漂移 |
| C-10 | Injection boundary | external item 不得进入 L0/L1 |
| S-01 | Fresh migration | 空库 migration v1 成功 |
| S-02 | Upgrade migration | 旧 schema 可升级且数据保持 |
| S-03 | Migration failure | transaction 回滚，version 不前移 |
| S-04 | Concurrent writers | 无未处理 database is locked，事件不丢失 |
| S-05 | Event idempotency | 重复 event_id 不产生重复状态 |
| S-06 | Sequence | 单 Run sequence 严格递增 |
| S-07 | Session reopen | 正常退出重开后状态和预算一致 |
| R-01 | Step-boundary resume | 从最后 committed checkpoint 恢复 |
| R-02 | Pending Bash | 不自动重放，返回 recovery_required |
| R-03 | Pending file write | 不自动重放，返回 recovery_required |
| R-04 | External file change | hash 重验失败并停止恢复 |
| R-05 | Corrupt checkpoint | state_hash 失败并停止恢复 |
| R-06 | Active Worker marker | 不尝试自动恢复 MultiAgent active Worker |
| P-01 | Provider context error | 最多一次二次裁剪，不无限重试 |
| P-02 | Token estimator fallback | Snapshot 记录 estimator 和安全余量 |

### 12.1 硬门槛

- Worker Context 跨 Task 泄漏：0；
- Reviewer 获得 Worker 自由推理：0；
- required constraint 丢失：0；
-摘要伪造 Evidence：0；
-外部文本升级为高优先级指令：0；
-SessionEvent 丢失或 sequence 重复：0；
-migration 失败后 schema 半升级：0；
-未知副作用被自动重放：0；
-Context 超预算后仍发往 Provider：0。

## 13. 最小演示

1. 创建一个超过 ContextBudget 的长工具链；
2. ContextBuilder 对工具输出确定性裁剪；
3. required constraint ID 和 Evidence 引用全部保留；
4. 保存 ContextSnapshot；
5. 正常退出并 reopen Session；
6. 从安全 step boundary 继续；
7. 构造 pending Bash，恢复返回 `recovery_required`；
8. 并行两个 Worker，证明彼此私有 Context 不可见；
9. Reviewer 只收到目标、Diff、Evidence 和限制。

## 14. 交付物

```text
artifacts/v0_04/
├── schema.md
├── migration_report.md
├── context_contract.md
├── role_context_matrix.md
├── context_budget_report.md
├── compaction_eval.json
├── constraint_retention_fixture.json
├── resume_boundary_report.md
├── failure_injection_report.md
├── session_reopen_trace.json
├── file_manifest.txt
└── implementation_summary.md
```

## 15. GO / NO-GO

### GO

同时满足：

- Phase A–F 全部完成；
-测试矩阵全部通过；
-硬门槛无例外；
-migration、角色隔离、约束保持和 safe resume 可复现；
-文档没有宣称支持任意时刻 crash recovery；
-独立 Reviewer 确认证据与实现一致。

### NO-GO

出现任一项：

-恢复会重复副作用；
-摘要可以覆盖原始 Evidence；
-Worker 能看到其他 Task 私有上下文；
-外部文本可进入 L0/L1；
-数据库升级无事务或无备份；
-ContextBuilder 静默丢失硬约束；
-Snapshot 只存最终 Prompt、无法回溯 source item；
-pending mutating operation 被自动继续。

## 16. v0.04.1 后续执行草案

v0.04 完成后，v0.04.1 再按两个独立工作包执行，禁止合并成一次大提交。

### Work Package A：Runtime protocol closure

- AgentMessage mailbox 与 recipient routing；
-message dedup / attempt / idempotency；
-Global Verify；
-Reviewer acceptance-claim coverage；
-failed Worker retry / repair 状态机；
-完整 stop_reason、provider、model、contract_id Trace。

### Work Package B：Recovery reconciliation

- arbitrary crash fixture；
-pending Bash / write / external API reconciler；
-durable Worker / Task state；
-durable lease reconciliation；
-人工确认与 recovery decision UI；
-重复副作用防护和故障注入。

v0.04.1 的进入条件：

- v0.04 GO；
-所有 mutating tool 已具备 operation ID；
-SessionEvent / Checkpoint 契约冻结；
-未知副作用统一进入 `recovery_required`；
-不得依赖模型自由文本判断副作用是否已发生。

## 17. 实施者约束

-不要引入向量数据库；
-不要引入 SQLAlchemy，除非显式变更 SOP；
-不要实现自动长期 Memory；
-不要实现任意时刻 crash resume；
-不要重构 v0.03 MultiAgent 调度器，除非是接入 Context 接口所必需；
-不要把 v0.04.1 项目标记为 v0.04 已完成；
-每个 Phase 单独提交并附测试证据；
-发现范围外缺口时记录到 implementation_summary，不得顺手扩大实现。
