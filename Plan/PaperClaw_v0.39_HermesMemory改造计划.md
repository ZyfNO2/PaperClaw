# PaperClaw v0.39：Hermes-Inspired Memory Architecture 改造计划

> 版本：v0.39  
> 状态：PROPOSED / 待实施  
> 前置版本：PaperClaw v0.38  
> 目标：在不重构现有 Context / Session / QueryEngine Runtime 的前提下，为 PaperClaw 增加真正的跨 Session 长期 Memory，并吸收 Hermes Memory 的核心生命周期思想。

---

## 1. 背景与当前仓库事实

PaperClaw 当前已经具备：

```text
Conversation
Run
SessionEvent
Message
TaskState
ContextItem
ContextSnapshot
Checkpoint
Artifact / Evidence
QueryEngine
Trace / Eval
```

v0.04 Context Runtime 已定义六层 Context：

```text
L0 Runtime Constitution
L1 Role / Agent Instructions
L2 Task State
L3 Session / Conversation Context
L4 Evidence / Working Context
L5 Retrieved Memory
```

但当前实现中，L5 Retrieved Memory 仍未形成正式长期 Memory 子系统；已有设计文档也明确将 `memory_items` 延后。因此 v0.39 不重新设计 Context/Session，而是在现有架构上补齐长期 Memory。

本版本借鉴 Hermes 的以下思想：

```text
长期 Memory
    ↓
Session / Conversation 开始
    ↓
Frozen Memory Snapshot
    ↓
稳定 Prompt Prefix

Session 内写 Memory
    ↓
立即持久化
    ↓
当前 Session 不刷新 Frozen Snapshot
    ↓
下一 Session 生效
```

PaperClaw 不复制 `MEMORY.md / USER.md` 的平面文件实现，而是实现：

> Structured + Scoped + Provenance-Aware + Auditable Memory Runtime

---

## 2. 核心设计结论

必须严格区分以下数据对象：

| 类型 | 生命周期 | 作用域 | 自动进入 Prompt | 主要职责 |
|---|---|---|---|---|
| SessionEvent | 永久 | Run | 否 | 发生过什么 |
| Message / Transcript | 永久 | Conversation | 当前会话历史 | 用户和 Agent 说过什么 |
| ContextSnapshot | 永久 | Model Call | 否 | 某次模型实际看到了什么 |
| Checkpoint | Run | Run | 否 | 从哪里安全恢复 |
| Artifact | 长期 | Project / Task | 按需 | Agent 产生了什么 |
| Evidence | 长期 | Project | 按需检索 | 什么事实有来源依据 |
| Memory | 长期 | User / Project | 有界注入 | 以后应该持续记住什么 |

必须坚持：

```text
Event != Memory
Transcript != Memory
Artifact != Memory
Evidence != Memory
Checkpoint != Memory
```

Memory 是从历史、Evidence、项目状态中提炼出的高密度长期知识层，不是历史存储的替代品。

---

## 3. v0.39 目标

### M1. 跨 Session 保留关键知识

适合 Memory：

```text
PaperClaw 使用 Python 3.12
QueryEngine 必须保持 thin façade
external_untrusted 不得进入 L0/L1
用户明确确认的长期项目约束
稳定 workflow 与重要 lesson
```

### M2. 不保存低价值 Session 噪声

默认不得写入 Memory：

```text
临时 stdout / stderr
一次性错误日志
完整代码文件
完整论文正文
完整聊天记录
raw tool output
```

它们继续留在 SessionEvent、Transcript、Artifact 或 Evidence。

### M3. 可追溯

每条 Memory 必须能回答：

```text
从哪里来？
哪个 Run 创建？
什么 sequence 创建？
是否用户确认？
是否引用 Evidence / Artifact？
替代了哪条旧 Memory？
```

### M4. Scope 隔离

v0.39 MVP 只支持：

```text
USER
PROJECT
```

不在本版引入 organization/team/worker/reviewer/task 临时 Memory。

---

## 4. Scope 语义

### 4.1 USER Scope

跨 Project 可见，适合：

```text
用户长期偏好
稳定沟通偏好
长期工作习惯
用户明确要求记住的信息
```

### 4.2 PROJECT Scope

只在当前 PaperClaw Project 中可见，适合：

```text
项目架构约束
技术栈
已确认设计决定
长期 workflow
已知工具限制
项目 convention
```

PROJECT Memory 绝不能泄漏到其他 Project。

---

## 5. 两层 Memory 模型

```text
                  Long-Term Memory
                         │
            ┌────────────┴────────────┐
            │                         │
      Pinned Memory              Recall Memory
     高频核心记忆                长尾可检索记忆
            │                         │
 Session-start frozen            per-turn search
            │                         │
 Stable prompt prefix       dynamic L5 context
```

