# PaperClaw v0.08–v0.10：校招开发向路线修订草案

> 状态：增量修订草案，不直接替换或删除既有 v0.08、v0.09、v0.10 草案  
> 基线：`main@1a50a311b91af74375d6a3036e9ccb750e9f1b02`  
> 日期：2026-07-16  
> 目标：在保留 PaperClaw 既有 Research / Evidence 方向的前提下，优先补齐 AI Agent 开发岗校招高频考察的 Context Engineering、动态 Prompt 装配、MCP、RAG 工程闭环、模型调配与可靠发布能力。

## 1. 本修订稿与旧草案的关系

本文件采用“叠加修订”而不是“覆盖重写”。以下旧文档继续保留，作为详细设计库和后续候选来源：

- `PaperClaw_v0.08_RetrievalRAG与EvidenceEngine_SOP草案.md`；
- `PaperClaw_v0.09_SeededResearch学术裁缝垂直切片_SOP草案.md`；
- `PaperClaw_v0.10_ReliabilitySecurityPackagingRelease_SOP草案.md`。

执行优先级和版本主线按本修订稿重新排序；旧草案中的契约、风险、Eval、Evidence 状态机、Release Checklist 不因排序调整而失效。

本修订稿只调整路线与边界，不声明任何新增能力已经实现。

## 2. 对现有 v0.08–v0.10 的覆盖审计

| 面试 / 工程能力 | 现有覆盖 | 判断 | 修订动作 |
|---|---|---|---|
| Context 分层、结构化压缩、Checkpoint | v0.04 已实现主体 | 已有基础 | 不重复造一套压缩器，补运行期选择、装配、冲突与预算策略 |
| 动态 Prompt Assembly | Context 设计稿有骨架，后续版本未冻结 | 部分覆盖 | 提升为 v0.08 主故事 |
| 长期 Memory 写入、召回、去重、失效 | L5 Retrieved Memory 仍为 no-op | 明显缺口 | v0.08 做轻量 Memory Retrieval MVP |
| QueryEngine 与 Prompt 边界 | 设计稿明确 QueryEngine 不直接拼 Prompt | 边界正确 | 保持薄 façade，由独立 ContextOrchestrator 负责模型输入 |
| Hybrid RAG、Chunk、Rerank、Citation、Eval | 原 v0.08 覆盖很强 | 强覆盖 | 保留设计，后移为 v0.09.1，先完成 Context 消费合同 |
| MCP Client / Server / Tool Discovery | v0.08–v0.10 未形成版本切片 | 核心缺口 | 新增 v0.09 MCP Tool Gateway MVP |
| Skill / Tool 渐进式披露 | 工具治理有概念，无动态能力选择闭环 | 部分覆盖 | v0.08 先做 Context/Capability Selection；v0.09 接 MCP discovery |
| Model routing / fallback / cost policy | Provider retry 已有，v0.10 有性能与发布 | 部分覆盖 | v0.10 增加最小 ModelPolicyRouter 与可观察 fallback |
| SeededResearch 学术垂直切片 | 原 v0.09 设计完整 | 有价值但主线偏科研 | 保留为 v0.09.2 可选 domain showcase，不阻塞通用开发能力 |
| LoRA / SFT / DPO / GRPO | 不在当前 Runtime 路线 | 对开发岗非必做 | 只准备原理与选型讨论，不在 PaperClaw 内实现训练流水线 |
| GraphRAG | 原 v0.08 明确延期 | 决策合理 | 继续延期，除非 Hybrid RAG Eval 证明多跳关系检索是实际瓶颈 |

## 3. 修订后的版本主线

```text
v0.07.x Trace / Eval / MultiAgent View
        ↓
v0.08 Context Orchestration / Dynamic Prompt Assembly
        ↓
v0.09 MCP Tool Gateway
        ↓
v0.09.1 Hybrid RAG / Evidence Engine
        ↓
v0.09.2 SeededResearch Domain Showcase（可选，不阻塞发布）
        ↓
v0.10 Model Policy / Reliability / Security / Packaging / Release
```

依赖原则：

