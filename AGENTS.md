# PaperClaw 项目协作入口

> 本节是当前项目的最高优先级仓库级说明。下方旧规则来自 PaperAgent，尚未完成清理；若与本节冲突，以本节为准。

## 项目定位

- PaperClaw 是面向 Coding / Research 场景的轻量 Agent Runtime，不是单一 LangGraph 工作流。
- 首个深度验证 domain 是 SeededResearch 学术裁缝，但 Runtime 不得与论文流水线强耦合。
- 核心方向是 Context、Session / Memory、Tool Registry、Permission、Trace、Recovery、QueryEngine、RAG 与 Eval。
- 一周目标是可演示、可解释、可评估的 MVP；一个月目标是形成可运行的轻量 Claw。

## 当前文档基线

- 项目方向与约束：`docs/desgin/PaperClaw_项目方向路径与约束.md`。
- 上下文系统骨架：`docs/desgin/PaperClaw_上下文系统与提示词工程骨架.md`。
- 总路线与风险推演：`Plan/PaperClaw_v0.02-v0.10_SOP总路线与风险推演.md`。
- 首批跨领域修复型测试题集：`Plan/testsets/PaperClaw_跨领域修复型测试题集_v0.01.md`，当前为设计稿，覆盖图像识别、大语言模型、三维重建各 1 题。
- v0.04 当前执行文件：`Plan/drafts/PaperClaw_v0.04_ContextSessionSQLite_SOP草案.md`，已重构为 Context / Session / SQLite MVP 收口版。
- v0.04.1 与 v0.05.1 文件是 Post-MVP 增强候选池，不是默认执行 SOP，也不属于当前版本完成 Gate。
- v0.05 当前设计文件：`Plan/drafts/PaperClaw_v0.05_HarnessQueryEngine_SOP草案.md`，只做薄 QueryEngine façade 与现有 Runtime 接线。
- 当前实施顺序：v0.02 Verify/Reflection → v0.03 MultiAgent → v0.04 Context/SQLite → v0.05 Harness/QueryEngine → v0.06 Claw TUI → v0.07 Trace/Eval → v0.08 Retrieval/RAG → v0.09 SeededResearch → v0.10 Release。
- v0.04 正在执行；v0.05–v0.10 尚为 SOP 草案，必须在前置版本通过后结合真实 Trace 冻结，不能描述为已经实现。

## 既有项目参考

- 在规划、实现、调试或遇到设计阻塞时，可以随时查阅以下既有项目作为思路、流程和实现对照，不必重复征求用户许可：
  - `G:\PaperAgent`：既有 LangGraph / PaperAgent 研究工作流、检索链路、状态与工程实践参考；
  - `C:\Users\ZYF\Desktop\Paper\Draftpaper_loop_temp`：论文生成与循环工作流参考；
  - `C:\Users\ZYF\Desktop\Paper\AutoResearchClaw`：自主科研 Agent、Pipeline、模型调用与容错参考；
  - `C:\Users\ZYF\Desktop\Paper\academic-research-skills`：学术 Skill、Prompt、证据与研究方法流程参考。
- 查阅这些项目时优先复用已经验证的思路、契约、测试方法和失败经验，避免重复踩坑。
- 参考不等于直接复制：迁移代码或设计前必须核对许可证、依赖、数据契约、接口语义和 PaperClaw 当前边界。
- PaperClaw 的 Context、Permission、Tool、Session、Trace 和 Eval 仍须保持独立，不能与任一参考项目形成不必要的运行时强耦合。
- 详细模块、路径、许可证风险和分版本阅读清单见 `docs/reference/PaperClaw_参考项目与可复用模块索引.md`。

## 参考优先规则

- 编写或执行新的 SOP 前，必须先阅读 `docs/reference/PaperClaw_参考项目与可复用模块索引.md`，再选择与当前版本直接相关的参考文件。
- 每份新 SOP 必须包含“既有实现参考（执行前必读）”，列出具体项目、具体文件、借鉴目标和禁止照搬项；禁止只写“参考某项目”。
- 实施开始时记录参考仓库的 commit 和 worktree 状态；dirty 文件、日志和临时输出不得当作上游稳定实现。
- Implementation Summary 必须说明实际借鉴了哪些契约、状态机、测试或失败策略，以及为何没有直接复制原模块。
- substantial code migration 必须核对 license、attribution、商标和商业使用限制；不确定时只借鉴思想并独立实现。

