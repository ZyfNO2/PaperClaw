# PaperClaw v0.04 Implementation Summary

本版本交付 Context / Session / SQLite MVP 闭环：在 PocketFlow 风格控制流之上，落地了不可变 Context 契约、SQLite 持久化 Session、确定性预算与压缩、稳定 Node ID 与 InstrumentedFlowRunner、Checkpoint 写入与安全恢复边界，形成可演示、可解释、可恢复的最小 Runtime 闭环。

---

## 1. Phase A–E 模块清单

| Phase | 模块 | 路径 | 说明 |
|---|---|---|---|
| Phase A | 数据契约与 migration | `src/paperclaw/context/contracts.py`、`src/paperclaw/context/migrations.py` | 冻结 ContextItem / ContextSource / Checkpoint 等不可变契约；TRUST_LEVELS、CONTEXT_LAYERS、CONTEXT_KINDS、SCOPE 常量；migration 骨架。 |
| Phase B | Session persistence | `src/paperclaw/context/session.py`、`src/paperclaw/context/repository.py` | EventSink Protocol + NullEventSink / SqliteEventSink；SessionService 统一 open/reopen、emit、update_task_state、record_side_effect；SQLiteRepository 单写者锁 + auto-sequence。 |
| Addendum P0-A | 稳定 Node ID | `src/paperclaw/runtime/node_registry.py` | IdentifiedNode Protocol、CompletedNode、NodeRegistry 双向映射 + node_registry_hash；RegistryMismatch 在恢复期暴露不兼容 Flow。 |
| Addendum P0-B | InstrumentedFlowRunner | `src/paperclaw/runtime/flow_runner.py`、`src/paperclaw/runtime/flow_contracts.py` | 包裹 PocketFlow，发射 node.started / node.completed 事件；FlowResumePoint 契约；保留 prep/exec/post 共享 dict 引用语义。 |
| Phase C | ContextBuilder 与 RoleContextView | `src/paperclaw/context/builder.py` | collect → validate → scope → expire → dedup → conflict → estimate → select → compact → render → persist 流程；RoleContextView 仅持 role/task_id；external_untrusted 不入 L0/L1 的硬 NO-GO。 |
| Phase D | Budget 与 Compaction | `src/paperclaw/context/compaction.py` | TokenEstimator Protocol + Char4TokenEstimator；CompactionPolicy 无状态合并 evicted observation；CompactionOutcome 冻结结果；摘要 source_ref 可回溯。 |
| Addendum P0-C | Checkpoint Wiring | `src/paperclaw/runtime/checkpoint.py`、`src/paperclaw/runtime/resume.py` | CheckpointWriter Protocol + SqliteCheckpointWriter；evaluate_resume_safety 决策原语；commit 顺序：node.completed → writer。 |
| Phase E | Safe resume boundary | `src/paperclaw/runtime/file_snapshot.py`、`src/paperclaw/runtime/resume_coordinator.py` | FileSnapshotVerifier（hashlib + snapshot 助手）；ResumeCoordinator 端到端 decide_resume；build_pending_operations 从事件日志重建 pending ops。 |

---

## 2. Commits 列表

以下为 v0.04 全量提交（`git log --oneline 4c2a5f4..HEAD`）：

```
e52ebfc fix(v0.04-E): address Phase E review findings (H-1, M-2)
4968b9c feat(v0.04-E): safe resume boundary with FileSnapshotVerifier + ResumeCoordinator
f7c5336 feat(v0.04-D): structured compaction with deterministic eviction + char4 estimator
af86ebb feat(v0.04-P0C): CheckpointWriter + safe resume decision (PF-06..PF-09)
94f84f1 feat(v0.04-C): ContextBuilder + RoleContextView with role-scoped selection
a7ad744 feat(v0.04-P0B): InstrumentedFlowRunner wrapping PocketFlow with event emission
04a36ec fix(v0.04-P0A): address review findings (M-1 doc sync, M-2 RuntimeServices.checkpoint_writer)
0c68c76 feat(v0.04-P0A): stable Node IDs, NodeRegistry, CompletedNode, vendored core integrity
d4eaa5c fix(v0.04-B): address Phase B review findings (H-1, H-2, L-1..L-4)
2a482ab Phase B: SessionService + EventSink integration with Repository
a08c522 fix(v0.04-A): atomic commit_runtime_step + construction-failure cleanup
cbfd322 Merge branch 'main' of https://github.com/Zyfno2/PaperClaw
8d9c984 docs(v0.04): add PocketFlow runtime adapter implementation addendum
fd11504 Merge branch 'main' of https://github.com/Zyfno2/PaperClaw
73d4609 docs(v0.04.1): add runtime protocol closure and recovery reconciliation SOP draft
```