1. RAG 先成为标准 `ContextSource`，再进入模型输入，不能由 RetrievalEngine 直接拼 Prompt；
2. MCP Tool 必须经过 PaperClaw ToolRegistry、validation、Permission 和 Trace，不能绕过现有执行路径；
3. QueryEngine 只管理 Run、预算、停止、事件和结果，不承担 Context、MCP、RAG 或 domain 规则；
4. SeededResearch 只消费通用能力，不反向污染 Runtime 核心；
5. v0.10 只收口已证明必要的能力，不为了“生产级平台”无限扩张。

---

# v0.08：Context Orchestration 与 Dynamic Prompt Assembly MVP

## 4. 用户故事

用户提交一个跨多轮 Coding / Research 任务后，PaperClaw 能够在每次模型调用前，从系统规则、角色、Workspace、Task State、最近消息、Tool Result、长期 Memory 和 Retrieval Candidate 中，选择当前真正需要的信息，并在固定 token 预算内生成可追踪的模型输入。

当规则、历史记忆、外部文档或用户要求冲突时，系统按显式优先级、trust、scope 和 freshness 处理，而不是依赖模型自行猜测。

## 5. 定位与边界

```text
QueryEngine
    负责 Run lifecycle / limits / stop / events / terminal result
        ↓
AgentRuntimeExecutor / Agent Loop
        ↓
ContextOrchestrator
    负责 collect / resolve / select / compress / allocate / render
        ↓
PromptAssembler
    只把已选 ContextItem 渲染成 Provider 输入
        ↓
ChatModel
```

必须保持：

- QueryEngine 不直接拼接 Prompt；
- ContextOrchestrator 不调用 Tool，不写任意业务数据库 SQL；
- PromptAssembler 不决定权限，不提升 Evidence / Memory 的 trust；
- 外部 README、网页、PDF、MCP Resource、RAG Chunk 一律是 untrusted data；
- Prompt 优先级不能替代执行层 Permission。

## 6. 最小契约

```text
ContextRequest
ContextPolicy
ContextSource
ContextCandidate
ContextSelection
ContextConflict
ContextBudgetAllocation
PromptSection
PromptAssembly
ContextAssemblyTrace
MemoryRecord
MemoryWriteDecision
MemoryRetrievalResult
```

关键字段至少包括：

```text
run_id / step_id
source / source_ref
layer / kind / scope
priority / trust / freshness
valid_from / valid_to / superseded_by
estimated_tokens / selected_tokens
selection_reason / exclusion_reason
conflict_group / conflict_resolution
compressible / pinned / sensitive
content_hash / policy_version / prompt_version
```

## 7. 必做能力

### 7.1 Context Source Adapter

首切片只接入现有可验证来源：

- Runtime Constitution；
- Role / Mode；
- Workspace Rules；
- structured Task State；
- recent conversation；
- recent Tool Results；
- v0.04 Context / Checkpoint；
- lightweight MemoryStore；
- Retrieval ContextSource Protocol 预留。

每个 Source 只提交 `ContextCandidate`，不能自行修改最终 Prompt。

### 7.2 Conflict Resolution

至少覆盖：

- system policy > project rule > user request > external data；
- 当前 scope > 远程 scope；
- 新版本 supersede 旧版本；
- verified fact 不被 hypothesis 覆盖；
- explicit user correction 可使旧 preference 失效；
- 外部文本中的 instruction 不进入 L0/L1；
- unresolved conflict 显式进入 Trace，必要时要求澄清或 blocked。

### 7.3 Token Budget Allocation

预算不是简单保留最近 N 条消息。至少区分：

```text
protected_budget
recent_message_budget
active_task_budget
tool_result_budget
memory_budget
retrieval_budget
output_reserve
```

硬约束：

- goal、confirmed constraints、current decision、pending work、failed verification 和 Evidence ref 是 protected；
- 超过 protected budget 时 fail-closed，不得静默删除；
- ContextSource 之间使用显式配额与可解释评分；
- 输出必须保留 reserve，不能把窗口全部占满；
- selection / exclusion 原因进入 ContextAssemblyTrace。

### 7.4 Compression

优先级：

1. deterministic dedup；
2. 删除重复日志与低价值 Observation；
3. raw → summary + reference；
4. structured compaction；
5. optional LLM summarizer。

LLM summarizer 不是 MVP 硬依赖。若启用，必须：

