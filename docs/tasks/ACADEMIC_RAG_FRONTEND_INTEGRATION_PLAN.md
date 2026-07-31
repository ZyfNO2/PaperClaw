# Academic RAG 双仓收口与真实前端集成计划

> 创建日期：2026-07-31  
> 适用仓库：`ZyfNO2/PaperClaw`、`ZyfNO2/PaperAgent`  
> 状态：`execution_ready / P0 GO blocked`  
> 文档规则：本文件在两个仓库保持语义一致；远端代码、测试、CI 与最新 Handoff 优先于本文中的快照 SHA。

## 1. 当前基线

| 仓库 | 工作分支 | 计划创建前 HEAD | 关联 PR | 当前阶段 |
|---|---|---|---|---|
| PaperClaw | `codex/academic-rag-h2-retrieval` | `99ebb0ce4676838d3670e345a2614fb1fd1f079b` | Draft PR #76 | H2 多通道检索、冲突检测与 corrective retrieval 已实现，P0 未通过 |
| PaperAgent | `codex/academic-rag-h3-reasoning` | `f1355fba738d48ea9dc09c65bad2122238a10a32` | Draft PR #66 | H3 Query Planner、Evidence Ledger、Claim 校验与八类 Artifact Gate 已实现，P0 未通过 |

已确认的前端基础：

- PaperClaw 前端重构提交：`5891d1efbc840aa81ba2a2c1c3e06ab7619cb9f2`；
- 该提交已经是 PaperClaw 当前开发链的祖先，不需要再次 cherry-pick；
- PaperClaw Workbench 的模块化 CSS/JS、状态组件、页面容器、抽屉、表格、Trace 与错误状态可以作为交互参考；
- PaperAgent 已有面向科研流程的 PWA 信息架构，但主要页面仍依赖 `PA.data` Mock 数据，尚未形成真实产品闭环。

## 2. 本阶段唯一目标

在不扩展新研究能力的前提下，完成以下真实闭环：

```text
真实论文文件
  -> PaperClaw 导入、版本化、解析、索引
  -> 多通道检索与 locator resolve
  -> PaperAgent Query Planner / Evidence Ledger / Claim validation
  -> 八类 evidence-bound Artifact revision
  -> PaperAgent 前端展示 Evidence、Claim、原页定位和审批操作
  -> Approve / Reject / Revise 写入 append-only revision history
```

本阶段完成后，用户应能在一个真实界面中完成：

```text
上传论文
-> 创建研究任务
-> 查看检索过程
-> 查看 accepted / rejected / conflicted Evidence
-> 点击 Claim 回到 paper / page / object / bbox
-> 查看 Baseline / Module / Compatibility / Experiment Artifact
-> Approve / Reject / Revise
```

## 3. 双仓职责边界

### 3.1 PaperClaw 是基础设施事实源

负责：

- Project Workspace 与论文文件生命周期；
- PaperRecord、PaperVersion、AcademicObject、EvidenceLocator；
- 解析、索引、retrieve / expand / resolve；
- Evidence Bundle、Memory、Artifact revision store；
- Trace、权限、受限工具与 Desktop 基础设施。

PaperClaw 不负责：

- 最终 baseline 选择；
- gap、module、novelty 与实验科学判断；
- 学术结论写作和人工审批策略。

### 3.2 PaperAgent 是学术执行事实源

负责：

- Query classification、decomposition、rewrite 与 routing；
- accepted / rejected / conflicted Evidence Ledger；
- Claim 与 citation / locator 校验；
- Baseline、Gap、Module、Compatibility 与 Experiment 推理；
- 八类 Artifact 草稿与 ReviewDecision；
- 人工审批和研究结果导出。

PaperAgent 禁止：

- 直接读取 PaperClaw SQLite、页面缓存、模型缓存或向量文件；
- 建立第二套 PaperRecord、EvidenceLocator 或 Artifact 持久化 schema；
- 在 PaperClaw 不可用或版本不兼容时静默退回伪造数据。