## 核心工程约束

- 轻量 Agent Loop 优先采用 PocketFlow 风格控制流；复杂 Workflow 可通过 LangGraph adapter 接入。
- Context、Permission、Tool、Session、Trace 和 Eval 必须独立于具体图框架。
- 对话历史不能替代结构化 Task State；上下文压缩不得丢失目标、约束、决策、失败尝试和待办。
- Prompt 只负责引导；危险操作必须由独立 Permission Engine 在执行层拦截。
- 用户提供的论文和检索结果在核验前都是 candidate，不得直接升级为 verified evidence。
- 学术方法组合是待验证假设，不等于创新；科研叙事不得超过证据。
- MVP 默认使用 SQLite，核心机制验证前不引入过重基础设施。
- 核心模块必须保留可复现用例和可观察 Trace，服务于学习、演示和面试追问。
- 修改 Context、Session、Memory、Permission、Tool、Trace、Eval 或数据库模型时，同步检查 `docs/desgin`。
- 每个版本默认拆成“当前 MVP”与“Post-MVP 增强候选池”；增强候选不得自动进入当前验收 Gate。
- 当前 MVP 原则上只保留一个用户可见闭环、最多三个实施 Phase 和一组最小硬 Gate；超过该边界必须说明为何不能延期。
- 已经实现的额外代码不自动成为版本完成条件；先通过真实失败或下游阻塞证明必要性，再将单个候选升级为独立 SOP。

## 工程化代码注释

- 新增或修改代码时，注释必须达到真实团队工程协作标准，优先解释设计意图、业务约束、边界条件、失败策略、兼容原因和不直观取舍，而不是逐行翻译代码。
- 公共接口、核心状态模型、Agent 节点、工具、权限判断、异步并发、重试/降级、数据迁移和安全敏感逻辑必须有必要的 docstring 或块注释。
- 对临时兼容、已知风险和后续清理使用可检索标记，如 `TODO`、`FIXME`，并说明原因、影响与解除条件；禁止只写“以后优化”。
- 注释必须随实现同步更新；过期、误导或与代码矛盾的注释视为缺陷。
- 不为显而易见的赋值、循环和语法添加噪声注释；注释密度服从可维护性，不以数量作为质量指标。
- 复制或改编外部实现时，在代码或相邻文档中保留来源、许可证和关键差异说明。

---

# AI 工程协作增强规则

## 测试策略

> **所有执行者必读**。本节规则适用于项目中的任何 AI 执行者（执行 AI、SOP AI、Review AI 等），不限于特定 SOP。

### 核心原则：能并行就并行，不值得并行就串行，并行时不空转

1. **可并行的测试必须并行**：多个相互独立的测试用例（如多题目端到端测试、多节点单元测试、多 validator 各跑一次）必须分发 subagent 并行执行，禁止逐条串行等待。

2. **分发前评估并行价值**：
   - 单条测试 <10s 且串行总耗时 <60s → 直接串行跑，不值得 subagent 开销。
   - 总耗时 >60s 且各用例相互独立 → 必须分发 subagent 并行。
   - 如果用例之间有数据依赖（如 Loop B 依赖 Loop A 的输出）→ 不能并行，串行执行。

3. **大规模测试需先判断必要性**：
   - 超过 10 条用例的大规模回归测试，先评估"是否每条都有独立发现价值"。
   - 如果前 3 条已覆盖核心路径，后续用例降级为 smoke test（只验证不 crash、`final_recommendation` 非空），不做全量断言。
   - 禁止为了"看起来全面"而跑 20 条本质重复的测试。

