# PaperClaw v0.04 Known Limitations

> 生成时间：2026-07-14
> 来源：`artifacts/v0_04/compaction.json` 与 `artifacts/v0_04/resume_boundary.json` 的 `non_blocking_debts` 字段，加上 SOP §3.2「不作为 v0.04 Gate」与 §10 后续增强边界。

v0.04 仅验证 Context / Session / SQLite MVP 闭环，下述增强能力均不属于当前版本完成 Gate。已经存在的相关实现只算「额外能力候选」，不反向扩大验收范围（见 SOP §3.2 末段）。

---

## 数据库增强（v0.04.1 候选）

- **Schema upgrade / 自动 backup / restore**：v0.04 只支持 fresh database schema 初始化，不做旧版本数据库迁移，也不提供自动备份与恢复。
  - 影响: 若 schema 在后续版本发生变更，已有 SQLite 文件无法平滑升级；运行异常时也没有内置快照回滚路径。
  - 延后到: v0.04.1
  - 当前缓解: v0.04 只承诺 fresh init；调用方若遇到 schema 不匹配需重建数据库。

- **并发 writer 压测 / 高并发 SQLite**：v0.04 假设单进程、单用户写入，未做 multi-writer 压测，未启用 WAL 调优与并发写策略。
  - 影响: 多 writer 并发场景下未验证写入正确性与吞吐；不能直接用于多进程并发任务调度。
  - 延后到: v0.04.1
  - 当前缓解: 文档与代码均假设单进程 resume、无并发写入（见 `FileSnapshotVerifier` docstring 与 §3.2）。

- **完整 operation idempotency ledger**：当前 `build_pending_operations` 采用 last-write-wins 配对，未提供完整、可审计的 idempotency ledger。
  - 影响: 同一 operation 多次 started/terminal 事件的复杂时序无法被 ledger 完整审计；replay 去重仅依赖事件配对。
  - 延后到: v0.04.1
  - 当前缓解: 检测到非 terminal operation 时直接返回 `recovery_required`（fail-closed），不尝试自动调和。

---

## 恢复增强（v0.04.1 候选）

- **任意时刻 crash 自动继续**：v0.04 不承诺无人值守崩溃自动恢复；调用方必须显式调用 `ResumeCoordinator.decide_resume`。
  - 影响: 进程崩溃后无法自动续跑，必须有人或上层 runner 主动触发 resume 决策。
  - 延后到: v0.04.1
  - 当前缓解: 仅在已提交 step boundary 提供 Checkpoint；其它时刻崩溃视为需要人工介入。

- **Bash / file / 外部 API 自动 reconciliation**：Coordinator 只计算 resume 决策，从不调用 mutating tool，也不判断外部 API 调用是否成功。
  - 影响: pending Bash、file write 或外部 API 调用未 terminal 时，无法自动重放或回滚，只能阻止 resume。
  - 延后到: v0.04.1
  - 当前缓解: 检测到 pending mutation 即返回 `recovery_required`，由人工或后续版本处理。

- **durable mailbox / Worker / Task / FileLease 恢复**：v0.04 不持久化 mailbox、Task 状态机或 FileLease，不尝试跨进程 Worker 恢复。
  - 影响: 崩溃时活跃的 Worker / Task / lease 无法在 resume 时被重建或迁移。
  - 延后到: v0.04.1
  - 当前缓解: 仅检测 active Worker（status ∈ {active, running, started}）并阻止 resume；lease 不持久化（见 E-DEBT-5）。

- **Lease 状态检测（E-DEBT-5）**：`ResumeCoordinator` 不检查 FileLease 或其他 lease 状态。SOP §10.2 condition 7（lease 状态无法确认）未实现。
  - 影响: 崩溃时持有活跃 lease 的 run 在 resume 时无法被检测；§10.2 要求的「检测不确定 lease 状态」缺失（检测与恢复是两件事）。
  - 延后到: v0.04.1
  - 当前缓解: v0.04 不持久化 lease，因此崩溃前的 lease 不会自动恢复；resume 决策对 lease 维度保持沉默，仅由 fail-closed 的 pending-mutation 检测间接兜底。

