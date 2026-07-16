# PaperClaw v0.08–v0.10：校招开发向路线修订草案

> 状态：增量修订草案，不替换或删除既有 v0.08、v0.09、v0.10 草案  
> 日期：2026-07-16  
> 目标：将后续路线统一拆成“当前版本 MVP 实现”与“Post-MVP 后续升级待办”两层，避免把长期能力混入版本完成条件。

## 1. 与旧草案的关系

以下旧文档继续保留，作为详细设计库和候选能力来源：

- `PaperClaw_v0.08_RetrievalRAG与EvidenceEngine_SOP草案.md`；
- `PaperClaw_v0.09_SeededResearch学术裁缝垂直切片_SOP草案.md`；
- `PaperClaw_v0.10_ReliabilitySecurityPackagingRelease_SOP草案.md`。

本文件只重新定义执行顺序、MVP 边界和后续升级池，不声明新增能力已经实现。旧文档中已经形成的 Evidence 状态机、RAG Eval、SeededResearch 契约和 Release Checklist 仍可作为后续 SOP 的输入。

## 2. 统一拆分规则

每个版本统一采用两个部分：

```text
v0.XX MVP 实现
├── 一个用户可见闭环
├── 最多三个实施 Phase
├── 最小契约
├── 最小测试与离线演示
├── GO / NO-GO
└── 明确非目标

v0.XX Post-MVP 后续升级待办
├── 不属于当前完成条件
├── 没有默认实施顺序
├── 必须写明升级触发条件
├── 必须基于真实失败 Trace / Eval / 用户故事
└── 升级时另开独立 SOP
```

约束：

1. MVP 完成后停止，不自动进入升级池；
2. 升级待办不能因为接口已预留就描述为已实现；
3. 一个候选只有在真实 Trace、Eval 或下游用户故事证明必要时，才能升级为独立 SOP；
4. QueryEngine 始终保持薄 façade，不直接拼 Prompt、执行 Tool、读取 RAG、管理 MCP 或实现 domain 规则；
5. 每个 MVP 默认最多三个实施 Phase，超过范围必须继续拆版本。

## 3. 修订后的主线

```text
v0.07.x Trace / Eval / MultiAgent View
        ↓
v0.08 Context Orchestration / Dynamic Prompt Assembly MVP
        ↓
v0.09 MCP Tool Gateway MVP
        ↓
v0.09.1 Hybrid RAG / Evidence Engine MVP
        ↓
v0.09.2 SeededResearch Domain Showcase MVP（可选）
        ↓
v0.10 Model Policy / Reliability / Security / Packaging / Release MVP
```

每个版本均有独立 Post-MVP 升级池，不阻塞下一主线版本。

---

# v0.08：Context Orchestration 与 Dynamic Prompt Assembly

## 4. v0.08 MVP 实现

### 4.1 用户故事

用户提交一个跨多轮 Coding / Research 任务后，PaperClaw 在每次模型调用前，从系统规则、角色、Workspace、Task State、最近消息、Tool Result 和已有 Context / Checkpoint 中选择当前真正需要的信息，在固定 token 预算内生成可追踪的 Provider 输入。

当项目规则、用户要求、历史内容或外部文本冲突时，系统按照显式 trust、scope、priority 和 freshness 处理，而不是依赖模型自由猜测。

### 4.2 MVP 边界

```text
QueryEngine
    Run lifecycle / limits / stop / events / result
        ↓
AgentRuntimeExecutor / Agent Loop
        ↓
ContextOrchestrator
    collect / resolve / select / allocate / compact
        ↓
PromptAssembler
    render selected ContextItem into provider payload
        ↓
ChatModel
```

必须保持：

- QueryEngine 不直接拼接 Prompt；
- ContextOrchestrator 不调用 Tool；
- PromptAssembler 不决定 Permission，不提升 Evidence trust；
- 外部 README、网页、PDF、MCP Resource 和 RAG Chunk 一律属于 untrusted data；
- Prompt 优先级不能替代执行层 Permission。