4. **并行时主线程不空转**：
   - subagent 跑测试时，主线程必须同时做推进性工作：review 已完成的代码、编写下一阶段的 prompt 草稿、检查文档一致性、准备下一阶段测试数据、撰写进度报告。
   - **禁止**分发 subagent 后主线程空转等待。等待 = 浪费。

5. **测试结果汇总后统一判断**：
   - 所有并行 subagent 返回后，主线程统一汇总 pass/fail。
   - 全 pass → 进入下一阶段。
   - 有 fail → 分析失败模式，决定是全部重跑还是只重跑失败项。不逐条处理。

### 并行分发示例

```
# 场景：5 个题目端到端测试，每个 ~3min，相互独立

# ❌ 错误：串行跑 5 个，等 15min
for topic in topics:
    run_e2e(topic)  # 主线程阻塞 15min

# ❌ 错误：分发后空转等待
subagents = [dispatch(run_e2e, t) for t in topics]
# 主线程什么都不做，等 subagent 返回 ← 浪费

# ✅ 正确：分发后做推进性工作
subagents = [dispatch(run_e2e, t) for t in topics]
review_completed_code()           # review 已完成节点
write_next_phase_prompts()         # 写下一阶段 prompt 草稿
check_docs_consistency()           # 检查文档一致性
# subagent 返回后统一汇总
results = collect_all(subagents)
if all(r.passed for r in results):
    proceed_to_next_phase()
else:
    rerun_failed([r for r in results if not r.passed])
```

---

## 认知盲区提醒

- 如果用户的需求描述过于直接跳到实现，AI 应先反问产品目标、用户场景、成功标准，避免为了做功能而做功能。
- 当发现用户可能把“实现方案”误当成“真实需求”时，AI 应主动区分：用户目标、当前方案、可选方案、推荐方案。

## 工程决策透明化

- 涉及架构、状态管理、数据模型、权限、依赖、路由、主要 UI 结构的变更时，AI 必须先说明自己的技术判断依据。
- 每次重要实现前，AI 应简短列出：本次改动影响范围、可能破坏的模块、验证方式。
- 如果存在多个实现路径，AI 应给出至少两个方案，并比较复杂度、扩展性、风险和开发成本，再推荐一个。
- 不允许为了短期跑通而引入长期难维护的临时方案；如必须临时处理，必须标记 TODO、说明原因。

## 文档与实现一致性

- 所有大的涉及功能、信息架构、数据结构、权限模型或主要布局的调整，都要询问用户是否同步更新 `/docs` 中对应文档，并提出更新大纲。
- 定期检查当前项目实际功能、UI、数据模型、交互流程是否与 `/docs` 规范一致；发现不一致时，主动提醒用户选择：更新代码、更新文档、或记录偏差原因。
- 当代码实现与文档方案发生偏离时， AI 必须说明偏离点、偏离原因、潜在影响。
- 每轮完整实现或测试收尾后，同步检查并按需更新 `artifacts/v0_01/test_report.md`、`artifacts/v0_01/known_limitations.md` 与当前执行中的 SOP 文档，避免代码、测试结论与交接物漂移。
- 终端过程日志如 `thinking / tool / result / done` 默认只作为测试/调试观测能力；若无用户额外要求，不把高频过程日志设为普通运行默认输出。

## 阶段交付规则

> **Re7.6 起生效**。AI 完成一个完整 Phase（如 Phase B 节点迁移、Phase C Job worker）后必须执行以下留档与审查动作。

1. **Commit 留档**：在确认当前 Phase 的测试通过后，立即执行 `git commit` 保存该 Phase 的全部代码变更；commit message 须说明 Phase 目标、影响节点/模块、验证结果。
1a. **SOP 收尾 commit**：每次一个 SOP 被宣布完成时，在完成对应测试、交接物同步和 SOP 自检后，必须至少执行一次 `git commit` 留档当前 SOP 的最终状态；除非用户明确禁止 commit。
2. **分发 Review 子代理**：commit 后必须调用 `Task` 子代理（subagent_type=search 或 general_purpose_task）对本次 Phase 的 diff 进行审查，审查范围包括：
   - 测试是否覆盖新增/修改路径（统一路由路径、legacy 回退路径、异常路径）
   - trace 字段是否一致记录 `provider`、`contract_id`、`model` 等调试信息
   - 环境 feature flag 默认值是否符合 Phase 决策（默认启用还是默认关闭）
   - 是否保持向后兼容（保留旧调用路径、不删除 public API）
   - 文档（SOP / plan / README）是否需要同步更新
