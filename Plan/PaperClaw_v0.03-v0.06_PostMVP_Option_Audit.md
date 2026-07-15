# PaperClaw v0.03–v0.06 Post-MVP 选做项审计

> 状态：候选审计完成；三个最小切片已实现
> 日期：2026-07-15
> 分支：`feat/v0.06.1-safe-session-picker`
> 规则：候选池不是默认 Roadmap；只有前置契约存在、用户故事明确且能独立验证的切片才可动工。

## 1. 结论

按文档中的候选包或延期行计数，本轮共审计 **26 项**：

- v0.03 Deferred：10 行；
- v0.04.1：5 个候选包；
- v0.05.1：5 个候选包；
- v0.06.1：6 个候选包。

这些条目存在明显跨版本重叠，因此 26 不等于 26 个独立项目。本轮分类结果：

| 分类 | 数量 | 结论 |
|---|---:|---|
| 已提取并实现的独立切片 | 3 | SQLite 只读 Doctor、Verification Inspector、Safe Session Picker |
| 条件性可启动 | 2 | Global Verify、MultiAgent View；仍缺失败 fixture、event adapter 或真实收益证据 |
| 当前不应启动、已被吸收或属于后续版本 | 21 | 保持 backlog，不做假接口或空 UI |

## 2. 已实现切片

### 2.1 v0.04.1 E2：SQLite 只读健康检查

用户故事：用户在迁移、备份或排障前，需要确认现有 PaperClaw 数据库可读、结构未损坏且没有外键违规，同时检查过程不得修改数据库。

实现：

- `paperclaw doctor --database <path>`；
- 默认执行 `PRAGMA quick_check`；
- `--full` 执行 `PRAGMA integrity_check`；
- 额外执行 `PRAGMA foreign_key_check`；
- 读取 `schema_migrations` 的最大版本；
- 使用 SQLite URI `mode=ro` 和 `PRAGMA query_only = ON`；
- 缺失和损坏数据库 fail-closed；
- 不创建数据库、不运行 migration、不修复数据。

本切片没有声称完成 E2 的 backup、restore drill、rollback、retention 或多 writer contention。

### 2.2 v0.06.1 U3：Verification Inspector

用户故事：用户在 TUI 中需要看到确定性 Verify 的最终结论，而不是只看到一条时间线事件或模型自报完成。

实现：

- 单一 `VerificationInspector`；
- 展示 status、passed/failed/uncovered claim 数量；
- 展示 `verified_after_last_write`；
- 展示截断后的结构化 summary；
- `/new` 时清空 Inspector；
- Bridge 在 UI 边界删除 raw `checks` 和 `observed` 输出；
- 不展示隐藏 reasoning、命令完整输出或任意 payload。

本切片没有加入 Context、Trace 或 Cost Inspector，也没有扩展 Runtime 契约。

### 2.3 v0.06.1 U5：Safe Session Picker

用户故事：用户需要在 TUI 中查看已安全关闭的 conversation，先预览再重新打开，并保证旧 Run 不被追加或修改。

实现：

- `paperclaw tui --database <path>` 显式启用持久化与 picker；
- `/sessions` 只列出不存在 active Run 的 conversation；
- `/preview <index|conversation_id>` 通过只读 SQLite 显示最近消息摘要；
- `/open <index|conversation_id>` 重新验证 safe-closed 条件；
- open 后复用原 `conversation_id`，下一次 submit 创建 fresh Run；
- list / preview / selection 不写数据库；
- 旧 Run 保持 ended，不执行 checkpoint replay 或事件追加。

本切片不包含 active process reconnect、crash reconciliation、arbitrary resume，也不把历史消息自动注入模型 prompt。

## 3. 逐版本审计

### v0.03 Deferred（10 行）