### 4.3 MVP 最小契约

```text
ContextRequest
ContextPolicy
ContextCandidate
ContextSelection
ContextConflict
ContextBudgetAllocation
PromptSection
PromptAssembly
ContextAssemblyTrace
```

关键字段：

```text
run_id / step_id
source / source_ref
layer / kind / scope
priority / trust / freshness
estimated_tokens / selected_tokens
selection_reason / exclusion_reason
conflict_group / conflict_resolution
compressible / pinned / sensitive
content_hash / policy_version / prompt_version
```

### 4.4 MVP 必做能力

1. 接入现有 Runtime Constitution、Role / Mode、Workspace Rules、Task State、recent conversation、recent Tool Results 和 v0.04 Context / Checkpoint；
2. 所有来源先转为 `ContextCandidate`，禁止模块直接字符串拼 Prompt；
3. 实现显式冲突规则：system policy > project rule > user request > external data；
4. verified fact 不被 hypothesis 覆盖，用户显式纠正可使旧 preference 失效；
5. 区分 protected、task、recent message、tool result、retrieval 和 output reserve 预算；
6. protected 内容超预算时 fail-closed，不静默删除目标、硬约束、决策、失败和 Evidence ref；
7. 优先复用 v0.04 deterministic dedup / compaction；
8. PromptAssembler 生成稳定 section、prompt version、fingerprint 和 token estimate；
9. 每次 assembly 输出 selection / exclusion / conflict Trace；
10. Retrieval 只预留 `ContextSource` Protocol，不在本版本实现 RAG。

### 4.5 MVP 三阶段

#### Phase A：ContextOrchestrator 契约与现有 ContextBuilder 适配

- 冻结请求、候选、选择、预算、冲突和 PromptAssembly 契约；
- 在现有 ContextBuilder 上增加 policy façade，优先避免复制一套完整 Pipeline；
- 保持当前公共 API 和 v0.04 回归兼容。

#### Phase B：预算、冲突与 Prompt Assembly

- 实现 protected budget、source quota、output reserve；
- 实现 deterministic conflict resolver；
- 实现 PromptAssembler 与 assembly trace；
- 接入单 Agent Runtime，MultiAgent 只做 role-scoped regression。

#### Phase C：Context Eval 与离线演示

- 固定跨域 fixture；
- 对比旧路径和新 assembly；
- 验证约束保留、注入隔离、token 效率和 deterministic output；
- 形成一条可复现 CLI demo。

### 4.6 MVP Eval 与 Gate

必须覆盖：

- Constraint Retention；
- Context Precision / Recall；
- Conflict Resolution Accuracy；
- Prompt Injection Containment；
- Token Efficiency；
- Compaction Drift；
- same fixture assembly determinism；
- Context build latency。

`GO`：

- QueryEngine 保持薄 façade；
- 每次模型调用有可回溯 PromptAssembly；
- protected item 保留率 100%；
- external instruction 不进入高 trust section；
- 超预算行为可预测；
- 旧单 Agent 路径无功能回归。

`NO-GO`：

- 多个模块继续直接拼 Prompt；
- Context 超限时随机截断；
- hypothesis 被压缩为 fact；
- QueryEngine 直接执行 Context / RAG / Tool 逻辑。

### 4.7 MVP 明确非目标

- 独立向量数据库；
- LLM 摘要器作为硬依赖；
- 完整长期 Memory；
- 自动 Skill 生成；
- Provider-specific Prompt Cache 强绑定；
- 通用 policy DSL；
- RAG、MCP 或 Skill Registry 直接接入 QueryEngine。

## 5. v0.08 Post-MVP 后续升级待办

候选项：

- `memory_items` SQLite 表与 Memory lifecycle；
- user-confirmed / automatic candidate 两级 Memory 状态；
- keyword + scope + recency + task alignment 的 Memory 召回；
- stale、TTL、supersede、删除和敏感信息拒绝；
- optional LLM summarizer；
- Prompt Cache fingerprint 与 provider cache hint；
- ContextSource 动态权重；
- capability / Skill progressive disclosure；
- MultiAgent shared / private context policy；
- Context assembly 可视化面板。

