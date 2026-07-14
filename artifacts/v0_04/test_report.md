# PaperClaw v0.04 Test Report

生成时间：2026-07-14
执行基线：commit `e52ebfc`（Phase E fix 之后）；post-audit 复跑见 §"Post-audit 复跑"
SOP：`Plan/drafts/PaperClaw_v0.04_ContextSessionSQLite_SOP草案.md`（MVP 收口版）

## M04 Gate Matrix

| M04 | Scenario | Test File | Test Function | Status |
|-----|----------|-----------|---------------|--------|
| M04-01 | fresh database | tests/unit/test_context_contracts.py | TestMigrations::test_s01_fresh_migration_latest_succeeds | PASS |
| M04-02 | clean reopen | tests/unit/test_context_session.py | TestSessionReopen::test_reopen_restores_run_id_and_last_sequence | PASS |
| M04-03 | role scope | tests/unit/test_context_builder.py | TestWorkerIsolation::test_c01_worker_a_cannot_see_worker_b_private_item | PASS |
| M04-04 | budget overflow | tests/unit/test_context_builder.py | TestBudgetOverflow::test_c05_eviction_fits_usable_input | PASS |
| M04-05 | constraint retention | tests/unit/test_context_builder.py | TestConstraintRetention::test_c06_constraints_retained_under_budget_pressure | PASS |
| M04-06 | compaction safety | tests/unit/test_compaction.py | TestForbiddenBehaviors::test_hypothesis_not_promoted_to_fact | PASS |
| M04-07 | safe resume | tests/unit/test_checkpoint_wiring.py | TestPFExtraHappyPath::test_clean_checkpoint_allows_resume | PASS |
| M04-08 | unsafe resume | tests/unit/test_checkpoint_wiring.py | TestPF07PartialNode::test_partial_node_returns_recovery_required | PASS |

补充映射（同一 M04 场景的辅助验证用例，全部 PASS）：

- M04-01：test_context_session.py::TestConversationRunMessage::test_open_creates_conversation_and_run
- M04-02：test_context_contracts.py::TestRepositoryBasics::test_s07_session_reopen_restores_state
- M04-03：test_context_builder.py::TestReviewerIsolation::test_c02_reviewer_excludes_worker_hypothesis
- M04-04：test_context_builder.py::TestBudgetOverflow::test_protected_items_exceeding_budget_raises；test_compaction.py::TestDeterministicEviction::test_lower_priority_evicted_first
- M04-05：test_compaction.py::TestConstraintRetentionFixture::test_all_required_constraints_retained_after_compaction；test_compaction.py::TestStructuredCompaction::test_compaction_preserves_constraint_ids
- M04-06：test_compaction.py::TestForbiddenBehaviors::test_evidence_ref_not_fabricated；test_compaction.py::TestForbiddenBehaviors::test_constraint_not_dropped_by_compaction
- M04-07：test_checkpoint_wiring.py::TestPF08PendingWrite::test_pending_operation_committed_allows_resume；test_node_registry.py::TestRegistryHash::test_registry_hash_is_stable_across_invocations（registry hash 一致性是 safe resume 判断的前提）
- M04-08：test_checkpoint_wiring.py::TestPF08PendingWrite::test_pending_operation_started_blocks_resume；test_checkpoint_wiring.py::TestPF09RegistryMismatch::test_registry_hash_mismatch_blocks_resume；test_checkpoint_wiring.py::TestPFExtraHappyPath::test_file_snapshot_mismatch_blocks_resume；test_node_registry.py::TestRegistryHash::test_registry_hash_changes_on_mutation（registry hash 漂移检测是不安全 resume 拦截的依据）

## Test Commands

> 重要执行说明：任务要求 9 个测试文件中 `test_repository.py` 与 `test_session.py` 在仓库中不存在（已用 Glob 确认）。Repository 与 Session 的契约由 `tests/unit/test_context_session.py`（28 用例）和 `tests/unit/test_context_contracts.py` 中的 `TestRepositoryBasics` / `TestCommitRuntimeStep`（共 21 用例）覆盖；`tests/unit/test_node_registry.py`（40 用例）覆盖 NodeRegistry / RegistryHash / CompletedNode 等 runtime 基础层，是 ResumeCoordinator 安全判断的依赖。因此实际运行 8 个文件。
>
> 首次尝试并行运行 5 个测试文件时，因共享同一 `--basetemp=tmp/pytest` 目录触发 Windows 文件锁（WinError 32/3），导致 setup 阶段 rmtree 连锁失败，产生大量 ERROR。**根因是测试基础设施并行冲突，不是代码缺陷。** 改为串行运行后全部通过。下方命令均为串行执行结果。

