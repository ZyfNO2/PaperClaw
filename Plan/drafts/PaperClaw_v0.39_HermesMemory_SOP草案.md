# PaperClaw v0.39：Hermes-Inspired Memory Runtime SOP

> 状态：EXECUTION READY  
> 类型：本地开发 SOP  
> 原则：最小改造、保持旧路径、逐层验证、禁止一次性重构。

---

## 0. 本次任务

在现有 PaperClaw Context / Session Runtime 上增加跨 Session Long-Term Memory。

禁止新建第二套：

```text
Session Runtime
Context Runtime
QueryEngine
Message Bus
Trace System
```

Memory 必须通过现有架构接线。

---

## 1. 开始前基线检查

执行：

```bash
git status
git branch --show-current
git log -1 --oneline

python -m pytest -q -m "not real_llm and not distributed"
python -m ruff check src/paperclaw tests --select E9,F63,F7,F82 --ignore F821
```

记录：

```text
baseline commit
pytest result
ruff result
```

若基线失败，不得把旧失败归因于 v0.39。

---

## 2. 必读文件

开始开发前必须阅读：

```text
src/paperclaw/context/contracts.py
src/paperclaw/context/migrations.py
src/paperclaw/context/repository.py
src/paperclaw/context/session.py
src/paperclaw/context/builder.py

src/paperclaw/harness/query_engine.py
src/paperclaw/harness/agent_runtime_executor.py

src/paperclaw/tools/registry.py

docs/desgin/PaperClaw_上下文系统与提示词工程骨架.md
Plan/drafts/PaperClaw_v0.04_ContextSessionSQLite_SOP草案.md
Plan/PaperClaw_v0.39_HermesMemory改造计划.md
.trae/specs/v0-39-hermes-memory/spec.md
```

确认 L5 Retrieved Memory 当前状态以及仓库是否已出现更新的 Memory 实现。

如果仓库已经存在比本 SOP 更新的实现，以真实代码为准，不覆盖新代码。

---

## 3. WP1 — Memory Contract

新增建议目录：

```text
src/paperclaw/memory/
    __init__.py
    contracts.py
```

定义：

```text
MemoryScope
MemoryKind
MemoryItem
MemorySnapshot
```

MemoryItem 至少包含：

```text
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

约束：

```text
content 非空
scope 合法
kind 合法
importance 有界
source_refs 格式可验证
supersedes_memory_id != self
```

Tombstone 应只表达删除语义，不应被当成新的长期事实。

### WP1 Gate

建议新增：

```text
tests/unit/memory/test_memory_contracts.py
```

必须验证：

```text
valid contract
invalid scope
invalid kind
empty content
invalid supersedes
serialization round trip
```

运行：

```bash
python -m pytest tests/unit/memory/test_memory_contracts.py -q
```

---

## 4. WP2 — SQLite Migration

修改：

```text
src/paperclaw/context/migrations.py
```

增加：

```text
memory_items
memory_snapshots
```

不得改变已有表语义。

### memory_items 推荐字段

```sql
memory_id TEXT PRIMARY KEY,
scope_type TEXT NOT NULL,
scope_id TEXT NOT NULL,
kind TEXT NOT NULL,
content TEXT NOT NULL,
source_refs TEXT NOT NULL,
trust_level TEXT NOT NULL,
importance INTEGER NOT NULL,
pinned INTEGER NOT NULL,
created_from_run_id TEXT,
created_from_sequence INTEGER,
supersedes_memory_id TEXT,
tombstone INTEGER NOT NULL,
content_hash TEXT NOT NULL,
created_at TEXT NOT NULL
```

推荐索引：

```text
scope_type + scope_id
pinned
content_hash
supersedes_memory_id
```

### memory_snapshots 推荐字段

```text
snapshot_id
conversation_id
memory_ids
rendered_hash
estimated_tokens
created_at
```

如果实际仓库已有标准 JSON/schema 约定，优先复用现有约定。

### WP2 Gate

必须测试：

```text
旧 DB → 新 schema migration
空 DB → 最新 schema
migration 幂等
已有 Context/Session 数据保持
```

运行：

```bash
python -m pytest tests/unit/memory/test_memory_migration.py -q
```

---

## 5. WP3 — Repository

新增：

```text
src/paperclaw/memory/repository.py
```

禁止 MemoryService 直接调用 sqlite3。

建议接口：

```python
add(item)
get(memory_id)
list_active(scope)
list_history(memory_id)
search(query, scope)
insert_snapshot(snapshot)
get_snapshot(snapshot_id)
```

Active Memory 语义：

```text
当前 lineage 中未被后续记录 supersede
AND
当前记录不是 tombstone
```

Replace：

```text
INSERT new MemoryItem
supersedes_memory_id = old_memory_id
```

Remove：

```text
INSERT tombstone MemoryItem
supersedes_memory_id = old_memory_id
```

禁止物理 DELETE 历史 Memory。

### WP3 Gate

测试：

```text
add
replace
remove
active projection
history chain
duplicate/content hash behavior
USER scope isolation
PROJECT scope isolation
```

---

## 6. WP4 — MemoryService

新增：

```text
src/paperclaw/memory/service.py
```

建议 API：

```python
add_memory(...)
replace_memory(...)
remove_memory(...)
list_memory(...)
search_memory(...)
capture_snapshot(...)
```

MemoryService 负责：

```text
validation
scope resolution
content hash
source provenance
mutation semantics
snapshot assembly
budget
```

Repository 只负责 persistence。

---

## 7. WP5 — Frozen Memory Snapshot

这是 v0.39 核心 Gate。

Conversation / Session 初始化时：

```text
resolve USER scope
resolve PROJECT scope
        ↓