- **TaskState revision 一致性检查（E-DEBT-1）**：SOP §10.1 condition 4 未由 `ResumeCoordinator` 强制。
  - 影响: 若调用方在 Checkpoint 之后 bump TaskState revision，无法被检测。v0.04 假设调用方按 SOP §5.3 在 Checkpoint 前提交 TaskState。
  - 延后到: v0.04.1
  - 当前缓解: 通过 SOP §5.3 的提交顺序约定 + 调用方自律，runtime 层不强制校验。

- **state_hash 重计算（E-DEBT-4）**：Coordinator 不重算 `state_hash` 与当前状态对比。R-05「Corrupt checkpoint — state_hash 失败」未实现。
  - 影响: 被篡改 `state_hash` 的 Checkpoint 无法被检测。当前 `test_no_checkpoint_returns_recovery_required` 覆盖「无 Checkpoint」场景，与 R-05 不同。
  - 延后到: v0.04.1
  - 当前缓解: 文件 hash 与 registry hash 仍校验；state_hash 维度暂不验证，依赖调用方不修改 Checkpoint 二进制。

---

## Context 增强（v0.04.1 候选）

- **LLM compaction（D-DEBT-1）**：`CompactionPolicy._build_summary_item` 使用简单内容片段（每项前 80 字符），未实现 LLM 摘要。
  - 影响: 摘要信息密度低，但不破坏 provenance 与确定性。
  - 延后到: v0.04.1
  - 当前缓解: 摘要 `trust_level = trusted_local`，标记为派生 observation，绝不升级为 fact；确定性可复现。

- **精确 tokenizer**：v0.04 默认使用 `Char4TokenEstimator`（1 token / 4 UTF-8 bytes）作为保守估算。
  - 影响: 估算偏差可能导致预算略偏保守，无法精准匹配上游模型 tokenizer。
  - 延后到: v0.04.1
  - 当前缓解: 估算偏向保守，配合硬预算阈值 fail-closed，避免超长上下文。

- **Prompt Cache**：v0.04 不接入 Prompt Cache，每次构建的 ContextSnapshot 都按全量发送给模型。
  - 影响: 重复 prefix 无法被上游 provider 缓存复用，token 成本与延迟未优化。
  - 延后到: v0.04.1
  - 当前缓解: 通过结构化 compaction 控制总 token 数；功能正确性不依赖 Prompt Cache。

- **自动长期 Memory**：v0.04 不引入自动长期记忆；Memory 持久化延后。
  - 影响: 跨 Session 的长期记忆与 confidence 衰减不在 MVP 范围内。
  - 延后到: 后续版本
  - 当前缓解: ContextItem 的 `source_ref / trust_level / scope` 已保留 provenance 字段，为后续 Memory 接入预留契约。

- **Dense retrieval / 向量数据库 / Knowledge Graph**：MVP 默认 SQLite，向量数据库与复杂 RAG 基础设施延后到评估需求明确后。
  - 影响: 不能进行语义检索或图结构推理；Context 选择只依赖确定性 priority / scope 过滤。
  - 延后到: 后续版本
  - 当前缓解: ContextBuilder 提供确定性 select + 结构化 compaction，保证 MVP 闭环可解释。

- **大文件内容特殊处理（D-DEBT-2）**：大文件内容（§8.3 tier 1）在 compaction 中按普通可驱逐项对待，未实现 source_ref-based re-read eligibility。
  - 影响: 大文件可能被合并进 summary 而非按需重读，可能损失精度。
  - 延后到: v0.04.1
  - 当前缓解: summary 保留原始 item_id 列表，provenance 可追溯；不丢失来源。

