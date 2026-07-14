# PaperClaw v0.04.1：Context / Recovery Post-MVP 增强候选池

> 状态：**Backlog，不是执行 SOP**
> 更新：2026-07-14
> 来源：原 Runtime Protocol Closure 与 Recovery Reconciliation 大型 SOP 已拆除
> 规则：不得整体执行；一次最多选择一个候选包，重新写成小型 SOP 后再实现

## 目录

- [1. 拆除结论](#1-拆除结论)
- [2. 候选升级规则](#2-候选升级规则)
- [3. E1 Context Quality](#3-e1-context-quality)
- [4. E2 SQLite Hardening](#4-e2-sqlite-hardening)
- [5. E3 Recovery Reconciliation](#5-e3-recovery-reconciliation)
- [6. E4 MultiAgent Durability](#6-e4-multiagent-durability)
- [7. E5 Global Verify 与 Reviewer](#7-e5-global-verify-与-reviewer)
- [8. 明确不合并的能力](#8-明确不合并的能力)
- [9. 风险预案](#9-风险预案)
- [10. 参考](#10-参考)

---

## 1. 拆除结论

原 v0.04.1 一次性包含：

- durable AgentMessage；
- delivery / ack / dedup；
- Operation Ledger；
- Global Verify；
- Semantic Reviewer；
- Worker retry / repair；
- arbitrary crash recovery；
- file / Bash / external API reconciliation；
- Task / Lease recovery；
- migration、fault injection 和完整 audit。

这不是一个增量版本，而是多个独立系统。继续以单一 GO Gate 推进，会重现 v0.03 的过度设计。因此：

- 取消“v0.04 完成后必须做 v0.04.1”的默认顺序；
- 取消 v0.04.1-A / v0.04.1-B 总体完成定义；
- 所有能力降级为候选包；
- 没有真实失败或用户故事，不进入实现；
- 已经存在的探索代码不要求删除，但不对外宣称完整支持。

---

## 2. 候选升级规则

一个候选包只有同时满足以下条件，才能升级为新 SOP：

1. 出现可复现的真实失败，或明确阻塞下一个用户可见演示；
2. 能用一句用户故事描述价值；
3. 只修改一个主要机制；
4. 最多 3 个实施 Phase；
5. 有一个确定性失败 fixture；
6. 可单独 GO / NO-GO；
7. 不依赖另外两个尚未实现的候选包。

不允许以“未来可能需要”作为实施理由。

---

## 3. E1 Context Quality

### 候选能力

- provider-specific tokenizer；
- 更好的工具输出摘要；
- LLM-assisted compaction；
- source_ref 重新读取；
- Context precision / recall 评估；
- 显式长期 Memory 写入与淘汰。

### 启动触发器

- char4 estimator 连续导致实际 context overflow；
- 现有 compaction 在真实任务中丢失非硬约束但高价值信息；
- 长期跨 Session 任务出现明确记忆需求。

### 不一起做

Tokenizer、LLM summary 和长期 Memory 必须分别立项，不能打包。

---

## 4. E2 SQLite Hardening

### 候选能力

- schema v1 → v2 upgrade；
- upgrade 前 backup；
- restore drill；
- migration rollback；
- 多 writer contention；
- retention / purge；
- database integrity check。

### 启动触发器

- 第一次真实 schema 变更；
- SQLite lock 在正常使用中可复现；
- 发布安装包前需要升级兼容保证。

### MVP 切片示例

```text
用户用旧版数据库启动新版 PaperClaw
→ 自动备份
→ 顺序 migration
→ 数据保持
→ migration 失败时旧库仍可恢复
```

不在同一切片加入 Worker recovery 或 Context quality。

---

## 5. E3 Recovery Reconciliation

### 候选能力

- operation ID / attempt；
- side-effect started / terminal ledger；
- file write hash reconciliation；
- unknown Bash 人工确认；
- external API reconciliation adapter；
- fault injection。

### 启动触发器

- v0.04 的 `recovery_required` 已成为高频阻塞；
- 有一个具体 tool class 能通过确定性证据判断副作用结果；
- 用户确实需要 crash 后继续，而不是重新运行任务。

### 推荐最小切片

只做 FileWrite：

```text
operation.started
→ crash after atomic replace
→ restart
→ compare expected hash
→ committed / not_executed / manual
```

Bash 与外部 API 默认保持 manual，不与 FileWrite 一起实现。

---

## 6. E4 MultiAgent Durability

### 候选能力

- durable mailbox；
- recipient routing；
- delivery dedup；
- Task attempt 持久化；
- FileLease 持久化与显式接管。

### 启动触发器

- v0.03 进程内协作在真实长任务中因重启丢失关键结果；
- MultiAgent 相比单 Agent 已有明确收益证据；
- 用户故事要求跨进程恢复 Worker。

### 停止规则

如果单 Agent + Verify 能完成目标，不能仅为了架构完整性启动本包。

---

## 7. E5 Global Verify 与 Reviewer

### 候选能力

- project-level acceptance claim registry；
- local result → global completion Gate；
- semantic Reviewer；
- finding → fix → reverify；
- Reviewer catch rate 评估。

### 启动触发器

- 出现“局部测试通过但整体任务错误”的真实 fixture；
- v0.02 Verify 无法表达跨文件或跨 Task 的完成条件；
- Reviewer 能与确定性 Verify 分离，且有独立评估集。

这部分更接近 v0.07 Eval，不默认属于 Context / Session 版本。

---

## 8. 明确不合并的能力

以下组合禁止放进同一个小版本：

- Context quality + crash recovery；
- SQLite migration + durable MultiAgent；
- Operation Ledger + Semantic Reviewer；
- Provider retry + FileLease recovery；
- Long-term Memory + Global Verify；
- Bash reconciliation + external API reconciliation。

每个组合都应由独立 Trace 证明必要性。

---

## 9. 风险预案

| 风险 | 预案 |
|---|---|
| Backlog 又变成默认路线 | AGENTS 明确“候选不进入当前 Gate” |
| 因已有代码而倒推需求 | 先写失败 fixture，再决定是否保留或扩展 |
| 所有候选互相依赖 | 选择可单独交付的 adapter / tool class |
| 把 recovery 宣称为 exactly-once | 使用 committed / not_executed / unknown 三态 |
| 自动化范围过大 | 无法确定性证明时保持 manual / blocked |

---

## 10. 参考

- [`PaperClaw_v0.04_ContextSessionSQLite_SOP草案.md`](PaperClaw_v0.04_ContextSessionSQLite_SOP草案.md)
- `AutoResearchClaw/researchclaw/pipeline/runner.py`：checkpoint 与 resume 思路
- `AutoResearchClaw/researchclaw/collaboration/dedup.py`：消息去重思路
- `Draftpaper_loop_temp/draftpaper_cli/loop_contract.py`：稳定事件与状态词汇

参考只用于提取失败模式和契约。候选升级为 SOP 时仍须重新记录 commit、worktree 和许可证边界。