### 5.1 Pinned Memory

特点：

```text
数量少
价值高
硬预算
Session/Conversation 开始时冻结
```

例如：

```text
Project uses Python 3.12.
QueryEngine must remain a thin façade.
External untrusted content cannot enter L0/L1.
```

Session 启动：

```text
MemoryStore
    ↓
load active pinned memory
    ↓
MemorySnapshot
    ↓
Frozen ContextItems
    ↓
当前 Conversation 生命周期固定
```

Session 内即使执行 `memory.add/replace/remove`，持久层立即更新，但当前 MemorySnapshot 不变化，新值从下一 Session 生效。

### 5.2 Recall Memory

Recall Memory 容量更大，不固定占 Prompt。

```text
user query
    ↓
MemoryRetriever
    ↓
scope filter
    ↓
active-only filter
    ↓
lexical search
    ↓
top-k + token cap
    ↓
ContextItem(L5)
```

v0.39 只要求 SQLite lexical/FTS 搜索，不引入外部 embedding、Vector DB、Memory Provider 或 LLM reranker。

---

## 6. Memory Search 与 Session Search 分离

### Memory Search

回答：

> Agent 长期记住了什么？

返回高密度、长期有效的 Memory。

### Session Search

回答：

> 某个历史 Session 具体讨论过什么？

返回 Message / Transcript。

不得用 Memory 模拟完整历史搜索。Session Search 可作为 v0.39.1 独立能力。

---

## 7. Artifact / Evidence 边界

### Artifact

Artifact 表示 Agent 产出的对象，例如：

```text
report.md
plot.png
experiment.json
generated code
dataset
PDF
```

Memory 可以保存 Artifact 的重要结论或引用，但默认不得复制整个 Artifact body。

### Evidence

Evidence 表示支持事实的原始依据，例如：

```text
paper chunk
URL
Git commit
experiment result
dataset row
tool verified observation
```

Memory 可以引用：

```text
source_refs = [evidence:..., artifact:..., event:...]
```

但 Evidence 才是 source of truth；Memory 是 durable interpretation / index。

---

## 8. 推荐数据流

```text
                    ┌──────────────┐
                    │ SessionEvent │
                    └──────┬───────┘
                           │
                    ┌──────▼───────┐
                    │  Transcript  │
                    └──────┬───────┘
                           │
             ┌─────────────┴─────────────┐
             │                           │
        Evidence                    Artifact
             │                           │
             └─────────────┬─────────────┘
                           │
                     Memory Write
                           │
                    ┌──────▼───────┐
                    │ MemoryStore  │
                    └──────┬───────┘
                           │
          ┌────────────────┴────────────────┐
          │                                 │
 Session start                        Per turn
          │                                 │
 MemorySnapshot                     Retriever
          │                                 │
 Frozen Pinned                    Recall Memory
          │                                 │
          └──────────────┬──────────────────┘
                         ▼
                  ContextBuilder L5
                         │
                  ContextSnapshot
                         │
                       Model
```

---

## 9. MemoryItem 最小模型

建议：

```python
MemoryItem:
    memory_id
    scope_type
    scope_id
    kind
    content
    source_refs
    trust_level
    importance
    pinned
    created_from_run_id
    created_from_sequence
    supersedes_memory_id
    tombstone
    content_hash
    created_at
```

MVP `kind`：

```text
user_preference
project_fact
decision
constraint
workflow
lesson
```

避免在 MVP 引入过多类型。

---

## 10. Immutable History

Memory replace 不覆盖旧记录。

```text
M1: Project uses Python 3.11
        ↓ superseded by
M2: Project uses Python 3.12
```

M2 保存 `supersedes_memory_id=M1`；M1 保留。

删除同理：写入 tombstone 记录，而不是物理 DELETE。

查询 active memory 时，只返回当前有效链头且非 tombstone 的记录。

---

## 11. MemorySnapshot

新增概念：

```python
MemorySnapshot:
    snapshot_id
    conversation_id
    user_memory_ids
    project_memory_ids
    rendered_hash
    estimated_tokens
    created_at
```

Session/Conversation 初始化：

```text
open conversation
      ↓
capture_memory_snapshot()
      ↓
persist MemorySnapshot
      ↓
整个 Conversation 固定使用该 snapshot
```

这是 v0.39 的核心语义，不允许每个 turn 重新读取 pinned Memory。

---

## 12. ContextBuilder 接入

现有 L5 Retrieved Memory 在本版正式启用：

```text
L5
├── frozen pinned memory
└── dynamically recalled memory
```

Memory 转为 ContextItem 时，metadata 至少包含：

```json
{
  "memory_id": "...",
  "memory_mode": "pinned"
}
```

或：

