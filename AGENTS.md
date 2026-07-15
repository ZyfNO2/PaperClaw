# PaperClaw 仓库协作规则

> 适用范围：`G:\PaperClaw` 全仓库。
> 本文件是仓库级规则的唯一事实源。`CLAUDE.md`、IDE 配置和 Hook 只能做适配或自动检查，不得维护冲突的第二套项目规则。

## 1. 项目定位

- PaperClaw 是面向 Coding / Research 的轻量 Agent Runtime。
- 轻量控制流采用 PocketFlow 风格；复杂 Workflow 以后通过 adapter 接入，不把 Runtime 写死在 LangGraph。
- SeededResearch 是首个 Research domain，但 Context、Tool、Permission、Session、Trace 和 Eval 必须保持 domain-independent。
- 项目目标是“可演示、可解释、可评估的校招项目”，不是一次建设生产级 Agent 平台。

## 2. 当前事实基线

执行任何版本任务前，先检查 `git log --oneline -15`、`git status --short`、当前 SOP、测试和 artifacts，不能只相信 Roadmap。

| 版本 | 当前状态 | 事实入口 |
|---|---|---|
| v0.04 | 已完成 / GO（MVP） | `Plan/drafts/PaperClaw_v0.04_ContextSessionSQLite_SOP草案.md`、`artifacts/v0_04/` |
| v0.05 | 已完成 / GO（MVP） | `Plan/PaperClaw_v0.05_HarnessQueryEngine_MVP_SOP.md`、`artifacts/v0_05/` |
| v0.06 | MVP 草案，未实现 | `Plan/drafts/PaperClaw_v0.06_Claw交互层_SOP草案.md` |
| v0.06.1 | Post-MVP 候选池 | `Plan/drafts/PaperClaw_v0.06.1_Claw交互增强候选池.md` |
| v0.07–v0.10 | 远期草案 | `Plan/drafts/`，执行前必须重新收缩 |

通用文档入口：

- 项目方向：`docs/desgin/PaperClaw_项目方向路径与约束.md`；
- Context 骨架：`docs/desgin/PaperClaw_上下文系统与提示词工程骨架.md`；
- 总路线：`Plan/PaperClaw_v0.02-v0.10_SOP总路线与风险推演.md`；
- 参考项目索引：`docs/reference/PaperClaw_参考项目与可复用模块索引.md`；
- 修复型题集：`Plan/testsets/PaperClaw_跨领域修复型测试题集_v0.01.md`。

## 3. MVP 与版本边界

- 每个版本默认分为“当前 MVP”和“Post-MVP 增强候选池”。
- MVP 只保留一个用户可见闭环、最多三个实施 Phase 和最小硬 Gate。
- 候选池没有默认执行顺序，不属于当前版本完成条件。
- 已经实现的额外代码不自动扩大验收范围。
- 只有真实失败 Trace 或下游用户故事证明必要时，才能把一个候选升级成独立 SOP。
- 完成当前版本后停止；没有用户授权，不自动进入下一版本。
- v0.03 的过度设计是反例，不作为后续版本模板。

## 4. 工作方式与授权

- 默认中文交流，技术术语保留英文。
- 论文正文或学术 Claim 改动：先提出方案，用户确认后再执行。
- 代码、配置和非论文文档：在用户授权范围内直接执行，事后报告。
- 用户只要求分析、审查或写 SOP 时，不修改 Runtime 代码。
- 用户要求实现时，完成实现、相关测试、文档同步和交接，不停在方案层。
- 架构、状态、数据模型、权限、依赖和主要 UI 变更前，简述影响范围、替代方案、风险和验证方式。
- 不为“架构完整”添加没有用户故事的模块。

## 5. 参考项目使用

编写或执行新 SOP 前，先读 `docs/reference/PaperClaw_参考项目与可复用模块索引.md`。

允许参考：

- `G:\PaperAgent`；
- `C:\Users\ZYF\Desktop\Paper\AutoResearchClaw`；
- `C:\Users\ZYF\Desktop\Paper\Draftpaper_loop_temp`；
- `C:\Users\ZYF\Desktop\Paper\academic-research-skills`。

使用要求：

- 记录参考仓库 commit 和 worktree；
- dirty 文件、日志、缓存和临时输出不是稳定上游；
- 优先复用失败分类、契约、状态机和测试思想；
- 迁移代码前检查 license、attribution、接口语义和数据契约；
- 每份 SOP 的参考表必须列具体文件、借鉴目标和禁止照搬项；
- Implementation Summary 或版本 handoff 说明实际借鉴内容以及为何没有直接复制。

## 6. 核心工程边界