升级触发条件：

- 多轮任务真实出现重复信息导致 token 浪费；
- Session resume 缺少稳定长期知识；
- Context Eval 证明静态 quota 明显损害召回；
- MCP / RAG 接入后候选能力或 Evidence 数量超过当前预算策略；
- 至少有一条失败 Trace 可以稳定复现。

---

# v0.09：MCP Tool Gateway

## 6. v0.09 MVP 实现

### 6.1 用户故事

用户配置一个本地或明确授权的 MCP Server 后，PaperClaw 可以发现其工具，将描述归一化为内部 Tool contract，并通过既有 ToolRegistry、Schema validation、Permission、timeout、Trace 和 Run Budget 调用。

MCP Server 失联、schema 非法、输出过大或请求越权时，系统 fail-closed 或降级，不影响本地 Tool 路径。

### 6.2 MVP 边界

```text
MCP Transport Adapter
        ↓
MCP Client Session
        ↓
Capability Normalizer
        ↓
PaperClaw ToolDescriptor
        ↓
ToolRegistry / Permission / Executor / Trace
```

原则：

- MCP 是外部能力协议，不是新的 Agent Runtime；
- MCP Tool 不自动获得 Workspace 权限；
- MCP Prompt / Resource 是外部 data，不自动成为 system instruction；
- 首切片只做 Client 侧闭环；
- 具体协议和 transport 在冻结 SOP 时按官方当前规范重新核对。

### 6.3 MVP 最小契约

```text
MCPServerConfig
MCPServerIdentity
MCPConnectionState
MCPCapabilitySnapshot
MCPToolDescriptor
MCPInvocationRequest
MCPInvocationResult
MCPError
MCPProvenance
```

### 6.4 MVP 必做能力

1. 一个本地 transport baseline；
2. connect / initialize / discover / call / close lifecycle；
3. tool schema normalization；
4. unknown / unsupported schema fail-closed；
5. per-server allowlist；
6. tool name collision namespace；
7. payload、timeout、并发和调用次数限制；
8. cancellation propagation；
9. 先 redact 再 truncate；
10. capability cache 与 stale 标记；
11. deterministic fake MCP server integration test；
12. MCP event 进入现有 Trace，不新建第二套事实源。

### 6.5 MVP 三阶段

#### Phase A：协议边界与本地测试 Server

- 冻结 MCP adapter / normalized Tool contract；
- 实现 deterministic fake server；
- 覆盖初始化、发现、调用、关闭和错误分类。

#### Phase B：ToolRegistry、Permission 与 Runtime 接入

- MCP Tool 注册到既有 Registry；
- 调用前按真实参数重验 Permission；
- 接入 timeout、cancel、budget、redaction 和 Trace；
- 本地 Tool 与 MCP Tool 保持统一结果契约。

#### Phase C：Capability Selection 与验收

- 本地索引 capability metadata；
- 基于任务、关键词、scope 和 permission 选出 Top-K ToolDescriptor；
- 只将候选工具交给 v0.08 ContextOrchestrator；
- 完成 fake server E2E 和失败注入。

### 6.6 MVP Eval 与 Gate

- discovery correctness；
- schema normalization correctness；
- invalid schema rejection；
- tool selection accuracy；
- permission bypass rate = 0；
- timeout / disconnect containment；
- oversized payload containment；
- secret / injection leakage = 0；
- local Tool regression = 0。

`GO`：MCP 工具从发现到调用完整经过 Registry、Permission、Executor 和 Trace，Server 失败不破坏本地 Tool。

`NO-GO`：MCP Tool 绕过 Permission、远端 Prompt 进入 system instruction、schema 不明仍执行、断线导致 Run 无界挂起。

### 6.7 MVP 明确非目标