### 3.3 前端调用边界

```text
PaperAgent PWA
  -> PaperAgent Application/API
  -> PaperAgent academic adapter
  -> PaperClaw public Python/REST contract
```

前端不得直接：

- 调用 PaperClaw 数据库；
- 构造学术 Prompt；
- 执行检索或方法判断；
- 绕过 Application/API 直接调用 repository、tool 或 model。

## 4. 前端复用策略

### 4.1 可以复用

以 PaperClaw `5891d1e` 及后续 Workbench 为来源，优先复用或等价迁移：

- design tokens；
- typography、spacing、density 与 responsive 规则；
- card、badge、chip、table、drawer、modal、toast；
- loading、empty、partial、failed、blocked、retry 状态；
- progress、timeline、Trace 与 budget 展示模式；
- Inspector / detail drawer 的信息组织；
- Desktop / Browser 一致的安全静态资源策略。

所有迁移必须记录来源提交和具体文件，不得复制旧 Mock 业务状态。

### 4.2 不可以整套搬运

不得把 PaperClaw 的 Runtime Console、Provider、Mission 等整套业务页面直接替换 PaperAgent。

PaperAgent 必须保留现有科研信息架构：

- Projects；
- Research Request；
- Literature / Papers；
- Evidence；
- Baseline；
- Gap；
- Method；
- Compatibility Matrix；
- Experiments；
- Quality Gate；
- Artifacts；
- Runs；
- Settings。

原则：**复用视觉组件和交互契约，不复制另一套产品业务。**

## 5. 执行顺序

必须按顺序执行。前一 Gate 未通过时，不得把后一阶段描述为完成。

## WP-0：重新审计与冻结基线

1. 重新检查两个仓库的默认分支、目标分支、HEAD、PR、CI、Handoff 和未完成 Review；
2. 固定本轮 PaperClaw/PaperAgent exact commit pair；
3. 校验 `academic.v1` schema digest、Python contract 与 REST fixture 一致；
4. 记录 Python、Node、浏览器、操作系统与可选模型环境；
5. 确认 `PA.data` 的所有使用位置及现有后端 API 覆盖范围；
6. 建立“页面需要的数据 → Application/API → PaperAgent domain → PaperClaw contract”映射。

完成条件：

- exact commit pair 可复算；
- contract digest 一致；
- 未解决 Review、CI 和真实环境缺口均有明确状态；
- 不依据旧文档重复开发已有能力。

## WP-1：双仓真实集成 Tracer

实现一个可重复执行的最小真实链路：

1. 创建临时 Project；
2. 导入一份真实生成 PDF 或许可明确的测试 PDF；
3. PaperClaw parse / index；
4. 运行 lexical + dense，可用时加入 visual；
5. retrieve 后 resolve 至 canonical locator；
6. PaperAgent 执行 decomposition、Evidence Ledger 与 accepted-only context；
7. 生成至少 Evidence Bundle、Baseline Card、Compatibility Matrix、Experiment Matrix；
8. 写入 PaperClaw append-only Artifact revision；
9. 读取 revision 并回放 Claim -> locator -> page/object/bbox。

必须覆盖失败路径：

- PaperClaw 不可用；
- `academic.v1` 版本或 digest 不兼容；
- locator 对应旧版本或不可 resolve；
- Evidence conflicted / insufficient；
- Artifact 写入失败；
- 任务取消与重启后的确定终态。

完成条件：

- 成功链路和失败链路均有结构化测试；
- 不使用私有数据库或缓存接口；
- generated PDF 测试不得描述为真实科学质量验证。

## WP-2：PaperAgent Application/API 与前端数据层

### 2.1 建立统一 `PA.api`

用一个有界 API client 替换生产路径中的直接 `PA.data` 读取：

- 请求超时与取消；
- 结构化错误；
- loading / empty / partial / blocked / failed 状态；
- Task polling 或 SSE；
- schema/version 检查；
- 不记录 Secret、Authorization 或原始 Provider payload。