### 1. Context contract

```
python -m pytest tests/unit/test_context_contracts.py -v --basetemp=tmp/pytest
```

结果：**45 passed in 0.65s**（0 failed）

### 2. Repository（test_repository.py 不存在，由 test_context_session.py 覆盖）

```
python -m pytest tests/unit/test_context_session.py -v --basetemp=tmp/pytest
```

结果：**28 passed in 0.54s**（0 failed）

### 3. Session（test_session.py 不存在，已并入上一项）

注：not found，由 test_context_session.py 覆盖（见上）。

### 4. ContextBuilder

```
python -m pytest tests/unit/test_context_builder.py -v --basetemp=tmp/pytest
```

结果：**20 passed in 0.30s**（0 failed）

### 5. Compaction

```
python -m pytest tests/unit/test_compaction.py -v --basetemp=tmp/pytest
```

结果：**26 passed in 0.26s**（0 failed）

### 6. Checkpoint wiring

```
python -m pytest tests/unit/test_checkpoint_wiring.py -v --basetemp=tmp/pytest
```

结果：**25 passed in 0.10s**（0 failed）

### 7. Resume coordinator

```
python -m pytest tests/unit/test_resume_coordinator.py -v --basetemp=tmp/pytest
```

结果：**24 passed in 0.22s**（0 failed）

### 8. Instrumented flow runner

```
python -m pytest tests/unit/test_instrumented_flow_runner.py -v --basetemp=tmp/pytest
```

结果：**25 passed in 0.05s**（0 failed）

### 9. Node registry

```
python -m pytest tests/unit/test_node_registry.py -v --basetemp=tmp/pytest
```

结果：**40 passed in 0.10s**（0 failed）

覆盖 `IdentifiedNode` 协议、`NodeRegistry` 注册与查询、`node_id` 校验、`registry_hash` 稳定性与漂移检测、`CompletedNode` 序列化、`AgentFlow` 稳定 node id。该模块是 ResumeCoordinator 在 §5.2 中判断 `checkpoint_registry_hash` 是否匹配的依赖层，对应 M04-07 / M04-08 的辅助验证。

### 汇总

| 模块 | 用例数 | passed | failed | errored |
|------|--------|--------|--------|---------|
| test_context_contracts.py | 45 | 45 | 0 | 0 |
| test_context_session.py | 28 | 28 | 0 | 0 |
| test_context_builder.py | 20 | 20 | 0 | 0 |
| test_compaction.py | 26 | 26 | 0 | 0 |
| test_checkpoint_wiring.py | 25 | 25 | 0 | 0 |
| test_resume_coordinator.py | 24 | 24 | 0 | 0 |
| test_instrumented_flow_runner.py | 25 | 25 | 0 | 0 |
| test_node_registry.py | 40 | 40 | 0 | 0 |
| **合计** | **233** | **233** | **0** | **0** |

## Field Drift Check

### SOP §4 contracts vs contracts.py

对比基线：SOP §4（行 107-143）与 `src/paperclaw/context/contracts.py`。

**ContextItem**：SOP §4 列出的概念字段全部存在。

| SOP §4 字段 | contracts.py 字段 | 位置 | 结论 |
|-------------|-------------------|------|------|
| item_id | item_id | L105 | 一致 |
| run_id / task_id | run_id (L106) / task_id (L115) | — | 一致 |
| kind | kind | L108 | 一致 |
| content | content | L109 | 一致 |
| source_ref / trust_level | 嵌入 ContextSource（source_ref L79, trust_level L79） | — | 概念一致，结构上由 ContextSource 承载，非缺失 |
| scope / priority | scope (L112) / priority (L111) | — | 一致 |
| estimated_tokens | estimated_tokens | L113 | 一致 |