- 插件市场；
- 自动信任任意 Server；
- 多租户 MCP Gateway；
- 任意第三方代码自动安装；
- MCP Server 托管平台；
- MCP Resource 自动升级为 verified Evidence；
- 远程写操作自动重试。

## 7. v0.09 Post-MVP 后续升级待办

候选项：

- 多 transport 支持；
- Resources / Prompts adapter；
- capability refresh / reconnect state machine；
- server health scoring；
- per-tool cost / latency model；
- Human approval UI；
- remote write operation idempotency；
- MCP Resource → RAG ingestion adapter；
- server profile import / export；
- capability version migration；
- 多 Server 冲突与路由策略。

升级触发条件：

- 真实 Server 不支持首个 transport；
- discovery cache stale 导致稳定失败；
- 多 Server 出现同名能力或选择错误；
- 用户故事明确需要 Resource / Prompt；
- 远程写操作有可审计的业务需求和 Permission 设计。

---

# v0.09.1：Hybrid RAG 与 Evidence Engine

## 8. v0.09.1 MVP 实现

### 8.1 用户故事

用户导入一组本地 Markdown / plain text 文档后，可以通过 SQLite FTS5 / BM25 检索相关 chunk；检索结果以标准 `ContextCandidate` 进入 v0.08 ContextOrchestrator，最终引用能够回溯到 document version、chunk、locator 和 content hash。

### 8.2 MVP 边界

本版本不是“先接一个向量数据库”，而是先完成：

```text
Document Registry
→ deterministic chunking
→ FTS5 / BM25 baseline
→ incremental index
→ Retrieval ContextSource
→ CitationAnchor
→ Retrieval / Grounding Eval
```

原 `PaperClaw_v0.08_RetrievalRAG与EvidenceEngine_SOP草案.md` 继续作为详细设计来源，但 Dense、Reranker、online scholarly backend 和复杂 Evidence 状态不自动进入 MVP。

### 8.3 MVP 最小契约

```text
DocumentIdentity
DocumentVersion
SourceArtifact
Chunk
IndexManifest
RetrievalRequest
RetrievalCandidate
RankedResult
CitationAnchor
RetrievalRun
```

### 8.4 MVP 必做能力

1. SQLite document registry；
2. Markdown / plain text deterministic parser；
3. 标题、段落、超长块和 overlap 的固定 chunk config；
4. Chunk 绑定 version、source hash、locator 和 chunk config；
5. FTS5 / BM25 baseline；
6. incremental add / update / delete；
7. broken index rebuild；
8. Retrieval ContextSource adapter；
9. duplicate / stale 过滤；
10. citation locator；
11. no-answer / abstention case；
12. Retrieval 与 Generation / Grounding 分离评估。

### 8.5 MVP 三阶段

#### Phase A：Document / Chunk / Index Contract

- 冻结 DocumentVersion、Chunk、IndexManifest；
- 实现 parser 和 deterministic chunking；
- 实现 SQLite registry 与 FTS5 schema。

#### Phase B：Retrieval 与 Context 接入

- 实现 BM25 查询、过滤、去重和 stale invalidation；
- 实现 incremental index；
- 通过 ContextSource 向 v0.08 提交候选，不直接拼 Prompt。

#### Phase C：Eval 与引用闭环

- 构建 graded relevance fixture；
- 计算 Recall@K、MRR、nDCG、Duplicate Rate；
- 验证 Citation Correctness、Unsupported Claim Rate 和 abstention；
- 完成本地离线 demo。

### 8.6 MVP Gate

必须包含：

- BM25 baseline；
- Recall@K、MRR、nDCG；
- Context Precision / Recall；
- Citation Correctness；
- Unsupported Claim Rate；
- prompt injection fixture；
- stale document invalidation；
- broken index rebuild；
- no-answer / abstention。

`GO`：每个进入模型的 chunk 可回溯，index 可增量更新和重建，Retrieval 失败与 Generation 失败可区分。