`PA.data` 只允许保留为显式 Demo fixture，并满足：

- 默认生产模式关闭；
- UI 明确显示 Demo；
- Demo 与真实数据不能混合；
- 测试能够证明生产路径不会静默 fallback 到 Mock。

### 2.2 最小 API 面

开始编码前先审计现有 API；仅补齐真实页面所需的最小端点或 application service：

- Project list / detail / create；
- Paper list / import / version / parse-index status；
- Task create / status / events / cancel；
- Evidence Ledger 与 ClaimEvidenceMap；
- Artifact list / detail / revisions；
- Approve / Reject / Revise；
- locator resolve 与 page/region asset readback；
- diagnostics / readiness / capability version。

不得为前端再造平行业务模型。新增 response schema 必须由 domain/application contract 投影产生。

## WP-3：四个真实页面 MVP

先只接通以下四个页面，其他页面可以通过 Artifact 详情间接展示：

### 3.1 Projects

- 项目列表与当前项目；
- 论文数、任务数、最近 Artifact、当前 Gate；
- 创建项目；
- loading / empty / error 状态。

### 3.2 Papers / Literature

- 导入论文；
- 版本、解析和索引状态；
- metadata candidate / confirmed；
- partial / failed 原因；
- 打开论文对象或页面。

### 3.3 Evidence

- accepted / rejected / conflicted / unknown 分类；
- channel、score、source、paper version 与 locator；
- Query rewrite、corrective round 和 stop reason；
- Claim -> Evidence -> page/object/bbox Inspector；
- Evidence 不足时明确 abstain / REVISE。

### 3.4 Artifacts / Runs

- 八类 Artifact 列表；
- revision history；
- `verified / inferred / proposed / unknown` 标记；
- Approve / Reject / Revise；
- 运行状态、Trace、预算、错误与取消。

完成条件：

- 四个页面在生产模式下全部来自真实 API；
- 页面刷新后状态可恢复；
- 不依赖内存 Mock 才能显示核心内容。

## WP-4：关键科研交互闭环

将以下操作做成一个浏览器可执行的 E2E：

```text
Create Project
-> Import Paper
-> Create Research Task
-> Observe Retrieval/Corrective Trace
-> Inspect Evidence Ledger
-> Open Claim Locator
-> Read Page/Region
-> Open Artifacts
-> Approve or Request Revision
-> Verify New Artifact Revision
```

硬要求：

- 每个 Claim 必须有 accepted Evidence；
- locator 无法 resolve 时 fail closed；
- conflicted evidence 不得进入 accepted-only generation context；
- 未批准 Artifact 不得标记 final；
- revision history append-only；
- UI 不得把 Fake/Mock/Generated PDF 描述成真实论文或人工验收。

## WP-5：组件整理与兼容性

1. 从 PaperClaw 迁移所需 design tokens 和组件模式；
2. 保留 PaperAgent hash route、PWA、CSP 与现有页面 ID；
3. 避免引入大型前端框架，除非仓库现有结构无法满足且有可验证收益；
4. Windows、Linux、窄窗口和键盘操作必须保持可用；
5. 主题、语言、密度和导航状态不得影响业务数据正确性；
6. 静态资源必须进入 wheel/sdist，并通过 package-data smoke。

## WP-6：测试、CI 与验收

### 6.1 必须执行

PaperClaw：

- Academic retrieval / conflict / corrective 定向测试；
- Paper、REST、Desktop 相关测试；
- 全量非 live 回归；
- lint/type/build；
- 相关 GitHub Actions。

PaperAgent：

- Academic workflow / claim / artifact / adapter 定向测试；
- API contract 测试；
- JS syntax 与静态资源 smoke；
- Browser E2E；
- 全量回归、strict mypy、coverage、build；
- required PaperClaw integration CI。

### 6.2 测试分级

报告必须明确区分：