---

## 3. 设计决策摘要

### 3.1 Phase D — Budget 与 Structured Compaction

来源：`artifacts/v0_04/compaction.json` → `design_decisions`。

- **D-D1｜压缩仅合并 `kind == "observation"` 项**：SOP §8.2 允许压缩旧 Observation，§9.2 禁止把 hypothesis 改写为 fact；将合并输入限制为 observation，从结构上阻断禁止的提升路径。
- **D-D2｜摘要项的 kind 仍为 `observation`，不是 `fact` 或 `decision`**：摘要是派生观察，不是已验证事实；提升它会违反 §9.2。
- **D-D3｜摘要 `source_ref = compaction:item_id1,item_id2,...`**：满足 SOP §4.1 来源可溯；逗号分隔列表让任意消费者可回溯原始项。
- **D-D4｜摘要 `trust_level = trusted_local`（非 `external_untrusted`）**：摘要是确定性代码产出，不是 LLM 生成；v0.04 不使用模型生成摘要。
- **D-D5｜压缩 hash 排除摘要 item_id（随机 uuid），仅含 content hash**：D6 不变量——对同一可压缩集合两次压缩必须产生相同 hash；随机 uuid 会破坏确定性。
- **D-D6｜压缩后预算检查：仅当 PROTECTED 项超出 usable_input 才抛 ContextBudgetExhausted**：§8.3 第 4 款要求超预算时不静默截断硬约束；若仅摘要把总量推过预算，接受结果——丢摘要会丢失来源。
- **D-D7｜`_is_protected` 在 compaction.py 内重复（不从 builder.py 导入）**：避免循环导入（builder 懒加载 CompactionPolicy，compaction 急需 _is_protected）；两份副本必须同步。
- **D-D8｜ContextBuilder 接受可选 `compaction_policy` 参数**：允许测试注入自定义策略；默认 None 时首次使用懒实例化 CompactionPolicy。

### 3.2 Phase E — Safe Resume Boundary

来源：`artifacts/v0_04/resume_boundary.json` → `design_decisions`（E-D1..E-D7）。

- **E-D1｜FileSnapshotVerifier 作为类，不是裸 callable**：`evaluate_resume_safety` 接受 `Callable[[dict], bool]` 以便测试注入合成 verifier；FileSnapshotVerifier 是带状态 hash_algorithm 配置的生产实现，并附 snapshot() 助手记录 pre-mutation 状态。
- **E-D2｜build_pending_operations 按 operation_id 配对，last-write-wins**：一个 operation 可能有多个 started（重试）或多个 terminal 事件；last-write-wins 与幂等账本语义一致；顺序按首次 started 事件稳定排序。
- **E-D3｜ResumeCoordinator 组合 evaluate_resume_safety 而非复制规则**：P0-C 的 evaluate_resume_safety 是核心决策（registry hash、pending ops、file snapshots）的唯一真源；Coordinator 只收集输入并委托。
- **E-D4｜Active Worker 仅检测不恢复**：SOP §10.3 明确推迟 MultiAgent active Worker 恢复；Coordinator 检测 status ∈ {active, running, started} 并以 recovery_required 阻断，但从不尝试终止或协调 Worker。
- **E-D5｜schema version gate 在所有其他检查之前**：schema_version=99 意味着序列化格式可能已变；先查 schema 版本避免把误读的 Checkpoint 传给决策逻辑。
- **E-D6｜FileSnapshotVerifier.verify 遇 I/O 错误返回 False，不抛异常**：False 被 evaluate_resume_safety 视为不匹配（安全默认：阻断恢复）；不可读文件状态未知，抛异常会迫使调用方包 try/except。
- **E-D7｜`existence_required=False` 记录"缺席"（而非仅"不存在"）**：断言"resume 时此文件不应存在"；用于删除类清理操作——若 resume 时文件出现，说明外部进程创建，resume 必须停。