`NO-GO`：检索结果直接升级 verified Evidence、Chunk 无版本和 locator、全文缺失时模型补写细节、RAG 绕过 Context budget。

### 8.7 MVP 明确非目标

- Vector DB；
- Dense Retrieval；
- CrossEncoder；
- GraphRAG；
- PDF OCR；
- 生产爬虫；
- 自动下载受限全文；
- 在线学术搜索作为 MVP 必需条件。

## 9. v0.09.1 Post-MVP 后续升级待办

候选项：

- `EmbeddingProvider` 与 in-memory / FAISS `VectorIndex`；
- BM25 + Dense + RRF；
- optional CrossEncoder reranker；
- PDF parser / OCR adapter；
- online Crossref、Semantic Scholar、arXiv、GitHub backend；
- cache-first / online / offline 三模式；
- Evidence identity resolve 与状态机；
- claim extraction、counter-evidence 与 conflict；
- advanced citation repair；
- GraphRAG / knowledge graph；
- 大规模 Vector DB。

升级触发条件：

- BM25 在固定 Eval 上出现稳定语义漏召回；
- Hybrid ablation 能证明 Dense 带来可解释收益；
- 文档关系型多跳问题成为真实瓶颈；
- PDF 是明确用户故事，而不是为了堆功能；
- 本地索引规模证明 SQLite / in-memory 已不足。

---

# v0.09.2：SeededResearch Domain Showcase

## 10. v0.09.2 MVP 实现

### 10.1 定位

SeededResearch 是可选 domain showcase，不阻塞 MCP、RAG 或 Release。它用于证明通用 Runtime 能承载复杂 Research domain，而不是把学术逻辑塞回 Runtime 核心。

### 10.2 MVP 用户故事

用户输入研究方向和少量真假混杂种子论文，系统交付一个可追溯的 Seed Audit / Evidence Gap / Baseline / Compatibility / Decision Package，并允许 `GO / REVISE / NO-GO`，不为了完成任务强行生成创新点或实验结果。

### 10.3 MVP 必做能力

- ResearchContract；
- Seed identity resolve / fake seed rejection；
- Seed Audit；
- Evidence Gap；
- v0.09.1 Retrieval 接入；
- Baseline Card；
- Compatibility Matrix；
- bounded Reviewer；
- GO / REVISE / NO-GO；
- Offline Replay fixture。

### 10.4 MVP 三阶段

#### Phase A：Seed / Identity / Evidence Gap

冻结 SeedInput、Identity、Claim / Evidence ref 和 Gap 契约，完成真假种子 fixture。

#### Phase B：Baseline / Compatibility / Decision

接入 Retrieval，形成 Baseline Card、Compatibility Matrix 和 bounded Review。

#### Phase C：Research Package 与 Eval

交付离线 Research Package，验证 fake paper leakage、Evidence alignment、NO-GO calibration 和 schema parity。

### 10.5 MVP Gate

`GO`：假论文不进入 Evidence；所有 Claim 有 source ref；无法支持创新时能合法输出 NO-GO 或 Evidence Gap。

`NO-GO`：自动生成实验结果、把 metadata verified 当全文 verified、强行拼接 A+B+C、Domain 逻辑污染通用 QueryEngine / Context / Tool。

### 10.6 MVP 明确非目标

- 自动训练；
- 自动运行大规模实验；
- 自动生成论文正文；
- LoRA / SFT / DPO / GRPO；
- 全学科 ontology；
- 无人工 Gate 的高风险代码下载和执行。

## 11. v0.09.2 Post-MVP 后续升级待办

候选项：

- Method Family Explorer；
- Academic Tailor Skill；
- Novelty / falsifiability pressure test；
- Baseline reproduction runner；
- Experiment Matrix 与 ablation planning；
- competing / counter-evidence lanes；
- retraction / erratum / version relation；
- Repo commit / license / checkpoint freeze；
- Full Agent / Lite Chain / Offline Replay 三模式；
- Research Workbench UI。

升级触发条件：