load active pinned memory
        ↓
apply deterministic order
        ↓
apply token budget
        ↓
render deterministic block
        ↓
persist MemorySnapshot
```

当前 Conversation 绑定一个 frozen snapshot。

之后每次 Model Call 必须使用同一个 pinned snapshot。

绝不能：

```text
每轮重新读取 active pinned memory
```

### 必测场景

初始：

```text
Memory = A
```

启动 Session S1：

```text
snapshot(S1) = A
```

S1 中：

```text
replace A → B
```

必须仍满足：

```text
persistent MemoryStore = B
snapshot(S1) = A
```

新建 S2：

```text
snapshot(S2) = B
```

该测试失败则 v0.39 NO-GO。

---

## 8. WP6 — ContextBuilder L5

修改：

```text
src/paperclaw/context/builder.py
```

不得修改 L0-L4 现有语义。

Memory 转换为：

```python
ContextItem(
    layer="L5",
    kind=...,
    source=...,
    metadata={
        "memory_id": ...,
        "memory_mode": "pinned" | "retrieved",
    },
)
```

Pinned Memory 来自 frozen MemorySnapshot。

Recall Memory 来自 `search_memory()` 或定义清晰的 read-only retriever/provider boundary。

必须保证 Memory 不被提升为 L0/L1 instruction。

---

## 9. WP7 — Recall Search

MVP 先实现 SQLite lexical / FTS search。

流程：

```text
query
 ↓
scope filter
 ↓
active only
 ↓
rank
 ↓
top-k
 ↓
token cap
 ↓
