# PaperClaw 项目方向、演进路径与边界约束

> 文档性质：项目提要与方向约束，不是详细架构设计或实现方案。

## 当前实现状态（v0.01）

截至 2026-07-13，仓库已实现 PocketFlow action routing 驱动的最小 Coding Agent Loop、五个工作区工具、结构化 history、模型输出校验、最大步数和基础安全边界。完整 Permission Engine、持久化 Trace、Session / Memory、Context Compaction、Eval、RAG 与 SeededResearch 仍处于设计或计划状态。

## 1. 项目目标

PaperClaw 是一个面向校招学习、技术验证和真实科研场景的轻量 Agent Runtime 项目。

项目不以“再实现一个 LangGraph 工作流”为目标，也不以完整复刻 Claude Code 或 AutoResearchClaw 为目标。它希望通过一个可以运行、观察、恢复和评估的小型 Claw，学习并验证以下能力：

- Agent Loop 与轻量控制流；
- Prompt / Context Engineering；
- Session、Memory 与任务恢复；
- Tool Registry、工具路由和调用治理；
- Permission 与副作用控制；
- QueryEngine、RAG 与证据检索；
- Trace、Replay 与 Agent Eval；
- SQLite 等轻量持久化；
- Coding / Research domain 的可插拔扩展。

## 2. 最终 Domain 方向

PaperClaw 的首个深度验证场景是 **SeededResearch 学术裁缝**。

用户不必只从一个题目开始，也可以携带从导师、自己阅读或其他模型获得的少量种子论文，以及一个研究方向进入系统。PaperClaw 最终应能围绕这些材料完成：

1. 核验论文是否真实并判断其角色；
2. 理解研究任务、方法、数据、指标和复现条件；
3. 补齐同任务竞争路线、替代方法族、机制模块、Repo、Dataset 和反证；
4. 冻结可复现 baseline；
5. 将研究缺口转化为可证伪假设；
6. 检查模块来源、语义、接口、训练目标、许可和计算成本；
7. 生成增量方法、实验和消融计划；
8. 经独立 Review 后输出可追溯的研究方案。

SeededResearch 是通用 Runtime 的验证 domain，不应反过来把 Runtime 写死为论文流水线。

## 3. 双入口约束

项目长期保留两种研究入口：

- `topic_only`：用户只有题目或方向，系统从零探索；
- `seeded_research`：用户提供方向和少量种子论文，作为推荐主流程。

两种入口可以有不同的前置流程，但最终应汇入统一的 Evidence、Tailor、Review、Eval 和产物契约。

## 4. Runtime 与 Domain 的边界

### Runtime 负责

- Agent Loop、运行模式和终止条件；
- Context 装配、压缩和预算；
- Session、Checkpoint、Memory 和 Replay；
- 工具注册、权限判断、执行与结果压缩；
- Trace、成本、错误和评估记录；
- 模型、检索和数据库 adapter。

### SeededResearch Domain 负责

- 研究意图和种子论文语义；
- 论文真实性、角色与证据状态；
- 方法族、Evidence Gap 和科研决策；
- Baseline、Module、Compatibility 与 Experiment；
- Novelty、Tailor、Review 和研究叙事。

Domain 可以调用 Runtime 能力，但不能绕过权限、证据状态、预算、Trace 或 Validator。

## 5. 技术路线约束

- 轻量动态 Agent Loop 优先参考 PocketFlow 的极简 Node / Flow / Shared Store / action routing 思路。
- LangGraph 仅用于确实需要复杂持久状态的科研 Workflow，作为 adapter 保留，不成为所有能力的强依赖。
- Context、Permission、Tool、Session、Trace 和 Eval 必须独立于具体图框架。
- Claude Code 只作为分层 Prompt、项目指令、权限和工具治理的公开设计参考，不宣称复刻其未公开内部实现。
- pi 主要作为轻量 Runtime、Session 与 Context Compaction 参考。
- τ-bench 主要作为任务最终状态与 `pass^k` 评估思路参考，不强制复现唯一 gold trajectory。
- AutoResearchClaw 和 PaperAgent 可以复用或借鉴 domain 工作流，但关键边界、状态和验证必须在 PaperClaw 中可解释。
- MVP 默认使用 SQLite；向量数据库、分布式队列和复杂 Knowledge Graph 只有在评估证明确有需要时再引入。

## 6. 上下文方向约束

- Prompt 不维护为单个超长字符串，而采用分层、模块化、运行时装配。
- 对话历史不能替代结构化 Task State。
- 压缩必须保留目标、约束、决策、失败尝试、待办和来源引用。
- 长期记忆按需检索，不默认全部注入上下文。
- 外部论文、网页、工具结果属于数据和证据，不得被当成高优先级指令。
- 每轮上下文应可解释：能回答“为什么这条信息进入了模型窗口”。
- 上下文系统详细讨论见 `PaperClaw_上下文系统与提示词工程骨架.md`。

## 7. 工具与权限约束

- Prompt 负责引导行为，Permission Engine 负责强制边界。
- Tool Registry、Permission Engine 与 Tool Executor 必须分层。
- 每个工具应声明能力、适用条件、权限类别、副作用、成本、超时、重试和结果保留策略。
- 外部写入、破坏性操作、敏感路径和高成本动作不得仅靠模型自律。
- 工具调用和结果必须进入 Trace；不得伪造未执行的调用或结果。
- Full Agent 可以自主选择工具，但必须有白名单、预算和硬终止条件。