```json
{
  "memory_id": "...",
  "memory_mode": "retrieved"
}
```

不得改变 L0-L4 的既有语义。

---

## 13. Memory Tool

MVP 暴露：

```text
memory.add
memory.replace
memory.remove
memory.search
memory.list
```

所有 mutation 必须经过：

```text
Model
 ↓
Memory Tool
 ↓
existing ToolRegistry validation
 ↓
MemoryService
 ↓
MemoryRepository
 ↓
SessionEvent(memory.*)
```

QueryEngine 不得直接操作 Memory DB，也不得增加 Memory 专用执行路径。

---

## 14. 写入策略

### MVP 允许

```text
用户明确要求记住
稳定项目事实
已确认架构决定
长期约束
稳定 workflow
重要 lesson
```

### MVP 不要求

```text
每轮自动 Memory extraction
自动总结全部 Session
自动推断用户人格
LLM Memory consolidation
无来源复杂事实自动升级
```

智能 extraction 放到后续版本。

---

## 15. Trust 规则

必须复用 PaperClaw 既有 trust 模型。

禁止：

```text
external_untrusted
        ↓
自动写 persistent Memory
```

外部网页、论文或工具输出成为长期事实时，应先经过 Evidence 或用户明确确认。

Memory 自身不得提升来源 trust level。

---

## 16. Token Budget

Pinned Memory 必须有独立硬预算。

建议默认：

```text
USER pinned: ~500 tokens
PROJECT pinned: ~1000 tokens
TOTAL static memory: <= ~1500 tokens
```

具体值可在实现中调整，但无界注入禁止。

超预算首版应 deterministic trim / reject，而不是立即引入 LLM consolidation。

---

## 17. 实施阶段

### Phase A — Contract + Storage

新增 MemoryItem、MemorySnapshot、MemoryRepository 与 schema migration。

### Phase B — MemoryService

实现 add / replace / remove / list / search。

### Phase C — Frozen Session Memory

实现：

```text
Session open
→ capture pinned memory
→ persist MemorySnapshot
→ current session fixed
```

核心验证：Session 内修改 Memory，当前 snapshot 不变；下一 Session 更新。

### Phase D — ContextBuilder L5

实现 Pinned + Recall Memory 到 L5 ContextItem。

### Phase E — Memory Tool

通过现有 ToolRegistry 暴露 add/replace/remove/search/list。

### Phase F — Trace / Eval

记录：

```text
memory.snapshot_created
memory.added
memory.replaced
memory.removed
memory.retrieved
```

ContextSnapshot 可回溯 contributing `memory_id`。

---

## 18. 明确非目标

v0.39 不做：

```text
Mem0 / OpenViking / Honcho / Supermemory
Knowledge Graph
External Vector DB
Embedding Provider
自动用户画像
全量 Session 自动总结
Memory Agent
LLM Memory consolidation
Multi-user cloud memory
跨设备同步
```

避免 Memory MVP 扩张成另一套平台。

---

## 19. GO Gate

v0.39 GO 必须满足：

```text
M39-01 Memory schema migration 正确
M39-02 add/list 正确
M39-03 replace/remove 保留 immutable history
M39-04 USER/PROJECT scope 不泄漏
M39-05 Session 创建 frozen MemorySnapshot
M39-06 Session 内 memory write 不改变当前 snapshot
M39-07 下一 Session 能看到新 memory
M39-08 L5 正确注入 Memory ContextItem
M39-09 external_untrusted 不可直接升为 persistent memory
M39-10 source_refs 可回溯
M39-11 原 Context / Session / QueryEngine 回归通过
M39-12 Artifact/Evidence/Transcript 不被当成 Memory body 存储
M39-13 同 Session pinned rendered_hash 稳定
```

全部通过才允许宣布 `v0.39 = GO`。

---

## 20. 后续路线

```text
v0.39
Structured Built-in Memory
        ↓
v0.39.1
Session Search / Transcript FTS
        ↓
v0.40
MemoryProvider Protocol
        ↓
v0.40+
External Providers / semantic recall
        ↓
v0.41+
Memory Extraction / consolidation / Eval
```

先把 Memory 的语义、Scope、持久化和 Prompt 生命周期做正确，再增加智能化。

---

## 21. 最终架构原则

PaperClaw Memory 的定位：

> Memory 不是历史记录，而是从历史、Evidence 和项目状态中提炼出的、具有明确 Scope、Provenance 和生命周期的跨 Session 长期知识。

Hermes-inspired 部分：

```text
bounded
curated
persistent
frozen per session
history search kept separate
```

PaperClaw 增强：

```text
structured
scope-aware
provenance-aware
auditable
evidence-linked
context-snapshot-aware
```

这是 v0.39 的设计主线。