- 保留 source refs；
- 区分 fact / decision / hypothesis / todo；
- 通过 constraint-retention fixture；
- 摘要失败时回退 deterministic path；
- 不把摘要结果自动写成长期 verified memory。

### 7.5 Lightweight Memory

首切片不引入独立向量数据库。使用 SQLite registry + FTS5 / metadata scoring：

- semantic-like project knowledge；
- episodic task result；
- procedural verified workflow；
- negative failed attempt；
- user preference。

写入策略：

- 不是每轮都写；
- 只有 explicit preference、confirmed decision、verified workflow、stable project fact、high-value failure 才能进入候选；
- 相似去重、supersede、TTL / invalidation；
- sensitive / secret 永不写入；
- automatic candidate 与 user-confirmed memory 区分状态。

召回策略：

- keyword / scope / recency / priority / task alignment / token cost 混合评分；
- threshold + top-k + per-kind quota；
- stale memory 显式标记；
- 召回不等于必选，仍经过 ContextOrchestrator。

### 7.6 Prompt Assembly

PromptAssembler 只负责稳定分区与 Provider payload：

```text
[System: Constitution]
[System: Role / Mode]
[System: Workspace Rules]
[System: Permission View]
[System: Task State]
[System: Retrieved Memory]
[System/Data: Retrieved Evidence]
[Messages: Recent Conversation]
[Tool: Recent Results]
[User: Current Request]
```

需要记录静态 section fingerprint、动态 section fingerprint、prompt version 和 token estimate，为 Prompt Cache、Trace 与 Eval 提供依据。

## 8. v0.08 Eval

- Constraint Retention；
- Context Precision / Recall；
- Conflict Resolution Accuracy；
- Stale Memory Rate；
- Memory Write Precision；
- Prompt Injection Containment；
- Token Efficiency；
- Compaction Drift；
- Tool Selection Accuracy；
- same task / same fixture assembly determinism；
- Context build latency。

## 9. v0.08 明确延期

- 独立 Vector DB；
- 自动 Skill 生成；
- 全量语义 Memory embedding；
- 任意 Provider Prompt Cache 强绑定；
- 通用 policy DSL；
- 让模型自由决定指令优先级；
- 将 RAG、MCP 或 Skill Registry 直接塞进 QueryEngine。

## 10. v0.08 GO / NO-GO

`GO`：

- QueryEngine 保持薄 façade；
- 每次模型调用有可回溯 PromptAssembly；
- protected items 在压缩后 100% 保留；
- external instruction 不进入高 trust section；
- Memory 写入、召回和失效有独立证据；
- token budget 超限时行为可预测。

`NO-GO`：

- Prompt 由多个模块直接字符串拼接；
- Context 超限时随机截断；
- hypothesis 被压缩成 fact；
- stale memory 无标记进入 Prompt；
- QueryEngine 直接执行 Memory / RAG / Tool 逻辑。

---

# v0.09：MCP Tool Gateway MVP

## 11. 用户故事

用户配置一个受信或待审查的 MCP Server 后，PaperClaw 可以发现其工具，将工具描述归一化为内部 Tool contract，并通过现有 ToolRegistry、Schema validation、Permission、timeout、Trace 和 Run Budget 调用。

MCP Server 失联、返回非法 schema、输出过大、请求越权或包含 Prompt Injection 时，PaperClaw fail-closed 或降级，不影响本地 Tool 的既有路径。

## 12. 定位与边界

```text
MCP Transport Adapter
        ↓
MCP Client Session
        ↓ list / call
MCP Capability Normalizer
        ↓
PaperClaw ToolDescriptor / ResourceDescriptor
        ↓
ToolRegistry + Permission + Executor + Trace
```

原则：

- MCP 是外部能力协议，不是新的 Agent Runtime；
- MCP Tool 不直接获得 PaperClaw workspace 权限；
- MCP Prompt / Resource 是外部 data，不自动成为 system instruction；
- 先实现 Client 侧最小闭环；本地 deterministic test server 只用于验收；
- Transport 和协议版本在执行 SOP 时以官方当前规范重新冻结，本草案不锁死长期细节。

## 13. 最小契约

```text
MCPServerConfig
MCPServerIdentity
MCPConnectionState
MCPCapabilitySnapshot
MCPToolDescriptor
MCPResourceDescriptor
MCPInvocationRequest
MCPInvocationResult
MCPError
MCPProvenance
```