- 通用 RAG / Evidence 已稳定；
- 至少三个跨领域 SeededResearch fixture；
- 当前 MVP 无法回答具体 Research 用户故事；
- 用户明确希望把该项目作为第二个校招展示故事。

---

# v0.10：Model Policy、Reliability、Security、Packaging 与 Release

## 12. v0.10 MVP 实现

### 12.1 用户故事

用户能在干净 Windows 环境安装、运行和卸载 PaperClaw；Provider 发生有限网络故障时有可观察重试和静态 fallback；Secret、越权、数据库恢复、构建和许可证通过硬 Gate；Offline demo 可重复执行。

### 12.2 MVP 收缩原则

原 `PaperClaw_v0.10_ReliabilitySecurityPackagingRelease_SOP草案.md` 范围过大，MVP 只保留发布必需闭环：

```text
version / package contract
+ clean install
+ static model policy
+ secret / permission gate
+ SQLite backup / restore smoke
+ deterministic offline demo
+ release manifest / known limitations
```

跨平台完整 Shell、SBOM 深化、容器隔离、复杂 crash recovery 和多 Provider Gateway 进入后续升级池。

### 12.3 MVP 最小契约

```text
ModelRequestProfile
ModelCandidate
ModelPolicyDecision
FallbackAttempt
ReleaseManifest
SupportMatrix
KnownLimitation
BackupManifest
```

### 12.4 MVP 必做能力

1. package version 单一来源；
2. Windows clean venv install / run / uninstall；
3. 静态 `ModelPolicyRouter`：capability、context length、structured output、cost ceiling、explicit override；
4. 显式 bounded fallback chain；
5. auth / permission / invalid request 不自动 fallback；
6. network / 429 / 5xx 在 bounded retry 后允许切换；
7. input / output tokens、attempt、retry、fallback、duration 和 estimated cost metadata；
8. Secret redaction canary；
9. Permission / path escape 最小安全 corpus；
10. SQLite online backup + restore smoke；
11. deterministic offline demo；
12. release manifest、support matrix、known limitations 和 checksum。

### 12.5 MVP 三阶段

#### Phase A：Version / Packaging / Model Policy

- 统一版本源；
- 冻结 CLI version、User-Agent 和 Trace metadata；
- 实现静态 Router 和 fallback trace；
- 构建 wheel / sdist 并 clean install。

#### Phase B：Security / Backup / Recovery Smoke

- Secret canary；
- Permission / path escape corpus；
- SQLite online backup；
- restore drill；
- unknown outcome 明确标记，不自动重放副作用。

#### Phase C：Offline Demo / Release Candidate

- 固定 clock、UUID、seed 和 fixture；
- 生成 manifest、checksum、support matrix 和 known limitations；
- Windows Tier 1 跑完整 release smoke。

### 12.6 MVP Gate

- package / CLI / User-Agent / Trace version 一致；
- clean install 和卸载成功；
- fallback 全链路可追踪；
- Secret 在 stdout、stderr、Trace、DB 和 export 中为 0；
- backup 可恢复 Session / Trace；
- wheel / sdist 不含 `.env`、绝对路径、临时文件和 artifacts；
- Offline demo 无网络和真实 API Key；
- known limitations 明确 native mode 非 OS sandbox。

`GO`：上述硬门全部通过。

`NO-GO`：Secret 泄露、越权执行、数据损坏、backup 不可恢复、构建物包含敏感内容、版本漂移或许可证不明。

### 12.7 MVP 明确非目标

- 通用多云 LLM Gateway；
- 动态健康度路由；
- 自动竞价路由；
- 多租户计费；
- Kubernetes / 分布式队列；
- Container-first sandbox；
- 全平台完整支持；
- 自动 PyPI 发布。

## 13. v0.10 Post-MVP 后续升级待办

候选项：