- **专用 tool output token 上限（D-DEBT-3）**：工具输出裁剪（D3）依赖首轮驱逐，compaction 内尚无专用 `max_tool_output_tokens` 强制。
  - 影响: 超长工具输出仅在预算压力触发首轮驱逐时被处理，无独立上限守门。
  - 延后到: v0.04.1
  - 当前缓解: 总预算硬上限仍生效，超预算会 fail-closed；只是工具输出无独立 guard。

---

## MultiAgent 增强（v0.04.1 候选）

- **完整 MultiAgent 端到端演示**：v0.04 不提供多角色完整演示，仅保留单角色 Context MVP 闭环。
  - 影响: 多角色协同、角色间消息路由与冲突调和未在当前版本验证。
  - 延后到: v0.04.1
  - 当前缓解: ContextBuilder 已支持角色过滤（role-scoped selection），为后续 MultiAgent 接入预留接口。

- **Global Verify**：v0.04 不在 Gate 内提供跨角色全局验证层。
  - 影响: 多角色输出的一致性与冲突检测由后续版本承担。
  - 延后到: v0.04.1
  - 当前缓解: 单角色闭环内仍通过 `verify_required_ids` 与 forbidden behaviors 守护 Context 完整性。

- **Semantic Reviewer**：未实现语义级 reviewer，仅靠结构性 invariant（§9.2 forbidden behaviors）守护。
  - 影响: 语义漂移（如摘要偏离原意）无法被自动检测。
  - 延后到: v0.04.1
  - 当前缓解: 摘要 trust_level 不升级、原 item_id 全部保留，结构性杜绝 hypothesis→fact 升级。

- **failed Worker retry / repair 状态机**：v0.04 对 active Worker 仅检测，不提供 retry/repair 状态机。
  - 影响: 失败 Worker 无法被自动重试或修复；只能 fail-closed 阻止 resume。
  - 延后到: v0.04.1
  - 当前缓解: 检测到 status ∈ {active, running, started} 立即返回 `recovery_required`，由人工介入。

---

## 文件验证增强（v0.04.1 候选）

- **TOCTOU race（E-DEBT-3）**：`FileSnapshotVerifier.verify` 与 resume 动作之间存在 TOCTOU 竞态。
  - 影响: 文件可能在 `verify()` 返回 True 后、runner 执行前被外部修改。v0.04 假设单进程 resume、无并发写入。
  - 延后到: v0.04.1
  - 当前缓解: 文档与代码均明确假设单进程 resume；并发场景下不承诺安全。

- **Symlink target resolution**：`FileSnapshotVerifier` 按路径原样处理，不解析 symlink 指向的真实 target。
  - 影响: 若关键文件被替换为指向其他文件的 symlink，verify 仍会按 symlink 路径读取，可能无法检测到 target 被替换。
  - 延后到: v0.04.1
  - 当前缓解: 文件 hash 仍会反映 symlink 当前指向的内容；但 target 切换不会被显式标记。

- **Directory tree snapshots**：仅支持单文件 snapshot，不支持目录树快照。
  - 影响: 若 checkpoint 需要记录整个目录的状态，必须逐文件 snapshot；目录结构变化（新增/删除子文件）不会被检测。
  - 延后到: v0.04.1
  - 当前缓解: 调用方需显式列出关键文件路径；目录级 invariant 由调用方在更上层维护。

---

## 预算增强（Phase F 候选）

- **Budget state 真实持久化（E-DEBT-2）**：v0.04 Checkpoint 携带 `budget_state={}`，SOP §10.1 condition 7 被平凡满足。
  - 影响: 步骤中途预算耗尽的 run 在 resume 时无法被检测；ResumeCoordinator 无法基于 budget 做决策。
  - 延后到: Phase F
  - 当前缓解: 当前 run 内仍通过 ContextBuilder 硬预算 fail-closed；resume 路径对 budget 维度保持沉默，不假装校验通过。