必须记录：

- server identity / config fingerprint；
- protocol / capability version；
- discovery timestamp / cache status；
- original schema hash / normalized schema hash；
- tool side-effect classification；
- request / response size；
- timeout / cancellation / error taxonomy；
- permission decision / trace id。

## 14. 必做能力

- 一个本地 transport baseline；
- connect / initialize / discovery / call / close lifecycle；
- tool schema normalization；
- unknown / unsupported schema fail-closed；
- per-server allowlist；
- tool name collision namespace；
- payload、timeout、并发和调用次数限制；
- cancellation propagation；
- output redaction、truncate-before-context 禁止，必须先 redact 再 truncate；
- discovery cache 与 stale 标记；
- server unavailable 时本地 Tool 路径不受影响；
- deterministic fake server integration test；
- MCP Tool event 进入现有 Trace，不创建第二套事实源。

## 15. Capability Progressive Disclosure

不能把所有 MCP Tool schema 每轮全部注入模型。首切片采用：

1. server / capability metadata 本地索引；
2. 基于用户任务、关键词、scope 和 permission 选出候选工具；
3. 只把 Top-K ToolDescriptor 交给 ContextOrchestrator；
4. 模型选择后，执行层再次按真实参数校验权限；
5. Tool miss / wrong selection 进入 Eval。

这与 v0.08 ContextOrchestrator 共享 selection trace，但 MCP Gateway 不直接修改 Prompt。

## 16. MCP Eval

- discovery correctness；
- schema normalization correctness；
- tool selection accuracy；
- invalid schema rejection；
- permission bypass rate = 0；
- timeout / disconnect recovery；
- oversized payload containment；
- secret / injection leakage = 0；
- stale capability rate；
- local Tool regression = 0。

## 17. v0.09 明确延期

- 插件市场；
- 自动信任任意 Server；
- 任意第三方代码安装；
- 多租户 MCP Gateway；
- MCP Server 托管平台；
- 把 MCP Resource 当 verified Evidence；
- 未经评估的远程写操作自动重试。

---

# v0.09.1：Hybrid RAG 与 Evidence Engine MVP

## 18. 与原 v0.08 草案的关系

原 `PaperClaw_v0.08_RetrievalRAG与EvidenceEngine_SOP草案.md` 保留为本切片的详细设计来源。本修订只改变前置依赖和 MVP 收缩：

- Retrieval 结果必须先转为 `ContextCandidate`；
- ContextOrchestrator 决定哪些结果进入模型；
- 先做本地可复现 baseline，再做 online scholarly backend；
- 先证明 Retrieval / Grounding Eval，再决定 Dense、Reranker 或 GraphRAG。

## 19. MVP 用户故事

用户导入一组本地 Markdown / 文档 fixture 后，可以通过 BM25 baseline 检索相关 chunk；可选 Dense adapter 打开后，系统使用 Hybrid + RRF；最终回答中的每个引用可以回溯到 document version、chunk、locator 和 content hash。

## 20. 最小实现顺序

1. Document / Version / Chunk / IndexManifest；
2. SQLite document registry + FTS5 / BM25；
3. deterministic chunking + metadata；
4. incremental add / update / delete；
5. Retrieval API + ContextSource adapter；
6. Retrieval Eval dataset；
7. optional EmbeddingProvider / in-memory VectorIndex；
8. RRF ablation；
9. optional reranker；
10. EvidenceRecord / CitationAnchor / Grounding Eval。

## 21. 必须回答的工程问题

- Chunk 为什么这样切，如何处理标题、代码、表格和超长段落；
- Index 如何增量更新、失效和重建；
- BM25 与 Dense 各自失败在哪里；
- Hybrid 如何融合，为什么选择 RRF；
- Top-K 如何受 Context budget 约束；
- duplicate / stale / conflicting chunk 如何处理；
- Retrieval 正确但 Generation 错误如何区分；
- Citation correctness 与 faithfulness 如何评估；
- offline、cache-first、online 如何降级。

## 22. MVP Gate

至少包含：

- BM25 baseline；
- Hybrid 公平对照；
- Recall@K、MRR、nDCG、Duplicate Rate；
- Context Precision / Recall；
- Faithfulness、Citation Correctness、Unsupported Claim Rate；
- Prompt injection fixture；
- broken index rebuild；
- stale document invalidation；
- no-answer / abstention case。