额外字段（SOP 声明"MVP 只冻结以下概念，不冻结所有未来字段"，额外字段允许）：layer、source、valid_from_sequence、valid_to_sequence、supersedes_item_id、metadata。

**ContextSnapshot**：SOP §4 列出的概念字段全部存在，存在 1 处命名漂移（非阻塞）。

| SOP §4 字段 | contracts.py 字段 | 位置 | 结论 |
|-------------|-------------------|------|------|
| snapshot_id | snapshot_id | L245 | 一致 |
| run_id / role | run_id (L246) / role (L248) | — | 一致 |
| included_item_ids | **source_item_ids** | L248 | **已同步**：原 SOP §4 文档写作 `included_item_ids`，实现命名为 `source_item_ids`（contracts.py docstring 明确 "source_item_ids is [the source of truth]"）。语义一致，SOP §4 已同步为实现命名 |
| excluded_items + reason | excluded_items（tuple[dict]，dict 含 reason） | L249 | 一致 |
| rendered_hash | rendered_hash | L250 | 一致 |
| estimated_tokens / estimator | estimated_tokens (L251) / estimator (L252) | — | 一致 |

额外字段（允许）：agent_id、created_sequence、task_id。

**SessionEvent**：SOP §4 字段全部一致。

| SOP §4 字段 | contracts.py 字段 | 位置 | 结论 |
|-------------|-------------------|------|------|
| event_id | event_id | L217 | 一致 |
| run_id | run_id | L219 | 一致 |
| sequence | sequence | L220 | 一致 |
| event_type | event_type | L221 | 一致 |
| payload | payload | L222 | 一致 |

额外字段（允许）：conversation_id、created_at。

**Checkpoint**：SOP §4 字段全部一致。

| SOP §4 字段 | contracts.py 字段 | 位置 | 结论 |
|-------------|-------------------|------|------|
| checkpoint_id | checkpoint_id | L306 | 一致 |
| run_id | run_id | L307 | 一致 |
| last_committed_sequence | last_committed_sequence | L308 | 一致 |
| pending_operations | pending_operations | L311 | 一致 |
| file_snapshots | file_snapshots | L312 | 一致 |
| state_hash | state_hash | L313 | 一致 |

额外字段（允许）：task_state_revision、budget_state、schema_version、created_at，以及 Addendum P0-C §5.1 扩展的 4 个 node-identity 字段（completed_node_id、last_action、next_node_id、checkpoint_registry_hash，均默认 None，向后兼容）。

**字段漂移结论**：SOP §4 冻结的概念字段在 contracts.py 中全部存在，无缺失（blocker 级别）。原唯一可记录的差异——ContextSnapshot 中 `source_item_ids`（实现）vs `included_item_ids`（SOP 文档）的命名漂移——已在 post-audit 修复中同步：SOP §4 改为实现命名 `source_item_ids`，与 contracts.py docstring "source_item_ids is [the source of truth]" 一致。

### New tables

新增数据库表：**none**。

`src/paperclaw/context/migrations.py` 中 v1 schema 创建 10 张表，与 v0.04 基线一致：

```
schema_migrations, conversations, runs, session_events, messages,
task_states, context_items, context_snapshots, checkpoints, idempotency_ledger
```

- v2 迁移：通过 temp-table swap 重建 `messages` 表以加 `UNIQUE(conversation_id, sequence)` 约束，**未新增表**。
- v3 迁移（Addendum P0-C §5.1）：对 `checkpoints` 表执行 4 次 `ALTER TABLE ADD COLUMN`，新增列 `completed_node_id`、`last_action`、`next_node_id`、`checkpoint_registry_hash`，**为列扩展而非新表**，符合 SOP §3.1 "fresh database schema 初始化" 边界。
- `memory_items` 表有意延后（SOP §3.2 明确不作为 v0.04 Gate），未引入。

### New recovery states

新增恢复状态：**none**。

Resume 决策仍由 SOP §5.2 定义的二态控制：`resume` 或 `recovery_required`。Checkpoint 数据结构新增的 4 个 node-identity 字段仅用于细化 resume 决策依据（决定进入哪个节点、检测 Flow 定义是否变化），未引入新的恢复状态枚举。`test_resume_coordinator.py`（24 passed）与 `test_checkpoint_wiring.py`（25 passed）覆盖了 safe/unsafe 两条路径，未出现超出 SOP §5.2 的新状态。