- unit；
- Mock/Fake；
- generated-PDF integration；
- real local paper；
- real MiniLM / ColQwen2 GPU；
- real LLM；
- Native Windows browser/Desktop；
- human scientific review。

任何未执行项标记 `pending`、`blocked` 或 `not_verified`，不得写成 PASS。

### 6.3 工程 Gate

本计划的工程阶段可以标记完成，仅当：

- exact commit pair、schema digest 与环境可复算；
- generated-PDF 双仓 E2E 通过；
- 四个真实页面不依赖 Mock；
- Claim locator 可回放；
- 审批产生新的 append-only revision；
- 定向、全量、CI、build 通过；
- 没有 Secret、PDF、模型权重、缓存、数据库或原始日志进入 Git。

## 6. P0 GO 仍需的真实 Gate

即使工程阶段完成，也不得自动宣布 P0 GO。至少仍需：

- 32 个 blinded questions 与人工 gold labels；
- 两个跨论文 baseline/module 场景的人工决策；
- critical unsupported claim、citation mismatch、false GO 均为 0；
- 真实 MiniLM/ColQwen2 能力按实际环境验证；
- 真实学术 LLM trace；
- Native Windows 全流程点击；
- human reviewer 对 Artifact 和最终决策的审批。

## 7. 非目标

本阶段不做：

- 新一轮前端视觉重设计；
- Relation Graph；
- 更多自由 Agent 或无限检索循环；
- 公开多租户、认证、计费或配额；
- 全文 PDF 编辑器；
- 通用 IDE；
- 新 Artifact Store；
- 大规模模型替换；
- 为了页面完整而伪造尚无后端支持的数据。

## 8. Commit 与 PR 规则

- 保持当前 Draft PR；
- 不自动合并，不改为 ready for review，不删除分支；
- 不直接向 `main` / `master` 推送功能代码；
- 每个工作包使用小步、可回滚 commit；
- 两仓 contract/Handoff 修改在同一工作批次同步；
- 推荐提交顺序：

```text
test(integration): add dual-repo academic tracer
feat(api): expose frontend academic projections
feat(web): replace mock data with bounded api client
feat(web): connect projects and papers pages
feat(web): connect evidence and artifacts workflow
test(browser): cover claim locator and review revision
docs(handoff): record frontend integration evidence
```

## 9. Stop Conditions

只有以下情况允许停止开发并标记 blocked：

- 缺少真实 GPU、模型、API Secret、论文许可或人工标签；
- 必须执行 Native Windows 点击或人工科学审批；
- 目标分支发生不可安全自动解决的冲突；
- 继续实现需要超出本文范围的大规模架构重写。

停止前必须完成所有不依赖真实环境的代码、测试、runner、配置示例和文档，并提交最后一次 commit。

## 10. 最终 Handoff

最终报告必须包含：

- 两个仓库、分支、PR、最终 commit SHA；
- exact commit pair 与 schema digest；
- 已完成内容和主要文件；
- 页面 → API → domain → PaperClaw contract 映射；
- 测试命令、数量、CI run 与结果；
- Mock、generated PDF、真实论文、真实模型、真实 LLM、Native Windows、人工验收的区分；
- 未验证能力、已知限制和 stop condition；
- 用户需要执行的真实验收步骤、预期结果和需返回的日志/截图。

## 11. Execution record (2026-07-31)

All implementation work packages in this plan are implemented on the Draft PR
branches. Production Projects, Literature, Evidence, Artifacts, and Runs paths use
bounded APIs; demo data requires `?demo=1`; canonical locator resolution and asset
readback, accepted-only evidence, eight artifact drafts, and append-only human
review revisions are covered by API, generated-two-PDF integration, and Playwright
tests. Exact heads and verification counts are recorded in
`docs/handoff/ACADEMIC_RAG_DUAL_REPO_HANDOFF.md` section 20.

This is an engineering implementation completion record, not scientific GO
evidence. P0 remains `NO-GO` and both PRs remain Draft.