- Ubuntu / WSL Tier 2 扩展；
- Windows PowerShell / pwsh / POSIX / WSL Shell contract；
- process tree cleanup；
- full PermissionEngine `allow / ask / deny / sandbox`；
- SSRF、DNS rebinding、redirect 和 download isolation；
- schema migration checksum / downgrade refusal；
- transaction / outbox；
- unknown_outcome reconciliation；
- dependency lock、vulnerability、secret 和 license scan；
- SBOM、THIRD_PARTY、NOTICE；
- optional WSL / container sandbox；
- dynamic provider health scoring；
- cost-aware routing；
- Prompt Cache usage；
- TUI backpressure / resize / Ctrl+C 完整验收；
- performance baseline 与 regression gate；
- release workflow / PyPI automation。

升级触发条件：

- Tier 1 release 已稳定；
- 用户明确需要第二平台；
- crash / unknown outcome 有真实失败 Trace；
- Provider fallback 数据证明静态 Router 不足；
- 发布渠道要求 SBOM、签名或自动化；
- native application-level isolation 无法满足明确安全需求。

---

# 14. 面试覆盖矩阵

| 高频问题 | MVP 版本 | 后续升级 |
|---|---|---|
| Context Engineering、动态 Prompt | v0.08 | Memory、Prompt Cache、Skill selection |
| 上下文窗口满了怎么办 | v0.08 | LLM summarizer、动态 quota |
| QueryEngine 是否拼 Prompt | v0.05 + v0.08 | 无，边界保持不变 |
| MCP 如何接入 | v0.09 | Resource / Prompt、多 transport |
| Tool 太多如何选择 | v0.09 | health / cost-aware routing |
| RAG 完整链路 | v0.09.1 | Dense、RRF、Reranker、PDF |
| RAG 如何评估 | v0.09.1 | online dataset、GraphRAG Eval |
| Agent 如何支持科研 domain | v0.09.2 | Tailor、Novelty、Experiment runner |
| 小模型能力不足怎么办 | v0.08 + v0.10 | dynamic Model Router |
| 429、断线、超时怎么办 | v0.07.1+ + v0.10 | provider health / multi-provider policy |
| 如何控制成本 | v0.08 + v0.10 | cost-aware routing、cache |
| 安全、恢复和发布 | v0.10 | sandbox、供应链、跨平台、自动发布 |

以下内容仍单独准备，不硬塞进 PaperClaw：

- LeetCode 手撕；
- SQL 执行计划、索引和事务；
- OS、网络、计算机组成；
- Python / Java / Go 语言基础；
- 通用后端系统设计。

# 15. 执行顺序与停止条件

执行顺序：

1. 冻结并实现 v0.08 MVP；
2. v0.08 GO 后停止，单独决定是否开始 v0.09；
3. v0.09 GO 后开始 v0.09.1；
4. 根据求职时间决定是否实现 v0.09.2；
5. 最后执行 v0.10 Release MVP；
6. 所有 Post-MVP 候选均需单独授权。

停止条件：

- 每个 MVP 只有一个用户可见闭环；
- 每个 MVP 最多三个 Phase；
- 没有失败证据，不升级候选；
- GraphRAG、Vector DB、LLM summarizer、remote MCP write、复杂 Router 和生产级平台默认延期；
- 校招时间不足时，优先保证 v0.08、v0.09、v0.09.1 和 v0.10 有可运行离线 demo。

# 16. 冻结下一份 SOP 前的待讨论项

1. v0.08 采用现有 ContextBuilder 上层 policy façade，还是扩展其内部 Pipeline；
2. v0.08 MVP 是否完全不创建 `memory_items` 表；
3. MCP 首个 transport baseline；
4. v0.09.1 首批只支持 Markdown / plain text 是否足够；
5. v0.09.2 是否进入校招展示主线；
6. v0.10 静态 ModelPolicyRouter 的候选配置格式；
7. Release MVP 的 Windows Tier 1 Python 版本范围。

冻结任何 SOP 前，必须重新检查当前 `main`、现有实现、测试、CI、Handoff 和官方协议现状，不能直接按本草案编码。
