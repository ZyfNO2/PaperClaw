# PaperClaw 参考项目与可复用模块索引

> 文档性质：参考实现导读，不是依赖清单  
> 更新时间：2026-07-13  
> 适用范围：PaperClaw v0.02+ SOP、SeededResearch、Trace / Eval 与后续架构设计  
> 核心原则：先读已验证实现和失败经验，再设计 PaperClaw 独立契约；优先借鉴接口、状态机、Gate、测试和 Trace，不整仓复制

## 目录

- [1. 使用规则](#1-使用规则)
- [2. 参考项目总览](#2-参考项目总览)
- [3. PaperAgent](#3-paperagent)
- [4. AutoResearchClaw](#4-autoresearchclaw)
- [5. Draftpaper-loop（用户所称 DeepLoop）](#5-draftpaper-loop用户所称-deeploop)
- [6. academic-research-skills](#6-academic-research-skills)
- [7. Academic Method Tailoring](#7-academic-method-tailoring)
- [8. Novelty / 创新点审查](#8-novelty--创新点审查)
- [9. 按 PaperClaw 版本阅读](#9-按-paperclaw-版本阅读)
- [10. 后续 SOP 强制模板](#10-后续-sop-强制模板)
- [11. 禁止直接复用的内容](#11-禁止直接复用的内容)
- [12. 未找到与待复核项](#12-未找到与待复核项)

---

## 1. 使用规则

### 1.1 可信度标签

| 标签 | 含义 |
|---|---|
| `verified_now` | 本轮已确认路径和内容存在 |
| `known_recent` | 来自最近 PaperAgent 工作记录，执行前必须重新核对当前代码 |
| `located_only` | 只确认目录或入口存在，尚未完成模块级审计 |
| `not_found` | 在已知路径未找到，不得假装存在 |

### 1.2 正确使用方式

执行者在实现前应回答：

1. 参考项目解决的真实问题是什么；
2. 哪个文件定义了核心契约；
3. 哪个文件展示失败、重试或 Gate；
4. 哪些测试证明行为成立；
5. 哪些内容与 PaperClaw domain 无关；
6. 许可证是否允许复制；
7. PaperClaw 应复用思想、写 adapter，还是独立重写；
8. 引入后如何通过 Offline fixture 验证。

### 1.3 默认迁移策略

```text
优先级 1：复用测试案例和失败分类
优先级 2：复用数据契约和状态转移思想
优先级 3：写独立 adapter
优先级 4：小段代码迁移并保留许可与差异说明
最后选择：复制大型模块或形成运行时强依赖
```

---

## 2. 参考项目总览

| 项目 / Skill | 路径 | 主要价值 | 主要风险 | 状态 |
|---|---|---|---|---|
| PaperAgent | `G:\PaperAgent` | LangGraph 科研工作流、Retrieval、Evidence Context、Workbench、SeededResearch | 旧阶段耦合、工作树噪声、实现可能继续变化 | `known_recent` |
| AutoResearchClaw | `C:\Users\ZYF\Desktop\Paper\AutoResearchClaw` | Pipeline contract、Verify、checkpoint、Memory、HITL、Eval、LLM fallback | 23-stage domain 耦合、同步 I/O、本地 dirty 文件 | `verified_now` |
| Draftpaper-loop / DeepLoop | `C:\Users\ZYF\Desktop\Paper\Draftpaper_loop_temp` | Evidence-first staged loop、Claim trace、Citation repair、Novelty overlap、质量 Gate | Source-available / commercial restrictions、商标和领域耦合 | `verified_now` |
| academic-research-skills | `C:\Users\ZYF\Desktop\Paper\academic-research-skills` | Skill 组织、Prompt contract、Ground Truth isolation、review / eval / hook | Skill 版本多、重复安装、不能全部注入 Context | `located_only` |
| Academic Method Tailoring | `C:\Users\ZYF\.codex\skills\academic-method-tailoring` | Baseline freeze、Module Card、Compatibility、Ablation、GO/NO-GO | 属于 domain skill，不应进入通用 Runtime | `verified_now` |
| Paper Novelty Design V1 | `C:\Users\ZYF\.agents\skills\paper-novelty-design-v1` | Problem–Method–Insight、伪创新诊断、可证伪性、Reviewer pressure test | 当前安装引用的两个 reference 文件未找到 | `verified_now` + partial |
| Paper project skills | `C:\Users\ZYF\Desktop\Paper\.agents\skills` | deep-research、academic-paper-reviewer、academic-pipeline 等角色与流程 | 数量多、重复版本，调用前必须读对应 SKILL.md | `located_only` |

---

## 3. PaperAgent

### 3.1 定位

PaperAgent 是 PaperClaw 最直接的 LangGraph / Research domain 参考。PaperClaw 不应复制其整个 Graph，而应选择性吸收检索、Evidence、工作台、Trace 和 SeededResearch 经验。

### 3.2 最近已知更新方向

以下来自 2026-06-30 前后的最近工作记录，本轮按用户要求未继续做完整仓库扫描，执行前必须查看当前 `git log --oneline -20` 和 `git status --short`：

- Research Agent 检索与 ToolPlan 加固；
- 保留原始 `raw_topic`，避免 repair 后主题漂移；
- 将 `search_dataset_web`、`search_paperswithcode` 补为确定性 fallback；
- Skill seed 通过 `skill_role` 在后续筛选中保留；
- Query 从“模型自由生成字符串”转向“模型选路线 + skill atoms 确定性编译”；
- Session42 Workbench 的聊天、Trace、状态展示与布局整理；
- Re8.0 SeededResearch / 学术裁缝策划。

### 3.3 Retrieval / QueryEngine 必读

| 路径 | 阅读目的 |
|---|---|
| `G:\PaperAgent\apps\api\app\services\research_planner_agent.py` | ToolPlan、query planning、raw_topic 保留 |
| `G:\PaperAgent\apps\api\app\services\research_skill_bridge.py` | Skill repair、seed backfill、dataset/repo enrich |
| `G:\PaperAgent\apps\api\app\services\retrieval\tool_orchestrator.py` | ToolPlan → adapter → normalize 的执行边界 |
| `G:\PaperAgent\skills\registry.json` | Research Skills 的本地索引 |
| `G:\PaperAgent\skills\research\paper-card\SKILL.md` | 论文 Evidence 的确定性预处理与禁止项 |
| `G:\PaperAgent\apps\api\app\services\agents\graph\nodes\evidence_context.py` | Evidence Context 的已有形态 |

可借鉴：

- LLM 负责 route choice，QueryCompiler 负责确定性 query；
- 原始用户主题不可覆盖；
- adapter 缺失时的 fallback；
- seeded candidate 的 provenance 和筛选保护；
- Query / Candidate / Role / Evidence 的分层 Trace。

不要直接搬：

- 与 PaperAgent Phase、LangGraph State 强绑定的节点；
- 依赖当前 Provider helper 签名的临时修复；
- 把 PaperClaw RetrievalEngine 写死为 PaperAgent API。

### 3.4 SeededResearch 必读

| 路径 | 阅读目的 |
|---|---|
| `G:\PaperAgent\Plan\PaperAgent_Re8.0_SeededResearch学术裁缝MVP策划案.md` | Seed Intake、Seed Audit、方法族、Evidence Gap、三运行模式 |
| `G:\PaperAgent\docs\interview\AutoResearchClaw_*.md` | 既有科研 Agent 对照和面试叙事 |
| `G:\PaperAgent\Plan\reports\PaperAgent_S66*` | Research Skill 与 Retrieval 调试证据 |

### 3.5 Workbench / Claw 交互层

执行 v0.06 前，应在当前 checkout 中搜索并阅读：

```text
step_workbench.js
report-workbench-section
RagContextSection
Trace / timeline / session status 相关组件
```

参考目标是交互状态、Trace 分组和 stale propagation，不复制旧 DOM 或样式结构。

---

## 4. AutoResearchClaw

### 4.1 仓库快照

- 路径：`C:\Users\ZYF\Desktop\Paper\AutoResearchClaw`
- origin：`https://github.com/aiming-lab/AutoResearchClaw.git`
- 当前可见 HEAD：`ea77ec19fefe9198ac1364d2cdb4f9e928cf0705`
- 当前 clone 为 shallow，不能据此声称掌握完整近期历史；
- LICENSE：MIT，迁移 substantial portions 时保留版权和许可；
- 工作树存在本地修改：`researchclaw/llm/acp_client.py`；
- `_cifar_dl.log`、`_run_final*.log`、`_tmp/` 是本地未跟踪内容，不属于上游基线。

### 4.2 Pipeline Contract / Verify / Resume

| 路径 | 可借鉴内容 | PaperClaw 阶段 |
|---|---|---|
| `researchclaw\pipeline\contracts.py` | StageContract、input/output、gate、retry、Definition of Done | v0.02 / v0.05 |
| `researchclaw\pipeline\stages.py` | StageStatus、TransitionEvent、rollback、pivot 上限 | v0.02 |
| `researchclaw\pipeline\runner.py` | atomic checkpoint、heartbeat、resume、cancel | v0.05 |
| `researchclaw\pipeline\executor.py` | pre/post HITL、retry、quality gate 生命周期切点 | v0.05 |
| `researchclaw\pipeline\verified_registry.py` | 实验事实、source、tolerance、condition | v0.02 / SeededResearch |
| `researchclaw\pipeline\experiment_diagnosis.py` | 失败诊断分类 | v0.02 |
| `researchclaw\pipeline\experiment_repair.py` | 定向修复—重跑闭环 | v0.02 |
| `researchclaw\experiment\sandbox.py` | entry、timeout、NaN/Inf、metrics、独立 run dir | v0.02 / v0.05 |
| `researchclaw\experiment\runner.py` | ExperimentHistory、best result、bounded loop | v0.02 |

重点借鉴：Verify 先登记客观事实，Reflection 只能消费事实，不能改写事实。

### 4.3 MultiAgent / HITL

| 路径 | 可借鉴内容 |
|---|---|
| `researchclaw\agents\benchmark_agent\orchestrator.py` | 角色编排 |
| `researchclaw\agents\benchmark_agent\selector.py` | 候选选择边界 |
| `researchclaw\agents\benchmark_agent\surveyor.py` | 信息收集角色 |
| `researchclaw\agents\benchmark_agent\acquirer.py` | 资源获取角色 |
| `researchclaw\agents\benchmark_agent\validator.py` | 独立 validator gate |
| `researchclaw\collaboration\publisher.py` | Result 发布 |
| `researchclaw\collaboration\subscriber.py` | 订阅与消费 |
| `researchclaw\collaboration\repository.py` | 协作状态存储 |
| `researchclaw\collaboration\dedup.py` | 幂等和去重 |
| `researchclaw\hitl\collaboration.py` | Human 作为特殊协作者 |
| `researchclaw\hitl\adapters\cli_adapter.py` | approve / reject / inject / view output |
| `researchclaw\hitl\adapters\mcp_adapter.py` | HITL adapter 边界 |

只借鉴角色输入输出、发布订阅和 validator gate；不要复制科研 stage 常量。

### 4.4 Context / Memory / Skills

| 路径 | 可借鉴内容 | 已知局限 |
|---|---|---|
| `researchclaw\hitl\context_manager.py` | system/history/stage/guidance 分区、滑动窗口、artifact summary | 字符预算、硬截断、缺 provenance / exclusion trace |
| `researchclaw\hitl\chat.py` | ChatSession 序列化、load、turn limit | 绑定 stage context |
| `researchclaw\memory\store.py` | MemoryEntry、confidence、access、prune | 文件式存储 |
| `researchclaw\memory\retriever.py` | recall 和 category retrieval | 与 PaperClaw ContextItem 不同 |
| `researchclaw\memory\decay.py` | Memory 失效 / 衰减 | 需重做评估 |
| `researchclaw\skills\schema.py` | Skill contract | 缺 trust / license / permission |
| `researchclaw\skills\loader.py` | builtin/custom/external source | 需防 prompt injection |
| `researchclaw\skills\registry.py` | Skill Registry | 匹配较浅 |
| `researchclaw\skills\matcher.py` | stage / keyword / description 匹配 | 直接 Prompt 注入风险 |
| `researchclaw\metaclaw_bridge\skill_feedback.py` | Trace/Eval → lesson 候选 | 必须人工审核 |
| `researchclaw\metaclaw_bridge\lesson_to_skill.py` | lesson → SKILL 草稿 | 不可自动升级为可信规则 |

推荐“复用数据字段和失败经验，写 SQLite / ContextItem adapter”，不要复制字符预算实现。

### 4.5 Model / Harness

| 路径 | 可借鉴内容 |
|---|---|
| `researchclaw\llm\client.py` | LLMResponse、Provider preset、fallback chain、backoff+jitter、JSON mode |
| `researchclaw\llm\anthropic_adapter.py` | Provider wire API 隔离 |
| `researchclaw\wizard\validator.py` | 配置 preflight |
| `researchclaw\wizard\quickstart.py` | 快速启动验证 |
| `researchclaw\mcp\registry.py` | MCP registry 边界 |
| `researchclaw\mcp\tools.py` | MCP tool contract |

已知问题：主 LLM client 偏同步 HTTP。PaperClaw 必须保持 async、cancel、usage 和 Trace 契约，不应直接复用同步执行层。

### 4.6 Literature Retrieval / Citation

| 路径 | 可借鉴内容 |
|---|---|
| `researchclaw\literature\search.py` | OpenAlex / S2 / arXiv、多 query union、dedup、cache fallback |
| `researchclaw\literature\models.py` | Paper schema |
| `researchclaw\literature\openalex_client.py` | backend adapter |
| `researchclaw\literature\semantic_scholar.py` | backend adapter |
| `researchclaw\literature\arxiv_client.py` | backend adapter |
| `researchclaw\literature\verify.py` | 多源 citation verification 与状态分类 |
| `researchclaw\literature\novelty.py` | 相似论文 signal、低样本不虚报满分 |

重要限制：当前 source/query 循环存在串行 I/O 和 sleep；PaperClaw 必须重写成异步并发、per-source semaphore 和 backoff。

AutoResearchClaw 没有完整通用 RAG pipeline 或统一 RAG Eval，不能在项目叙事中声称已经复用成完整 RAG。

### 4.7 Trace / Eval / UI

| 路径 | 可借鉴内容 |
|---|---|
| `researchclaw\experiments\arc_bench` | topic manifest、rubric、judge、scoreboard |
| `researchclaw\assessor\rubrics.py` | Rubric schema |
| `researchclaw\assessor\scorer.py` | scoring |
| `researchclaw\assessor\comparator.py` | mode / result comparison |
| `researchclaw\dashboard\collector.py` | run snapshot / metrics |
| `researchclaw\dashboard\broadcaster.py` | 状态广播 |
| `researchclaw\server\websocket\events.py` | UI event contract |
| `researchclaw\hitl\adapters\cli_adapter.py` | pause / progress / action UX |

ARC-Bench 是科研最终产物评估，不等价于 Tool、Context 或 RAG retrieval eval。当前也未找到 LangSmith 集成或统一 TraceStore/span，PaperClaw 仍应自建内部 Trace，再接 LangSmith adapter。

---

## 5. Draftpaper-loop（用户所称 DeepLoop）

### 5.1 身份确认

本索引将用户所称 **DeepLoop** 对应到：

```text
C:\Users\ZYF\Desktop\Paper\Draftpaper_loop_temp
```

未发现另一个独立名为 `DeepLoop` 的仓库，因此后续 SOP 使用统一名称：`Draftpaper-loop（DeepLoop）`。

### 5.2 许可与品牌边界

执行前必须阅读：

```text
COMPLIANCE.md
COMMERCIAL_LICENSE.md
TRADEMARK.md
```

该项目不是默认可按普通开源依赖随意复制的假设对象。PaperClaw 优先借鉴契约、Gate、Artifact 和测试思想；复制代码前必须核对用途和授权。

### 5.3 核心入口

| 路径 | 可借鉴内容 |
|---|---|
| `codex_skills\draftpaper-workflow\SKILL.md` | 薄 Agent wrapper、核心逻辑留在 Python package |
| `codex_skills\draftpaper-workflow\references\commands.md` | staged workflow、repair 和 stop 条件 |
| `docs\DPL_SCHEMA.md` | project passport、stage、claim trace、loop event、schema identity |
| `draftpaper_cli\loop_contract.py` | stable claim / evidence ID、loop event vocabulary |
| `draftpaper_cli\core_evidence.py` | 核心证据 Gate、数据/方法 repair 路由 |
| `draftpaper_cli\integrity_gate.py` | 完整性与生成内容清理 |
| `draftpaper_cli\citation_audit.py` | Citation audit |
| `draftpaper_cli\citation_repair.py` | audit—repair—re-audit loop |
| `draftpaper_cli\research_plan.py` | research plan 与 novelty overlap gate |
| `draftpaper_cli\review_revision.py` | Review / Revision loop |
| `Draftpaper_loop_code_audit_report.md` | 已有代码审计、未接入模块和迁移风险 |

### 5.4 对 PaperClaw 的价值

#### v0.02 Verify / Reflection

- 先定义 Evidence Contract，再允许写作或完成；
- 不把“脚本 exit code 0”视为方法验证的全部；
- Figure、metadata、result validity、claim trace 共同构成完成 Gate；
- 失败进入 data repair、method repair 或 research-plan revision，而不是无限重试。

#### v0.04 Context / Evidence

- Project Passport；
- Claim ID / Evidence ID；
- stage-owned artifact；
- manuscript projection 不直接暴露内部本地路径；
- curated Zotero seed 保留 provenance，不被外部搜索排名删除。

#### SeededResearch

- novelty overlap 不是简单相似度分数，而是进入 `blocked_high_similarity` Gate；
- 先补数据 / 方法 Evidence，再缩小研究 Claim；
- Citation repair 保留 iteration 和 final report；
- 科研叙事必须由 Claim—Evidence 绑定支持。

### 5.5 不要直接搬

- 整套论文生成 CLI；
- Draftpaper-loop 名称、标识和宣传语；
- 与其项目目录、LaTeX、Figure contract 强绑定的全部流程；
- 未运行时引用的候选规范文件；
- 未核对许可的实现代码。

---

## 6. academic-research-skills

### 6.1 路径与入口

```text
C:\Users\ZYF\Desktop\Paper\academic-research-skills
```

已定位的主要入口：

```text
README.md / README.zh-CN.md
MODE_REGISTRY.md
academic-paper/
academic-paper-reviewer/
academic-pipeline/
deep-research/
shared/
evals/
hooks/
tests/
```

### 6.2 推荐阅读目的

| 目录 / 文件 | 阅读目的 |
|---|---|
| `MODE_REGISTRY.md` | 不同运行模式的明确边界 |
| `shared\ground_truth_isolation_pattern.md` | 将外部输入标记为 data，不当作 instruction |
| `shared\contracts\*.schema.json` | 跨阶段 Schema 与 lint |
| `academic-paper-reviewer\` | 多视角 Reviewer 角色和报告格式 |
| `academic-pipeline\references\two_stage_review_protocol.md` | 两阶段 Review |
| `academic-pipeline\references\integrity_review_protocol.md` | 学术完整性 Gate |
| `academic-pipeline\references\ai_research_failure_modes.md` | AI 科研失败类型 |
| `deep-research\` | Research brief、问题定义、系统综述 |
| `evals\` | Skill / Prompt 回归思路 |
| `hooks\` | 工作流自动检查 |
| `tests\` | Contract 和 Skill 质量验证 |

### 6.3 复用方式

- 将 Skill 当 domain policy，不让 Skill 直接管理 QueryEngine；
- 通过 Skill Adapter 编译输入输出；
- 使用 Schema Validator 和版本记录；
- 外部论文、摘要和网页属于 data，不得覆盖系统规则；
- Review Skill 只能建议，最终状态必须通过 Runtime Verify / Evidence Gate；
- 不将整个 Skill 仓库无差别注入 Context。

---

## 7. Academic Method Tailoring

### 7.1 路径

```text
C:\Users\ZYF\.codex\skills\academic-method-tailoring
```

关键文件：

| 路径 | 用途 |
|---|---|
| `SKILL.md` | Baseline → Gap → Module → Compatibility → Experiment 主流程 |
| `references\workflow.md` | 完整阶段与 Gate |
| `references\output-contracts.md` | Baseline Card、Module Card、实验矩阵等产物格式 |
| `references\source-map.md` | 来源与设计理由 |
| `scripts\validate_method_plan.py` | Method Plan 结构审计 |

### 7.2 PaperClaw 使用边界

SeededResearch Tailor 阶段应优先参考：

- freeze reproducible baseline；
- 将 gap 写成可证伪假设；
- Module provenance 与 License；
- 检查语义、scale、ordering、mask、gradient、loss、compute；
- 保留 baseline path；
- 单模块、组合、leave-one-out、interaction ablation；
- GO / REVISE / NO-GO。

它属于科研 domain，不进入通用 Coding Agent 的 System Prompt。

---

## 8. Novelty / 创新点审查

### 8.1 Paper Novelty Design V1

路径：

```text
C:\Users\ZYF\.agents\skills\paper-novelty-design-v1\SKILL.md
```

可借鉴：

- `Problem–Method–Insight` 三层创新表述；
- 工程堆叠、领域平移、指标叙事、“first” Claim 的伪创新诊断；
- 将创新点改写为可证伪 Proposition；
- repetition / motivation / falsifiability / differentiation / story pressure test；
- 1 句、3 句、短段落三种叙事；
- Novelty Evolution Log。

当前限制：该 `SKILL.md` 指向的以下文件在当前安装目录中未找到：

```text
references/review-checks-v1.md
references/writing-templates-v1.md
```

后续调用时只能使用现存 `SKILL.md`，或先补齐 Skill 包；不得伪造缺失 reference 内容。

### 8.2 Draftpaper-loop Novelty Gate

建议结合阅读：

```text
Draftpaper_loop_temp\draftpaper_cli\research_plan.py
Draftpaper_loop_temp\tests\test_research_plan.py
Draftpaper_loop_temp\codex_skills\draftpaper-workflow\references\commands.md
```

借鉴点：高相似性进入 blocked / user decision，而不是模型自动把措辞改得“更创新”。

### 8.3 academic-paper-reviewer

已定位目录：

```text
C:\Users\ZYF\Desktop\Paper\academic-research-skills\academic-paper-reviewer
C:\Users\ZYF\Desktop\Paper\.agents\skills\academic-paper-reviewer
```

后续选择一个确定版本后阅读其 `SKILL.md`、Reviewer agents、criteria 和 report template；不要混用两个目录的不同版本。

---

## 9. 按 PaperClaw 版本阅读

### v0.02 Verify / Reflection

执行前至少阅读：

```text
AutoResearchClaw\researchclaw\pipeline\contracts.py
AutoResearchClaw\researchclaw\pipeline\stages.py
AutoResearchClaw\researchclaw\pipeline\verified_registry.py
AutoResearchClaw\researchclaw\experiment\sandbox.py
AutoResearchClaw\researchclaw\pipeline\experiment_diagnosis.py
AutoResearchClaw\researchclaw\pipeline\experiment_repair.py
Draftpaper_loop_temp\draftpaper_cli\core_evidence.py
Draftpaper_loop_temp\draftpaper_cli\review_revision.py
```

提取：Evidence、Gate、failure taxonomy、retry/pivot、bounded repair。  
禁止：复制 23-stage 常量或论文 domain 完成条件到通用 Coding Agent。

### v0.03 MultiAgent

执行前至少阅读：

```text
AutoResearchClaw\researchclaw\agents\benchmark_agent\orchestrator.py
AutoResearchClaw\researchclaw\agents\benchmark_agent\validator.py
AutoResearchClaw\researchclaw\collaboration\publisher.py
AutoResearchClaw\researchclaw\collaboration\subscriber.py
AutoResearchClaw\researchclaw\collaboration\dedup.py
AutoResearchClaw\researchclaw\hitl\collaboration.py
academic-research-skills\academic-paper-reviewer\
```

提取：角色 I/O、发布订阅、去重、Validator、Human collaborator。  
禁止：建设无边界 Swarm 或让 Reviewer 同时实现和审查。

### v0.04 Context Engineering

执行前至少阅读：

```text
AutoResearchClaw\researchclaw\hitl\context_manager.py
AutoResearchClaw\researchclaw\hitl\chat.py
AutoResearchClaw\researchclaw\memory\store.py
AutoResearchClaw\researchclaw\memory\retriever.py
AutoResearchClaw\researchclaw\memory\decay.py
Draftpaper_loop_temp\docs\DPL_SCHEMA.md
Draftpaper_loop_temp\draftpaper_cli\loop_contract.py
PaperAgent\apps\api\app\services\agents\graph\nodes\evidence_context.py
```

提取：Context 分区、Session、Memory lifecycle、Claim/Evidence identity。  
禁止：照搬字符硬截断或把所有 Skill 全量注入 Prompt。

### v0.05 Harness Engineering

执行前至少阅读：

```text
AutoResearchClaw\researchclaw\pipeline\runner.py
AutoResearchClaw\researchclaw\llm\client.py
AutoResearchClaw\researchclaw\llm\anthropic_adapter.py
AutoResearchClaw\researchclaw\server\websocket\events.py
AutoResearchClaw\researchclaw\mcp\registry.py
PaperAgent\apps\api\app\services\retrieval\tool_orchestrator.py
```

提取：checkpoint、heartbeat、Provider adapter、Event、MCP / Tool 边界。  
禁止：同步阻塞实现、把 LangSmith 当唯一 TraceStore、把 ACP dirty 文件当上游基线。

### v0.06 Claw 交互层

执行前至少阅读：

```text
AutoResearchClaw\researchclaw\hitl\adapters\cli_adapter.py
AutoResearchClaw\researchclaw\dashboard\broadcaster.py
AutoResearchClaw\researchclaw\server\websocket\events.py
AutoResearchClaw\frontend-legacy\src\components\PipelineView.js
AutoResearchClaw\frontend-legacy\src\components\ExperimentMonitor.js
AutoResearchClaw\frontend-legacy\src\components\ChatPanel.js
G:\PaperAgent 中当前 workbench / Trace / RagContext 组件
```

提取：pause、approve、progress、event-to-UI、task status。  
禁止：复制 legacy UI 或让 TUI 直接操作 Tool / DB。

### v0.07 Trace / Replay / Eval

执行前至少阅读：

```text
AutoResearchClaw\researchclaw\experiments\arc_bench\
AutoResearchClaw\researchclaw\assessor\rubrics.py
AutoResearchClaw\researchclaw\assessor\scorer.py
AutoResearchClaw\researchclaw\assessor\comparator.py
AutoResearchClaw\researchclaw\dashboard\collector.py
academic-research-skills\evals\
Draftpaper_loop_temp\draftpaper_cli\core_evidence.py
Draftpaper_loop_temp\draftpaper_cli\citation_audit.py
```

提取：Dataset、Rubric、Scoreboard、artifact-only judge、Claim/Citation Evidence。  
禁止：把 ARC-Bench 宣称为 Tool/Context/RAG Eval，或把 LLM Judge 当唯一裁判。

### v0.08 Retrieval / RAG / Evidence

执行前至少阅读：

```text
G:\PaperAgent\apps\api\app\services\research_planner_agent.py
G:\PaperAgent\apps\api\app\services\research_skill_bridge.py
G:\PaperAgent\apps\api\app\services\retrieval\tool_orchestrator.py
AutoResearchClaw\researchclaw\literature\search.py
AutoResearchClaw\researchclaw\literature\verify.py
AutoResearchClaw\researchclaw\literature\models.py
```

提取：raw_topic、确定性 QueryCompiler、多源 adapter、canonical identity、citation verify、cache fallback。  
禁止：串行 source loop、结果直接升级 verified、把 literature retrieval 称为完整通用 RAG。

### v0.09 SeededResearch / Academic Tailor / Novelty

执行前至少阅读：

```text
G:\PaperAgent\Plan\PaperAgent_Re8.0_SeededResearch学术裁缝MVP策划案.md
G:\PaperAgent\skills\registry.json
G:\PaperAgent\skills\research\paper-card\SKILL.md
AutoResearchClaw\researchclaw\literature\search.py
AutoResearchClaw\researchclaw\literature\verify.py
AutoResearchClaw\researchclaw\literature\novelty.py
C:\Users\ZYF\.codex\skills\academic-method-tailoring\SKILL.md
C:\Users\ZYF\.agents\skills\paper-novelty-design-v1\SKILL.md
Draftpaper_loop_temp\draftpaper_cli\research_plan.py
```

### v0.10 Reliability / Security / Release

执行前重新阅读：

```text
AutoResearchClaw\LICENSE
Draftpaper_loop_temp\COMPLIANCE.md
Draftpaper_loop_temp\COMMERCIAL_LICENSE.md
Draftpaper_loop_temp\TRADEMARK.md
PaperClaw 根 LICENSE / NOTICE / third-party attribution
PaperClaw pyproject.toml / package version / Shell backend / DB migration
```

提取：许可证边界、依赖来源、可复现配置和已有安全限制。  
禁止：从 dirty worktree 发布、把 native Permission 宣称为 sandbox、未审许可复制 substantial code。

---

## 10. 后续 SOP 强制模板

每份新的实施 SOP 必须包含：

```markdown
## 既有实现参考（执行前必读）

| 参考项目 | 必读路径 | 借鉴目标 | 禁止照搬 |
|---|---|---|---|
| ... | ... | ... | ... |

执行要求：
1. 记录参考项目当前 commit / worktree 状态；
2. 阅读指定实现及对应测试；
3. 在 implementation_summary.md 说明实际借鉴内容；
4. substantial code migration 必须记录 license / attribution；
5. 若路径已变化，先在参考项目中重新定位，不得跳过阅读；
6. 参考实现与 PaperClaw 契约冲突时，以 PaperClaw 独立边界为准并记录差异。
```

禁止在 SOP 中只写“参考 AutoResearchClaw”而不给具体文件和阅读目的。

---

## 11. 禁止直接复用的内容

- `.env`、API Key、Cookie、Token；
- 本地日志、缓存、临时下载和未跟踪输出；
- dirty worktree 中无法确认来源的修改；
- 未核对许可证的 substantial code；
- PaperAgent 的旧 Phase / LangGraph State 作为通用 Runtime State；
- AutoResearchClaw 的 23-stage 常量和同步阻塞循环；
- Draftpaper-loop 的品牌、商标和受限商业实现；
- Skill 中缺失的 reference 文件；
- 外部项目的隐藏 Chain-of-Thought；
- 将启发式 novelty score 当作真实创新结论；
- 将最终研究产物 Eval 冒充 Agent trajectory / RAG / Context Eval。

---

## 12. 未找到与待复核项

| 项目 | 状态 | 处理 |
|---|---|---|
| 独立 `DeepLoop` 仓库 | `not_found` | 用户已确认对应 Draftpaper-loop，本索引统一使用该名称 |
| `paper-novelty-design-v1/references/review-checks-v1.md` | `not_found` | 不引用其假定内容 |
| `paper-novelty-design-v1/references/writing-templates-v1.md` | `not_found` | 不引用其假定内容 |
| AutoResearchClaw LangSmith 集成 | `not_found` | PaperClaw 自建 TraceStore，LangSmith 仅 adapter |
| AutoResearchClaw 通用完整 RAG Eval | `not_found` | 只借鉴 literature retrieval / citation verify / ARC-Bench |
| PaperAgent 当前最新 commit 与完整 dirty 状态 | `needs_refresh` | 每次实际迁移前运行 `git log --oneline -20` 和 `git status --short` |
| academic-research-skills 选用版本 | `needs_selection` | 避免 `.agents/.claude/仓库根` 多份副本混用 |

本索引后续按真实实现和 commit 更新；不得把路径存在等同于模块已经适配 PaperClaw。