## 8. 检索、RAG 与证据约束

- QueryEngine 不只接收“搜索关键词”，还应逐步支持由任务目标和 Evidence Gap 驱动的查询。
- 用户提供的论文、DOI、链接或模型生成列表一律先视为 `candidate`，核验前不能成为已验证证据。
- 每次增强搜索应说明它要补哪个缺口、成功条件是什么、结果改变了哪个判断。
- 检索必须覆盖主路线、同任务竞争路线、可迁移机制、资源和反证，避免只围绕种子自我强化。
- RAG Eval 与 Agent Eval 分开：前者评估检索结果，后者评估上下文使用、工具行为和最终任务状态。
- 重要 Claim 必须能回溯到论文、代码、数据、实验或明确标记的用户输入。

## 9. 学术裁缝约束

- 模块组合只是待验证假设，本身不等于创新。
- 每个借用的思想、公式、实现、数据集和文本模式都必须保留来源。
- 不能仅凭 tensor shape 判断模块兼容，还要检查语义、尺度、顺序、mask、gradient、训练目标、License 和计算成本。
- 先选择并验证 baseline，再做增量修改；原 baseline 路径必须可恢复。
- 每个拟议模块必须对应明确失败机制、预期效果、失败条件和消融实验。
- 科研故事不得超过证据。未运行实验只能写作 proposed / expected / unresolved，不能写成 verified。
- 必须保留负结果、已知限制和 NO-GO / PIVOT 路线。
- 项目可以帮助用户设计低门槛增量研究，但不能捏造论文、引用、实验数据或隐藏更强比较方法。

## 10. 三种运行模式

项目最终应支持同一顶层契约下的三种模式：

- **Full Agent**：允许联网、有界 ReAct 和关键 Gate Reflection，用于真实研究任务；
- **Lite Chain**：固定流程，关闭 ReAct / Reflection，用于低成本演示和模型兼容测试；
- **Offline Replay**：完全禁止联网，使用固定 fixture，用于 CI、调试和回归。

Lite 和 Offline 可以降低自主性，但不能关闭真实性校验、Schema Validator、权限和 Trace。

## 11. 演进路径

### 阶段 A：可讲的一周 MVP

优先证明通用 Runtime，而不是完成整个 SeededResearch：

- 最小 Agent Loop；
- 分层 ContextBuilder；
- 结构化 Task State；
- 少量只读工具和权限判定；
- SQLite Session / Tool Call / Checkpoint；
- Trace 与 Offline Replay；
- 一个压缩前后约束保持测试；
- 一个简化 Research 或 Coding fixture。

### 阶段 B：一个月可运行版本

- Context Compaction 与 Session Resume；
- Tool Registry、Permission 和错误恢复；
- QueryEngine 与混合检索；
- RAG / Context / Tool / Final State Eval；
- Full、Lite、Offline 三模式；
- SeededResearch 的最小垂直切片：Seed Intake → 核验 → 定向补搜 → Tailor → Review。

### 阶段 C：SeededResearch 深化

- 多种输入形式与 PDF / Repo 环境提取；
- 方法族展开与 Evidence Gap 搜索；
- Baseline Freeze、Module Card 和 Compatibility；
- 有界 ReAct / Reflection；
- 跨领域 fixture 与真实案例；
- 前端可视化、人工 Gate 和研究包导出。

## 12. 评估优先级

项目不以“看起来聪明”作为验收标准。至少逐步建立：

- Context：约束保持率、事实落地率、压缩漂移、token 效率；
- Tool：工具选择准确率、参数正确率、越权率、错误恢复率；
- RAG：Recall、Precision、来源覆盖、证据新鲜度和反证覆盖；
- Agent：任务完成率、最终状态、`pass^k`、成本和时延；
- Research：假论文泄漏率、种子角色准确率、Evidence Gap 满足率、Baseline 可复现性、Claim-Evidence 对齐和 Review 后改进率。

评估数据应优先来自可复现 fixture，再逐步增加真实任务 Trace。测试不能依赖一次模型输出“感觉正确”。

## 13. 当前非目标

在 MVP 阶段暂不追求：

- 完整复刻 Claude Code；
- 通用自主软件工程 Agent；
- 大规模多 Agent Swarm；
- 复杂向量数据库和分布式基础设施；
- 自动生成并宣称真实的实验结果；
- 一次覆盖所有学科的学术方法本体；
- 为追求 Demo 而隐藏失败、fallback 或未验证状态。

## 14. 项目叙事

PaperClaw 的校招叙事应保持克制且可验证：

> 我以 PocketFlow 风格的极简控制流为起点，实现了一个轻量 Agent Runtime，并补充 Context、Session、工具权限、Trace、恢复和评估能力。随后以 SeededResearch 学术裁缝作为复杂 domain，验证 Agent 如何核验用户提供的论文、围绕证据缺口调度检索、管理长上下文，并生成可追溯、可证伪的增量研究方案。

所有面试表述都应能够由代码、Trace、测试或演示支持。