Vector DB、CrossEncoder 和 GraphRAG 都不能成为 MVP 的前置条件。

---

# v0.09.2：SeededResearch Domain Showcase（可选）

## 23. 与原 v0.09 草案的关系

原 `PaperClaw_v0.09_SeededResearch学术裁缝垂直切片_SOP草案.md` 完整保留，不删除、不降格为无效文档。

调整仅是：

- 不再阻塞通用 Runtime、MCP、RAG 和 Release 主线；
- 只有 v0.08 Context、v0.09 MCP（如需要外部工具）和 v0.09.1 Evidence 通过后才冻结；
- 作为 Research domain showcase，用于展示通用 Runtime 如何支撑复杂领域；
- 校招开发岗面试中重点讲 adapter、contract、Evidence、Eval、failure handling，不把论文训练或自动写作包装成主贡献。

若时间不足，可以只交付：

- Seed Audit；
- Evidence Gap；
- Baseline Card；
- Compatibility Matrix；
- GO / REVISE / NO-GO；
- Offline Replay fixture。

不能为了版本号完成而自动生成训练结果、实验结论或论文正文。

---

# v0.10：Model Policy、Reliability、Security、Packaging 与 Release

## 24. 与原 v0.10 草案的关系

原 `PaperClaw_v0.10_ReliabilitySecurityPackagingRelease_SOP草案.md` 继续作为 Release / Security 主体。新增一个受控的 Model Policy 切片，补齐校招开发岗常见的模型选择、成本、fallback、限流与可观测性问题。

## 25. ModelPolicyRouter 最小边界

```text
ModelRequestProfile
    capability / context length / structured output / cost budget
        ↓
ModelPolicyRouter
        ↓
Provider Candidate
        ↓
OpenAICompatibleModel / future adapter
```

路由输入只允许使用结构化事实：

- required capability；
- context size；
- structured-output requirement；
- task risk；
- latency / cost budget；
- provider health；
- explicit user override。

不得使用隐藏 reasoning 或未经验证的“任务看起来难”作为唯一依据。

## 26. Fallback 规则

- fallback chain 必须显式配置并进入 Trace；
- authentication、permission、invalid request 不自动 fallback；
- network、429、5xx 可在 bounded retry 后切换候选；
- context overflow 可以触发 ContextOrchestrator 重新压缩，不能直接丢约束；
- structured output failure 先进行有限 repair / retry，不能无限循环；
- 高风险写操作在模型切换后必须重新走 Permission；
- fallback 不得把“失败”伪装成同模型成功；
- Provider / model / attempts / cost / latency 写入安全 metadata。

## 27. Usage / Cost / Rate Limit

至少记录：

- input / output / total tokens；
- attempt / retry / fallback count；
- duration；
- estimated cost（标记 pricing snapshot version）；
- cache hit（Provider 可提供时）；
- provider error code；
- concurrency slot / rate-limit wait。

成本估算不是账单事实，必须区分 estimated 与 provider-reported。

## 28. v0.10 主体继续沿用的硬门

- version single source；
- Windows clean install；
- Ubuntu / WSL contract test；
- Shell backend 与 path contract；
- Permission / Secret / SSRF / path escape；
- SQLite migration / online backup / restore / crash drill；
- unknown_outcome 不自动重放；
- wheel / sdist / pip check；
- lock / vulnerability / secret / license scan；
- SBOM / THIRD_PARTY / NOTICE；
- deterministic offline demo；
- performance baseline；
- known limitations；
- release manifest / checksum / rollback instructions。

## 29. v0.10 明确非目标

- 通用多云 LLM Gateway；
- 动态竞价路由；
- 自动在线学习 Router；
- 多租户计费平台；
- 模型训练、LoRA、SFT、DPO、GRPO 流水线；
- 将 Prompt 或 Router 配置隐藏在不可审计的模型决策中；
- 为追求“生产级”引入分布式队列、Kubernetes 或独立微服务集群。

---

# 30. 校招开发向面试覆盖矩阵