| 条目 | 状态 | 原因 / 下一触发器 |
|---|---|---|
| Role Context / Session / SQLite / Checkpoint / Resume | 已吸收 | v0.04 MVP 已提供核心能力，不作为新的 v0.03 选做包 |
| 完整 AgentMessage mailbox / recipient routing | 暂缓 | 需要跨进程 Worker 恢复或消息丢失的真实 Trace |
| Global Verify | 条件性 | 需要“局部通过但整体错误”的确定性 fixture 和 project claim contract |
| Semantic Reviewer | 暂缓 | 需要独立评估集和 reviewer catch-rate，不得以 LLM 主观意见代替 Verify |
| failed Worker retry / repair | 部分已吸收 | 已有 bounded Fix-Review；通用 retry 需证明不会重复副作用 |
| 严格预算 / 完整 Trace | 已拆分 | 预算已有基线；完整 Trace 属于 v0.07 |
| Permission Engine / HITL | 暂缓 | 依赖 v0.05.1 PermissionRequest、fingerprint 和 TOCTOU recheck |
| OS/container Shell sandbox | 后续版本 | 属于 v0.10 release security，不在当前分支扩张 |
| 强 TOCTOU / process-tree termination | 暂缓 | 缺少 stop 后残留进程或竞态的可复现失败 |
| Retrieval / RAG / Evidence | 后续版本 | 属于 v0.08 |

### v0.04.1（5 包）

| 候选包 | 状态 | 原因 / 本轮范围 |
|---|---|---|
| E1 Context Quality | 暂缓 | 没有 context overflow、压缩丢失或长期 Memory 的失败 Trace |
| E2 SQLite Hardening | **部分实现** | 只提取只读 integrity/foreign-key/schema Doctor；其余能力仍 backlog |
| E3 Recovery Reconciliation | 暂缓 | `recovery_required` 尚未证明为高频阻塞；不宣称 exactly-once |
| E4 MultiAgent Durability | 暂缓 | 没有跨进程 Worker 恢复用户故事和收益证据 |
| E5 Global Verify / Reviewer | 条件性 | 与 v0.03 Global Verify 合并看待；先补跨任务失败 fixture |

### v0.05.1（5 包）

| 候选包 | 状态 | 原因 / 下一触发器 |
|---|---|---|
| H1 Async / Streaming | 暂缓 | Worker thread 已避免 UI 冻结，尚无 token streaming 必需证据 |
| H2 ShellTask / 强制取消 | 暂缓 | 无长构建前台阻塞或 stop 后子进程残留 Trace |
| H3 Permission 交互 / 缓存 | 暂缓 | Runtime PermissionRequest、fingerprint、TOCTOU contract 尚未实现 |
| H4 ModelGateway / Retry | 暂缓 | 尚无第二 Provider 或 Provider 失败成为主要不稳定来源的证据 |
| H5 Event Distribution | 暂缓 | 当前单 UI observer 足够，未出现多消费者阻塞或内存增长 |

### v0.06.1（6 包）

| 候选包 | 状态 | 原因 / 本轮范围 |
|---|---|---|
| U1 Permission UX | 暂缓 | H3 前置不存在，禁止先画假弹窗 |
| U2 Shell Task UX | 暂缓 | H2 前置不存在，禁止用 UI 假装 streaming/cancel semantics |
| U3 Inspector Panels | **部分实现** | 只实现 Verification Inspector；Context/Trace/Cost 仍缺稳定输入契约 |
| U4 MultiAgent View | 条件性 | MultiAgent Runtime 已存在，但缺 team-to-TUI adapter 与相对收益验收故事 |
| U5 Session Picker / Resume | **部分实现** | 已实现 safe-closed conversation list/preview/open；crash/active/checkpoint resume 仍 backlog |
| U6 UX Hardening | 部分已有 | 窄终端已支持；其余项目应由真实兼容失败逐项提取 |

## 4. 停止条件

本轮明确停止在三个切片，不继续实现以下内容：

- async QueryEngine 或 token streaming；
- ShellTaskManager、background task 或强制进程树取消；
- Permission Dialog 或授权缓存；
- EventBus；
- arbitrary crash recovery；
- active process reconnect；
- checkpoint replay；
- durable MultiAgent mailbox；
- 空的 Context/Trace/Cost 面板；
- 未经失败 fixture 支撑的 Global Verify。

继续扩张会违反候选池的启动规则，并把当前 Draft PR 从可审查的小增量变成跨版本重构。