3. **Review 结果处理**：子代理返回后，由主线程汇总 review 结论；若发现阻塞问题，在当前 Phase 内修复后重新 commit；非阻塞问题记录到交接包或 TODO。
4. **SOP 完成度自检 (Re7.6 起新增)**：AI 在宣布"当前 SOP 已完成"或准备结束 SOP 工作流前，必须运行 SOP 完成度检查 hook：
   - 命令：`python .claude/hooks/sop_completion_check.py`（或 opencode 侧 `python .opencode/hooks/sop_completion_check.py`）
   - 该 hook 会扫当前 SOP 文档所有 `- [ ]` checkbox + 查 `artifacts/reN_M/` 交接包产物齐备性
   - AI 必须把 hook 输出贴给用户，并明确回答：剩余多少项未勾选、哪些交接包不齐、是否可以宣布完成
   - 若 hook 报告"仍有 N 项未勾选"，AI 不得宣称 SOP 全量完成；必须先补齐或明确标注"剩余项为已知阻塞，下一位执行者处理"
   - 非 SOP 上下文下 hook 静默退出，不会污染普通回合

## 用户能力提升

- AI 在给出实现结果时，应适度解释关键工程判断，让用户理解为什么这样做，而不只是交付代码。
- AI 不应一味迎合用户的即时指令；当更好的长期方案存在时，应礼貌但明确地提出。

## 工程效能规则

### 并发优先

- I/O 密集型操作（HTTP 请求、数据库查询、文件读写）必须使用异步并发（`asyncio.gather`、`asyncio.Semaphore`），禁止串行 `await` 循环。
- 公共 API 调用需加限流（Semaphore 3-5 并发，exponential backoff on 429）。
- 搜索类任务跨源（crossref/github/arxiv）天然可并发，禁止逐源串行等待。

### 长任务委派

- 预计运行超过 60 秒的任务（模型评测、全量审计、数据构建），必须委派给子代理（Task tool）异步执行。
- 主线程只做规划、调度、结果汇总和用户交互，不阻塞等待。
- 子代理完成后通过消息通知，主线程负责验收和报告。
- **相互独立的 Loop 可拆成多个子代理并行执行**（如 Loop 3 分 2 批 × 子代理，Loop 4 单独子代理），无需串行等待。
- **主线程在子代理运行期间必须做有用的工作**：撰写进度报告、review 代码、检查漏洞、更新文档、准备下一阶段材料。禁止空转等待。

### API 兼容扩展原则

- 新增 backend/provider/adapter 时，禁止修改或删除现有调用代码。
- 新增功能应与旧功能并存，通过配置/参数切换。
- 修改必须向后兼容，原有调用方无需任何改动。

### 自主修复与硬停规则

> **Re7.6 起生效**。AI 在执行 SOP 工作包时遵循以下修复秩序：

1. **小修自主执行**：遇到代码/测试/配置问题时，先按 SOP 指引和项目规则自行修复（改 prompt、调整 mock、修路径、适配接口等），修复后重跑验证。
2. **硬停条件**：只有遇到以下两种情况才停下报告用户：(a) **同一 failure signature 连续 3 次受控修改仍未改善**（SOP §9.2 NO-GO 规则），或 (b) **问题超出 SOP 范围且影响安全/数据完整性**（如 secret 泄露、SSRF 漏洞、数据库损坏风险）。
3. **批量前 smoke test**：批量操作（如多节点迁移、多 fixture 生成）前先做 1-2 个 smoke test，通过后全速批量。禁止无脑全量提交报错后逐条修。
4. **修复不可通用户确认**：SOP 范围内的 prompt/interface/schema 调整不需用户确认即可执行，事后通过交接包报告。

---

## AI 工程协作增强规则（原始）