| 高频问题 | 主要版本 | 可展示证据 |
|---|---|---|
| Prompt Engineering、Context Engineering、Harness、Loop 的区别 | v0.05 / v0.08 | QueryEngine 边界、ContextOrchestrator、PromptAssembly Trace |
| 上下文窗口满了怎么办 | v0.04 / v0.08 | budget allocation、protected items、deterministic compaction |
| 长短期记忆怎么设计，如何避免越聊越脏 | v0.08 | MemoryWriteDecision、dedup、supersede、TTL、stale fixture |
| 动态 Prompt 和静态 Prompt 如何组装 | v0.08 | PromptSection、fingerprint、assembly trace |
| 指令、项目规则、历史记忆冲突怎么办 | v0.08 | trust / scope / freshness conflict fixtures |
| QueryEngine 是否应该负责拼 Prompt | v0.05 / v0.08 | 薄 façade + injected ContextOrchestrator |
| Agent 如何调用工具 | v0.01 / v0.05 | ToolRegistry、validation、budget、Trace |
| MCP 解决什么问题，怎么接入 | v0.09 | discovery、normalization、Permission、fake server E2E |
| Skill / Tool 太多如何选择 | v0.08 / v0.09 | progressive disclosure、selection trace、tool accuracy |
| RAG 完整链路 | v0.09.1 | ingestion、chunk、index、retrieve、fusion、context、citation |
| BM25 与向量检索区别 | v0.09.1 | baseline / hybrid ablation |
| Chunk 如何设计 | v0.09.1 | chunk manifest、locator、eval dataset |
| RAG 怎么评估 | v0.09.1 | Recall@K、MRR、nDCG、faithfulness、citation |
| 小模型能力不足怎么办 | v0.08 / v0.10 | task/context reduction、capability routing、bounded fallback |
| Provider 429、断线、超时怎么办 | v0.07.1+ / v0.10 | RetryPolicy、error taxonomy、fallback trace |
| 如何控制成本和延迟 | v0.08 / v0.10 | token budget、usage/cost/latency metadata |
| Agent 如何做生产可靠性与安全 | v0.10 | permission、redaction、crash recovery、release gates |
| Agent 如何评估 | v0.07 / v0.08 / v0.09.1 | Trace Eval、Context Eval、Retrieval/Grounding Eval |

以下内容不应硬塞进 PaperClaw 版本：

- LeetCode 手撕；
- SQL 执行计划、索引与事务；
- OS、网络、计算机组成基础；
- Java / Go / Python 语言八股；
- 通用后端系统设计。

这些属于个人校招准备主线，PaperClaw 只负责证明 Agent Runtime、工程设计和可验证落地能力。

# 31. 执行顺序与停止条件

优先顺序：

1. 冻结 v0.08 Context Orchestration MVP；
2. 完成离线 Context Eval 后再开始 MCP；
3. MCP 工具接入稳定后，冻结 v0.09.1 RAG MVP；
4. 根据时间决定是否做 SeededResearch showcase；
5. 最后统一做 v0.10 Model Policy 和 Release hardening。

停止条件：

- 每个版本只保留一个用户可见闭环；
- MVP 最多三个实施 Phase；
- 没有测试或 Trace 证明必要时，不升级候选能力；
- GraphRAG、Vector DB、LLM summarizer、remote MCP write、复杂 Router 都默认延期；
- 校招时间不足时，优先保证 v0.08、v0.09、v0.09.1 有可运行 demo，SeededResearch 可只保留设计与离线 fixture。

# 32. 下一步冻结前需要讨论的问题

1. v0.08 首切片是否包含真正的 `memory_items` 表，还是先使用现有 SessionEvent / ContextItem 投影；
2. ContextOrchestrator 是扩展现有 `ContextBuilder`，还是在其上增加 policy façade；
3. v0.08 的模型调用入口是否只接单 Agent，MultiAgent 只做 role-scoped regression；
4. MCP 首切片选择哪一种本地 transport baseline；
5. v0.09.1 的文档类型先只支持 Markdown / plain text，还是加入 PDF parser adapter；
6. ModelPolicyRouter 是否在 v0.10 只支持静态规则，不做动态 health scoring；
7. SeededResearch 是否作为校招演示的第二故事，还是完全移到发布后。

冻结任何 SOP 前，必须重新检查当前 `main`、已有实现、测试、CI、Handoff 和官方协议现状，不能直接按本草案编码。