- 对话 history 不能替代结构化 Task State。
- Context 压缩不能丢失目标、硬约束、决策、失败、未完成事项和 Evidence 引用。
- Prompt 只负责引导；危险操作由执行层 Permission / validation 强制拦截。
- 用户论文、PDF、DOI 和检索结果在核验前都是 candidate，不是 verified evidence。
- 学术方法组合是待验证 hypothesis，不自动等于创新。
- MVP 默认使用 SQLite；没有评估证据前不引入向量数据库、分布式服务或重基础设施。
- QueryEngine 是薄 façade，不直接执行 Tool、读写数据库或实现 domain 规则。
- TUI 是 QueryEngine 的客户端，不直接操作 Tool、Repository 或 Agent Prompt。
- Windows 当前 Shell backend 以 PowerShell 行为为准，不把它描述成通用 Bash sandbox。
- Secret 不得进入代码、Trace、artifact、日志或 memory note。

## 7. 实现与兼容

- 新能力优先通过 Protocol、adapter 或 feature flag 与旧路径并存。
- 不删除或修改公共 API，除非当前 SOP 明确授权并提供迁移路径。
- 保留用户和其他执行者的未提交改动；提交时只包含当前工作范围。
- 文件编辑使用原子写入或现有安全工具；涉及副作用时保留 operation / event 证据。
- 外部 I/O 可并发时使用有界并发、限流和 429 backoff；有数据依赖的步骤保持串行。
- 批量修改前先做 1–2 个 smoke test。

## 8. 测试与修复

- 先跑与改动直接相关的最小测试，再决定是否扩大回归范围。
- 单条测试小于 10 秒且串行总耗时小于 60 秒：直接串行。
- 相互独立且总耗时超过 60 秒：可以分发 subagent 并行；主线程同时做 Review、文档或下一步准备。
- 有数据依赖的测试不得并行。
- 超过 10 条相似用例时，先证明每条有独立发现价值；否则保留核心断言，其余降为 smoke。
- 同一 failure signature 连续 3 次受控修复仍无改善，停止并报告 blocked。
- 环境、安全或数据完整性风险超出 SOP 边界时立即硬停。
- skipped / xfail、节点存在或单元测试通过，不等于 live validation。

## 9. 状态与证据

报告状态时区分：

```text
planned
implemented
connected
offline_validated
live_validated
release_accepted
blocked
```

- Completion Report、README 和 SOP checkbox 都是 Claim，需要代码、测试、Trace 和磁盘 artifact 支撑。
- 不能把 `implemented` 写成 `live_validated`。
- 外部 Provider、真实模型、网络检索或 TUI 人工演示没有运行时，必须明确说明。
- Roadmap、增强候选和接口预留不得描述为已实现能力。

## 10. 文档与注释

- 修改 Context、Session、Memory、Permission、Tool、Trace、Eval、数据库模型或主要 UI 时，同步检查 `docs/desgin`、README 和当前 SOP。
- 实现偏离文档时，记录偏离点、原因、影响和后续处理。
- 注释解释设计意图、业务约束、边界条件、失败策略和兼容原因，不逐行翻译代码。
- 公共接口、状态模型、Agent 节点、权限、异步、重试、迁移和安全逻辑需要 docstring 或块注释。
- `TODO` / `FIXME` 必须包含原因、影响和解除条件。
- 外部实现的复制或改编保留来源、许可证和关键差异。

## 11. Phase 与 SOP 收尾

本节适用于实现 Phase，不适用于单纯讨论或远期草案编辑。

每个实现 Phase 完成时：

1. 运行相关测试并保存真实结果；
2. 同步当前版本 `artifacts/v0_XX/`、SOP、README 和必要设计文档；
3. 创建范围单一的 commit；
4. 使用可用的 Review subagent 审查 diff、测试、兼容、Trace 和文档；
5. 修复阻塞问题并再次提交，非阻塞项进入 known limitations。

宣布 SOP 完成前必须运行：

```powershell
python .claude/hooks/sop_completion_check.py
```

必须向用户报告：

- 未勾选项数量；
- 缺失交接物；
- 测试与真实演示状态；
- 是否可以宣布 GO。

SOP 未完成时不得用“总体完成”“基本完成”等措辞掩盖 pending 项。SOP 完成后至少有一个最终留档 commit，除非用户明确禁止提交。

## 12. 本地环境

- 平台：Windows 11，PowerShell；可能通过 WSL2 做兼容验证。
- Python 与中文文件默认 UTF-8；必要时使用 `python -X utf8`。
- 搜索文件优先使用 `rg` / `rg --files`。
- TUI 是 optional extra；无 TTY、CI 或依赖缺失时必须保留 CLI fallback。
- `.env`、缓存、临时测试目录和 Hook state 不提交。