L5 ContextItems
```

本版不得为了 Recall 引入：

```text
Embedding API
LLM search rewrite
Vector database
External Memory Provider
```

如果 SQLite FTS 在当前仓库构建/平台约束下不适合，可以采用现有 SQLite lexical 方案，但必须保持 deterministic、scope-safe、可测试。

---

## 10. WP8 — Memory Tool

通过现有 ToolRegistry 暴露 Memory Tool，不增加 QueryEngine 特判。

MVP actions：

```text
add
replace
remove
list
search
```

### add

输入至少包括：

```text
target scope
kind
content
source_refs?
importance?
pinned?
```

### replace

必须指定目标 `memory_id` 和新内容。

### remove

必须指定目标 `memory_id`。

所有 mutation 必须由 MemoryService 完成。

---

## 11. WP9 — SessionEvent / Trace

所有 Memory 生命周期行为产生可审计事件：

```text
memory.added
memory.replaced
memory.removed
memory.snapshot_created
memory.retrieved
```

Event payload 不重复保存巨大 content。

优先记录：

```text
memory_id
scope
kind
content hash
source refs / source count
snapshot_id
retrieved count
```

保持现有 Trace redaction 与 secret policy。

---

## 12. WP10 — Provenance / Security

允许作为长期 Memory 来源的典型路径：

```text
user
system
trusted_local
confirmed evidence
```

禁止自动持久化：

```text
external_untrusted
```

外部网页、论文或 external tool 信息成为长期事实时，应先形成 Evidence，或获得用户明确确认。

Memory trust_level 不得高于真实 source。

---

## 13. WP11 — Artifact / Evidence / Transcript Boundary Tests

必须专门写测试证明：

```text
Memory 不保存 artifact body
Memory 不保存 evidence body
Memory 不保存 transcript dump
Memory 不保存 raw tool output
```

Memory 可以保存：

```text
artifact ref
evidence ref
session/event ref
高密度 durable conclusion
```

原始对象继续由各自子系统负责。

---

## 14. WP12 — Prompt Stability Test

对同一个 Session：

```text
turn 1
turn 2
turn 3
```

即使期间 MemoryStore 被修改，frozen pinned memory 的：

```text
snapshot_id
rendered_hash
```

必须保持稳定。

Recall Memory 是动态 L5 内容，不属于 pinned prefix stability 的同一语义；测试必须区分 pinned 与 retrieved。

---

## 15. WP13 — Backward Compatibility

Memory disabled 或无 active memory 时，现有行为必须保持等价。

重点回归：

```text
ContextBuilder
SessionService
Checkpoint / Resume
QueryEngine
AgentRuntimeExecutor
ToolRegistry
Trace
```

不得要求旧调用者必须显式配置 Memory 才能工作。

---

## 16. WP14 — 定向与全量回归

定向测试通过后：

```bash
python -m pytest -q tests/unit/memory
python -m pytest -q tests/unit/context
python -m pytest -q tests/unit/test_query_engine.py
python -m pytest -q tests/unit/test_agent_runtime_executor.py
```

最后：

```bash
python -m pytest -q -m "not real_llm and not distributed"
python -m ruff check src/paperclaw tests --select E9,F63,F7,F82 --ignore F821
python -m build
```

若仓库当前命令已变化，以仓库最新 CI/README 为准，并在 Handoff 记录差异。

---

## 17. Acceptance Matrix

| ID | Requirement | Expected |
|---|---|---|
| M39-01 | Migration | PASS |
| M39-02 | Memory add/list | PASS |
| M39-03 | Replace immutable history | PASS |
| M39-04 | Remove tombstone | PASS |
| M39-05 | USER scope isolation | PASS |
| M39-06 | PROJECT scope isolation | PASS |
| M39-07 | Frozen snapshot creation | PASS |
| M39-08 | Mid-session write isolation | PASS |
| M39-09 | Next-session refresh | PASS |
| M39-10 | L5 pinned injection | PASS |
| M39-11 | L5 recall injection | PASS |
| M39-12 | provenance traceability | PASS |
| M39-13 | external_untrusted promotion guard | PASS |
| M39-14 | Artifact/Evidence/Transcript separation | PASS |
| M39-15 | Prompt rendered hash stability | PASS |
| M39-16 | Existing Runtime regression | PASS |

---

## 18. NO-GO 条件

任一发生则 v0.39 NO-GO：

```text
Memory scope 跨 Project 泄漏
Session 内 frozen MemorySnapshot 被自动刷新
replace/remove 覆盖或删除历史记录
external_untrusted 自动变成高 trust 长期事实
Evidence 被 Memory 覆盖
Artifact/Transcript/raw output 被复制成 Memory body
QueryEngine 直接写 Memory DB
为了 Memory 新建第二套 Context/Session Runtime
Memory disabled 时旧路径回归
```

---

## 19. Artifacts

完成后建议生成：

```text
artifacts/v0_39/
    implementation_summary.md
    test_report.md
    memory_semantics.md
    frozen_snapshot_demo.json
    known_limitations.md
    file_manifest.txt
```

不得伪造真实测试结果；未运行的项标记 pending / not verified。

---

## 20. Handoff

最终 Handoff 至少包含：

```text
Repository
Branch
Base commit
Final commit

Implemented modules
Migration version

Memory scopes
Frozen snapshot semantics
Recall semantics

Tests
Regression
CI

Known limitations
Pending real tests
Next recommended version
```

---

## 21. 推荐 Commit 切分

```text
feat(v0.39): add structured memory contracts and persistence
feat(v0.39): add memory service and immutable mutations
feat(v0.39): freeze session memory snapshots
feat(v0.39): wire memory recall into context L5
feat(v0.39): expose audited memory tools
test(v0.39): close memory runtime acceptance gates
docs(v0.39): record memory runtime acceptance
```

不要一次写完全部代码再提交；每阶段应可单独测试和回滚。