---

## 4. 既有实现参考借鉴

> 按 SOP §11（`Plan/drafts/PaperClaw_v0.04_ContextSessionSQLite_SOP草案.md` 第 319–330 行）表格对照。
>
> 说明：v0.04 实现代码注释未对参考项目源文件做逐行内联标注。下表"实际借鉴"列描述代码中可见且与 SOP §11 借鉴目标对齐的概念/契约层面借鉴（设计意图对齐），而非字面代码迁移；若某参考项目在实现期未被直接打开核验，标注为"未直接查阅"。

| 参考项目 | 必读路径 | 实际借鉴 | 未照搬项 |
|---|---|---|---|
| AutoResearchClaw | `researchclaw/hitl/context_manager.py` | 概念借鉴：Context 分区（L0–L5 六层 + RoleContextView role/task_id scope 匹配）与 artifact summary 思路对应 `builder.py` 的 collect → scope → select → render 流程与 observation 摘要合并。 | 字符硬截断（未采用——v0.04 用 token 预算 + keep-priority 选择，超 protected 项才抛 ContextBudgetExhausted）；stage 强耦合（未采用——RoleContextView 与具体科研 stage 无关）。 |
| AutoResearchClaw | `researchclaw/hitl/chat.py` | 概念借鉴：Session 序列化与 reopen 对应 `session.py` 的 SessionService.open/reopen + SqliteEventSink 持久化 + crash-safe resume 语义。 | 复制其科研 stage state（未采用——SessionEvent 是通用 type/payload，不含科研阶段状态机）。 |
| AutoResearchClaw | `researchclaw/memory/store.py` | 概念借鉴：provenance、confidence、生命周期字段对应 `contracts.py` 的 ContextSource（trust_level / source_type / source_ref）与 ContextItem（valid_from_sequence / valid_to_sequence / superseded_by）。 | 在 MVP 引入自动长期 Memory（未采用——v0.04 只做 Session 级 ContextItem 生命周期，无自动长期 Memory 晋升）。 |
| AutoResearchClaw | `researchclaw/pipeline/runner.py` | 概念借鉴：checkpoint 与安全恢复边界对应 `checkpoint.py`（CheckpointWriter Protocol + commit 顺序）与 `resume_coordinator.py`（decide_resume + build_pending_operations）。 | 任意副作用自动恢复（未采用——ResumeCoordinator 是纯决策层，从不调用 mutating tool，从不恢复进程树，active Worker 仅检测；E-D4）。 |
| Draftpaper-loop | `docs/DPL_SCHEMA.md`、`draftpaper_cli/loop_contract.py` | 概念借鉴：稳定 ID 与原始记录/派生物分离对应 `node_registry.py` 的 IdentifiedNode + NodeRegistry + node_registry_hash，以及 `contracts.py` 的 evidence_ref kind + source_ref 回溯。 | 论文流水线数据模型（未采用——Node ID 约定 decide / tool:<name> / verify_done / completed 与论文流水线无关）。 |
| PaperAgent | `apps/api/app/services/agents/graph/nodes/evidence_context.py` | 概念借鉴：Evidence Context 与来源追踪对应 `contracts.py` 的 evidence_ref kind + `compaction.py` 摘要 source_ref = `compaction:item_id1,...` 的可回溯设计（D-D3）。 | LangGraph State 强耦合（未采用——PaperClaw Context/Runtime 独立于图框架，PocketFlow 风格控制流 + InstrumentedFlowRunner adapter）。 |

---

## 5. 测试统计

- **344 passed, 1 skipped**
- Phase E 前：320 passed, 1 skipped；Phase E 新增 24 tests（TestBuildPendingOperations 8 + TestFileSnapshotVerifierVerify 5 + TestFileSnapshotVerifierSnapshotRoundTrip 2 + TestResumeCoordinatorDecideResume 9），无回归。
- Phase D 测试矩阵共 26 tests（覆盖 Char4TokenEstimator、确定性驱逐、结构化压缩、Constraint Retention、Compaction Drift hash 确定性、不可变快照、§9.2 禁止行为、tool output trimming、CompactionPolicy 直测）。
- R-05（state_hash 失败）推迟至 v0.04.1（E-DEBT-4）。