## GO/NO-GO 初判

**GO（初判）**

依据：

1. M04-01 至 M04-08 全部 8 个 Gate 场景对应的测试函数在串行运行下全部 PASS；
2. 8 个定向测试文件合计 233 passed / 0 failed / 0 errored；
3. SOP §4 最小契约字段在 contracts.py 中全部存在，无 blocker 级缺失（原 1 处命名漂移已在 post-audit 同步）；
4. 未新增数据库表，v3 迁移为列扩展；未新增恢复状态；
5. 未观察到 NO-GO 信号：无摘要覆盖或伪造 Evidence、无超预算发送模型请求、无 Session reopen 状态/sequence 漂移、无 unsafe state 被自动 resume、无为通过测试修改原始事实。

需主线程确认的次要事项（不阻塞 GO）：

- 并行运行测试时 `--basetemp=tmp/pytest` 共享目录会触发 Windows 文件锁连锁 ERROR，属测试基础设施约束，建议后续 CI 用独立 basetemp 或串行执行；不影响 Gate 判定。

注：本报告为 WP1 最小契约回归初判，最终 GO 需结合 WP2 集成演示与 WP3 留档综合判定。

## Post-audit 复跑

复跑基线：commit `4e60c6b` 之后的 audit fix 工作树（含 compaction.py 确定性 summary_id、conftest.py 合并到 tests/ 根）。

### 命令

```
python -m pytest tests --basetemp=tmp/pytest_full3 -q
```

结果：**345 passed, 1 skipped in 43.75s**（0 failed / 0 errored）

### 发现与修复

1. **rendered_hash 非确定性根因**：commit `4e60c6b` 之前的 `compaction.py._build_summary_item` 使用 `summary-{uuid4().hex[:16]}` 生成 summary_id，而 `ContextBuilder._render` 把 `item_id` 作为 `rendered_hash` 的 payload 字段。两次运行同一份 source items 产生不同 summary_id，导致 `rendered_hash` 漂移，committed `mvp_demo_trace.json` 在每次 rerun 后 dirty。`_compute_hash` 注释已明确指出"summary item_ids are random uuids and would break determinism"但 `_render` 未对应保护。修复：summary_id 改为基于 sorted(source item_ids) 的 SHA-256 前 16 字符，使同一 chunk 总产生相同 id；不同 chunk 因 item_ids 不同不会冲突。
2. **`tests/integration/conftest.py` 遮蔽父级 conftest**：commit `4e60c6b` 新增的 `tests/integration/conftest.py` 让 `from conftest import ...` 解析到 integration 子目录，破坏 `tests/unit/test_cli_observability.py` 与 `tests/integration/test_minimal_react_loop.py`（二者依赖父级 `tests/conftest.py` 的 `FakeModel / action / done / reflect`）。修复：删除 `tests/integration/conftest.py`，把 normalize fixture + `pytest_runtest_makereport` hook 合并到 `tests/conftest.py`，并加 guard：测试 fail 时不 normalize，避免 `pytest.fail` 掩盖原始异常。
3. **M-3 漏报**：本报告 Test Commands 与汇总表原仅列 7 个文件，遗漏 `tests/unit/test_node_registry.py`（40 passed）。已补入 Section 9 与汇总表，合计 193 → 233。
4. **M-2 命名漂移**：SOP §4 写 `included_item_ids`，实现 `contracts.py` 命名为 `source_item_ids`。contracts.py docstring 明确"`source_item_ids` is [the source of truth]"，故以实现为准，同步 SOP 文档命名（见 SOP §4 改动）。

### GO 复判

**GO（维持）**

依据：
1. 修复后全量 345 passed / 1 skipped，与 `4e60c6b` baseline 一致，无新增失败；
2. WP1 定向回归扩充至 233 passed（含 test_node_registry.py 40 用例），仍全 PASS；
3. `rendered_hash` 现在 rerun-stable，committed trace JSON 在 worktree 中保持 clean；
4. ImportError 回归（conftest 遮蔽）已修复，原本未在 v0.04 跑过的 `test_cli_observability.py` / `test_minimal_react_loop.py` 现已纳入全量基线。
