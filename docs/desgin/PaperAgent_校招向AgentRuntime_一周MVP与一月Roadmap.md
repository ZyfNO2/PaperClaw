# PaperAgent 校招向 Agent Runtime：一周 MVP 与一月 Roadmap

> 日期：2026-07-11  
> 目标：把 PaperAgent 从“一个 LangGraph 应用”收束成“可评估、可审计、可恢复的轻量 Agent Runtime + 科研检索 Domain”，用于校招简历、实习汇报和项目深挖。  
> 时间盒：第 7 天无论完成度如何都形成可演示 MVP；第 30 天形成稳定可运行版本。  
> 范围修订：**RAG 不是一周 MVP 的硬门**。优先完成 Agent loop、上下文、权限、工具、session、trace 与可复跑演示；RAG 可作为后续插件或独立项目补强。

---

## 1. 先给结论

当前项目并不薄弱，真正的问题是**技术资产很多，但缺少统一内核、可信指标和清晰叙事**。

仓库已经真实存在：

- LangGraph 研究流程、8 类 Query Matrix、多源检索和 ReAct 风格搜索；
- ACP capability registry、read/write 权限、工具调用 ledger；
- TF-IDF RAG、引用校验、无证据拒答；
- SQLite Job Repository、长任务 cancel/budget/checkpoint/resume；
- trace、source ledger、failure taxonomy 和 eval fixtures。

目前不能直接宣称已经完成：

- Claude Code / pi 风格的独立 Agent Loop 与 Context Compaction；
- 真正的 MCP Server 与 OS 级 sandbox；
- BM25 + Dense + RRF + Reranker 的完整 Hybrid RAG；
- Recall@K、MRR、nDCG、faithfulness 等真实检索质量评估；
- 统一数据库和 migration；
- 文档中部分历史 Memory、MCP、Interview Mode 模块已经归档或删除。

因此推荐的新定位是：

> **PaperAgent Workbench Runtime：一个可审计、可恢复、可扩展的 Research/Coding Agent Harness。它在 LangGraph 之外实现自己的 Agent Loop，并统一上下文预算、工具权限、长任务、session 与 trace；PaperAgent 科研流程只是第一个可插拔 domain。**

不要再以“节点数量”“Multi-Agent 数量”作为卖点。校招更值得讲的是：为什么这样分层、如何限制 Agent、如何复现失败、指标是否真的提升。

---

## 2. 两条实现路线

| 路线 | 做法 | 开发成本 | 扩展性 | 风险 | 结论 |
|---|---|---:|---:|---:|---|
| A. 仓内 Runtime Layer | 在现有 FastAPI/Python 项目中抽出通用 runtime，PaperAgent 作为首个 domain | 低 | 中高 | 容易和旧代码耦合 | **一周 MVP 推荐** |
| B. 独立 Mini Coding Agent | 新建独立 CLI/runtime，通过 ACP/MCP 调 PaperAgent | 中高 | 高 | 一周内易做成玩具；联调成本高 | 月度后半程再抽离 |

推荐先 A 后 B：第 1 周证明接口和评估闭环，第 3～4 周再把 runtime 抽成可独立运行的 CLI。这样既能复用已有资产，也能证明核心不依赖 LangGraph。

### 2.1 PocketFlow 作为轻量控制内核

新 Runtime 不必从零发明图执行器。推荐引入 **PocketFlow 风格的 100 行 Graph Core**：

```text
Node: prep -> exec -> post
Flow: 根据 action 选择 successor
Shared Store: 节点之间显式传递状态
SubFlow: 一个 Flow 也可以作为 Node 复用
```

在此基础上，Agent Loop 表达为：

```text
LoadContext
  -> CompactHistory
  -> DecideAction
  -> ValidateToolCall
  -> PermissionGate
  -> ExecuteTool
  -> VerifyResult
  -> PersistEvent
  -> CompactHistory / Done
```

PocketFlow 负责**控制流**；PaperAgent Runtime 自己负责它没有提供的能力：

- typed tool schema 与统一 ToolRegistry；
- `deny > ask > allow` 权限和 workspace boundary；
- session、checkpoint、JSONL/SQLite event store；
- token budget、结构化 compaction 与 pinned context；
- trace、cost、failure taxonomy 和 outcome evaluation；
- timeout、cancel、idempotency、secret redaction 与 sandbox adapter。

这样既保留 PocketFlow 的极简性，又能明确说明个人工程贡献不只是“调用 PocketFlow”。

### 2.2 参考项目分工

| 项目 | 借鉴内容 | 不照搬的部分 |
|---|---|---|
| PocketFlow | `Node/Flow/shared store/action routing`、Flow-is-Node、coding-agent tool loop | 不把共享 dict 当完整状态治理；补权限、持久化、trace、eval |
| pi | typed event、session tree、compaction、steer/abort | pi 没有内建细粒度 permission/sandbox |
| Claude Code | gather-act-verify loop、permission/hook/checkpoint 公开机制 | 不宣称复刻未公开内部实现 |
| OpenHands | Workspace、RiskAnalyzer、ConfirmationPolicy、OTEL 分层 | 一周内不引入整套平台 |
| τ-bench | final-state reward、policy/tool/task domain、`pass^k` | 不强制复现唯一 gold trajectory |
| LangGraph | 继续承载现有复杂科研 workflow | 不再让所有 runtime concern 都塞进 graph state |

---

## 3. 目标架构

```text
CLI / Web / Eval Runner
          |
     AgentRuntime
   /      |       \
AgentLoop ContextManager PolicyEngine
    |          |             |
PocketFlow SessionStore  ToolRegistry
               |          /        \
             SQLite   Repo Tools  Paper Tools
                                      |
                                  QueryEngine
                              |
             Planner -> Retriever -> Fusion/Rerank -> Verifier
                              |
                     Domain Capability
                   /          |          \
             Research Flow  Existing RAG  Coding Tools
                              |
                           Evaluator
```

### 3.1 最小核心接口

```python
class AgentRuntime:
    async def run(self, task, profile, session_id=None) -> RunResult: ...

class RuntimeFlow(Flow):
    """PocketFlow-style control graph; runtime services stay outside nodes."""
    ...

class ContextManager:
    def build(self, session, token_budget, pinned_items) -> ModelContext: ...
    def compact(self, session) -> MemorySnapshot: ...

class ToolRegistry:
    def register(self, tool, policy) -> None: ...
    async def invoke(self, call, principal, context) -> ToolResult: ...

class PolicyEngine:
    def decide(self, call, principal, workspace) -> allow | ask | deny: ...

class QueryEngine:
    async def run(self, query, context, policy) -> RetrievalResult: ...

class Evaluator:
    def evaluate(self, case, trajectory, final_state) -> EvalResult: ...
```

PocketFlow 风格 Flow 负责轻量 Agent 控制循环；LangGraph 只作为复杂科研 workflow adapter。`ToolRegistry`、上下文、权限、session 与评估不依赖其中任何一个图框架。

### 3.2 两个 Profile

- `research`：题目拆解、论文/数据集/代码检索、证据问答、引用与拒答。
- `coding_readonly`：`list/read/search/run_test`，用于仓库理解和测试诊断；第一周不自动写代码。

一个月版再增加受控 `apply_patch`。这样可展示“同一 runtime，不同工具和 policy”，比再造两个 Agent 更有价值。

---

## 4. 你还没明确提到、但项目必须补的内容

### 4.1 Threat Model，而不只是权限字段

- workspace 路径穿越；
- SSRF、重定向和内网地址访问；
- prompt injection / tool output poisoning；
- secret redaction；
- shell、写文件、网络、删除操作的风险分级；
- 项目信任（project trust）与真正 sandbox 的区别。

权限建议分为：

```text
READ_LOCAL < NETWORK_READ < SAFE_WRITE < EXECUTE < DESTRUCTIVE
```

Policy 输出必须是 `allow / ask / deny`，并写入 audit log。第一周做到应用级 policy；容器、VM 或 OS sandbox 放到月度版，不能把请求头权限包装成 sandbox。

### 4.2 可复现性元数据

每次 Eval 至少记录：

```text
git_commit / fixture_version / prompt_hash / model / provider /
temperature / tool_registry_version / policy_version / random_seed /
started_at / latency / token_usage / external_call_count
```

否则指标提升无法复现，也无法回答“是不是换模型带来的”。

### 4.3 Failure Injection

至少覆盖：429、timeout、空结果、坏 JSON、假 citation、工具越权、上下文溢出、worker crash。Agent 工程的价值通常在失败路径，不在 happy path。

### 4.4 Human Feedback 与 Gold Eval 隔离

- 用户点赞/采纳率用于产品反馈；
- Gold set 用于离线比较；
- 不允许把已看过的 holdout feedback 回灌到测试集后继续报同一成绩。

### 4.5 文档真实性审计

`docs/interview` 中部分说明仍指向已经删除或归档的 `rag_pipeline.py`、Memory、MCP 模块。面试前必须把表述分成 `implemented / prototype / planned`，避免面试官顺着文件追问时穿帮。

---

## 5. QueryEngine 设计

统一当前分散的 `query_matrix + search_planner + search_agent + retrieval_orchestrator`：

```text
User Query
  -> QueryNormalizer
  -> QueryPlanner（确定 family/source，不自由编造 placeholder query）
  -> Tool Router（policy + budget + concurrency）
  -> Retriever Adapters（arXiv/OpenAlex/Crossref/GitHub/...）
  -> Candidate Dedup
  -> Fusion / Rerank
  -> Evidence Verifier
  -> RetrievalResult + Trace + FailureReason
```

`RetrievalResult` 至少包含：

```text
candidates[] / citations[] / tool_calls[] / source_ledger /
query_plan / policy_decisions / latency_ms / cost / fallback_reason
```

设计重点不是增加 LLM 调用，而是：LLM 决定检索策略，确定性代码生成 query、执行工具、去重、验证和计量。

---

## 6. Context Manager：参考 pi，但只做够用版本

### 6.1 四层上下文

| 层 | 内容 | 生命周期 |
|---|---|---|
| Instruction | AGENTS、system policy、profile | 项目级 |
| Working Context | 最近对话、当前任务、最近工具结果 | 单次运行 |
| Session Transcript | message/tool/result JSONL 或 SQLite rows | 跨刷新/恢复 |
| Pinned Memory | 用户确认约束、EvidenceRef、已修改文件、失败签名 | 跨压缩 |

### 6.2 Compaction 规则

触发条件：

```text
estimated_tokens > context_window - reserve_tokens
```

压缩时：

- 保留最近 N tokens；
- 总结更早的完整 turns；
- tool call 与 tool result 不拆开；
- 永久保留 policy decision、用户确认、EvidenceRef、modified files、未解决错误；
- 记录 `first_kept_event_id`、`tokens_before/after` 和 summary hash；
- replay 后必须通过 state invariant 检查。

一周版不做向量记忆和“自动学习用户人格”；先把确定性 replay 和不丢关键状态做好。

---

## 7. Tool 与权限治理

在现有 ACP registry 上扩展元数据：

```json
{
  "name": "search_literature",
  "risk": "NETWORK_READ",
  "mutates_state": false,
  "timeout_s": 20,
  "max_calls_per_run": 5,
  "required_scope": "research:read",
  "input_schema": {},
  "output_schema": {}
}
```

每次调用统一经过：

```text
schema validate -> policy decide -> budget reserve -> execute
-> output sanitize -> trace -> budget settle -> return
```

第一周只需 6～8 个真实工具：

- 通用只读：`list_files`、`read_file`、`search_code`、`run_tests`；
- 科研工具：`plan_query`、`search_literature`、`query_rag`、`get_trace`。

月度版再做 MCP adapter。协议只是薄层，权限、schema、trace 必须复用同一个 registry。

---

## 8. Agent 评估系统与可选 RAG Track

一周 MVP 先证明 Agent Harness，不把 RAG 质量作为完成门。评估分为 Agent/System 主线与 RAG 可选线。

### 8.1 Agent / System 主线（MVP 必做）

| 指标 | 说明 |
|---|---|
| Task Success | 最终状态是否满足任务要求 |
| Policy Compliance | 是否有越权/漏审批调用 |
| Tool Valid Rate | 工具名、参数和 schema 是否合法 |
| Recovery Rate | timeout/crash 后能否恢复 |
| Context Invariant | compaction/replay 后关键约束是否仍存在 |
| Fallback Rate | 进入 heuristic/degraded 的比例 |
| Step / Token / Cost | 完成任务的轨迹效率 |
| P50/P95 Latency | 延迟分布 |

第一周可用 10～20 条确定性 task fixture，不依赖真实网络和 RAG：读取文件、搜索代码、运行测试、调用 PaperAgent capability、越权写入拒绝、超时恢复、上下文压缩恢复。

核心借鉴 τ-bench：**优先评最终状态，不强制 Agent 复现唯一工具轨迹**。工具轨迹只做诊断指标；除非任务确实只有唯一合法路径，不要把“跟 gold action 一样”当成正确性。

### 8.2 RAG Track（可延期或拆成独立项目）

如果已有链路能稳定运行，就保留下面的分层指标；如果不能，不阻塞 Agent Runtime MVP，也不要用 mock 高分包装完成。

#### Retrieval 层

| 指标 | 说明 | 一周目标 |
|---|---|---:|
| Recall@5 | Gold evidence 是否进入 Top-5 | 后续 |
| MRR | 第一个正确结果的位置 | 后续 |
| nDCG@10 | 多级相关性排序质量 | 后续 |
| Source Coverage | paper/dataset/repo 是否缺类 | 后续 |
| Duplicate Rate | 去重前后重复比例 | 后续 |

#### Generation / Grounding 层

| 指标 | 说明 | 一周目标 |
|---|---|---:|
| Citation Validity | 引用 chunk 是否真实存在 | 后续 |
| Citation Precision | 被引用内容是否支持 claim | 后续人工小样本 |
| Answer Relevance | 是否回答问题 | 后续 LLM judge + 人工校准 |
| Abstain Accuracy/F1 | 无证据时是否正确拒答 | 后续 |
| Hallucination Rate | 无来源事实占比 | 后续 |

### 8.3 Dataset 规划

一周版准备 10～20 条 Agent fixture：

- 4 条 read/search/run-test 正常任务；
- 3 条权限拒绝任务；
- 3 条 timeout/坏 JSON/工具失败；
- 3 条 compaction/replay；
- 2～5 条 PaperAgent domain smoke。

每条 case 标注：允许工具、禁止动作、期望最终状态、必须保留的上下文 invariant。RAG gold set 另行维护，不与 Agent fixture 强绑定。

---

## 9. 数据库最小方案

一周内继续使用 SQLite，不要为了简历强上 PostgreSQL、Redis、Qdrant。

建议最小表：

```text
sessions(id, profile, status, created_at, context_version)
events(id, session_id, seq, type, payload_json, created_at)
tool_calls(id, session_id, tool, args_hash, decision, status, latency_ms)
memory_snapshots(id, session_id, first_kept_event_id, summary, token_count)
eval_runs(id, git_commit, fixture_version, config_json, created_at)
eval_results(id, eval_run_id, case_id, metrics_json, trace_id)
feedback(id, artifact_id, rating, reason, created_at)
```

使用 schema migration（最小可用 `PRAGMA user_version` 或 Alembic），repository interface 隔离业务逻辑。向量索引仍可单独存文件；月度版再根据真实规模决定是否引入 LanceDB/Qdrant。

---

## 10. 一周 MVP 排程

### Day 1：冻结事实与故事主线

- 建立 active test 清单，修复/记录 Windows `tmp_path` 可复现问题；
- 冻结 10～20 条 Agent fixture；
- 定义 3 个现场 Demo 场景和 expected state；
- 精读 PocketFlow `pocketflow/__init__.py`，写一份带注释的 100 行核心理解；
- 决定依赖方式：MVP 优先显式依赖包；若复制/改写核心则保留 MIT attribution；
- 新增 ADR：Runtime layer 的边界，声明 ACP 不是 MCP、policy 不是 sandbox。

**交付**：OnePager 草稿 + fixture schema + 架构图。

### Day 2：AgentLoop + ToolRegistry

- 用 PocketFlow Node/Flow 实现最小 model/tool loop，限制最大 steps、tokens、tool calls；
- 节点先固定为 `Load/Compact/Decide/Policy/Execute/Verify/Persist/Done`；
- `patch_file` 等复合操作使用 Flow-is-Node subflow，不把所有逻辑塞进一个节点；
- 包装 4 个只读工具和 3～4 个 PaperAgent 工具；
- 所有调用统一 schema、timeout、错误结构和 trace。

**交付**：一个 CLI 命令能跑 research task 并输出 trajectory。

### Day 3：PolicyEngine

- risk、scope、workspace、network、mutates_state 元数据；
- `allow / ask / deny`；
- 越权、路径穿越、SSRF、secret redaction 测试；
- coding profile 保持 read-only。

**交付**：能现场演示“同一工具为何允许/拒绝”。

### Day 4：Context + Session

- transcript 持久化；
- token budget、recent window、pinned evidence；
- compaction snapshot；
- replay 后 invariant 一致。

**交付**：长对话压缩前后，引用、用户约束和 modified files 不丢。

### Day 5：QueryEngine Facade + Domain 接入

- 统一现有 QueryEngine facade；
- 把现有 PaperAgent research flow 包成一个 domain capability；
- 加一个 `coding_readonly` profile，证明 runtime 可复用；
- 现有 RAG 能跑则作为可选工具，不能跑则返回明确 degraded reason；
- 不新增向量库、reranker 或 GraphRAG。

**交付**：同一 runtime 可跑两个 profile，且工具/policy/context 复用。

### Day 6：Outcome Eval + Failure Injection

- final-state evaluator；
- 429、timeout、坏 JSON、假引用、worker crash；
- Eval 结果写 SQLite；
- 生成 task success、policy compliance、recovery、context invariant 和一页失败分类。

**交付**：一次命令复跑评估，结果带 commit/config/trace。

### Day 7：Demo 与校招材料

- 只选一个真实科研题目 + 一个 coding_readonly 任务；
- 录制或固化 3～5 分钟演示路径；
- 更新 OnePager、真实架构图、Known Limitations；
- 准备 2 分钟项目介绍、5 个失败案例、10 个深挖问题提纲；
- 无论剩余多少都打 `mvp-v0` 标记，未完成项明确列出。

**MVP 完成定义**：

```text
一条任务可运行；工具有 policy；上下文可压缩和恢复；
RAG 有 gold set 和真实指标；结果可复跑；失败可解释；
文档只描述真实实现。
```

---

## 11. 一个月 Roadmap

### Week 1：PocketFlow-based Runtime MVP

完成上一节，不追求 UI 华丽度。

### Week 2：Coding Agent 可用性与数据层

- coding tools 的只读链路和受控 patch；
- checkpoint/undo 与幂等 tool call；
- 20～30 条 Agent fixture 和 holdout；
- SQLite migration 与 artifact/version 管理；
- baseline regression CI。

### Week 3：安全执行与可观测性

- `apply_patch` 受控写工具；
- workspace path boundary；
- command allowlist、timeout、输出截断；
- diff review + user approval；
- Docker/WSL sandbox 作为可选 executor；
- crash resume 和幂等 tool call。

### Week 4：协议、可观测性与作品化

- MCP adapter（复用 ToolRegistry/PolicyEngine）；
- trace_id/span_id、timeline、cost/latency dashboard；
- baseline vs candidate 对比页；
- 一键 Demo、Runbook、架构 ADR、Failure Book；
- 简历 bullets、项目讲稿、面试追问卡片；
- 可选把 runtime 抽为独立 package/CLI。
- 输出一页 `PocketFlow vs LangGraph` 取舍说明：轻量动态 agent loop 使用 PocketFlow，复杂持久状态 workflow 保留 LangGraph。

### 可选独立 Track：RAG Eval Lab

如果一个月后仍有精力，再单独做：BM25 + Dense + RRF、reranker ablation、Recall/MRR/nDCG、citation support、abstain、latency/cost。它可以复用 Runtime 的 ToolRegistry、TraceStore 和 EvalRunner，但单独维护数据集与项目叙事。

---

## 12. 学习顺序

按“实现一个概念，马上用项目验证”推进：

1. **PocketFlow Core**：读懂约 100 行 `Node/Flow/Batch/Async`，自己画出 action routing；
2. **Agent Loop / Function Calling**：用 Flow 亲手搭 `decide -> tool -> observe -> verify`；
3. **Context Engineering**：token budget、compaction、transcript、replay；
4. **Tool Safety**：schema、idempotency、permission、sandbox 边界；
5. **Agent Evaluation**：outcome/state evaluator、policy compliance、recovery、pass^k；
6. **Information Retrieval（可延期）**：TF-IDF/BM25、dense embedding、RRF、rerank；
7. **Database**：SQLite transaction、migration、repository、event log；
8. **Reliability**：timeout/retry/backoff/circuit breaker/cancel/resume；
9. **Protocol**：最后学 MCP，不把协议接通当成 Agent 能力本身。

建议每天 40% 学习、50% 实现、10% 写复盘。学习笔记必须对应代码、测试或指标，避免只做资料收藏。

---

## 13. 面试叙事方向

### 30 秒

> 我做的不是单纯 LangGraph 流程，而是以 PocketFlow 的极简 Node/Flow 为控制内核，构建了一个 Research/Coding Agent Harness。我补齐了框架未提供的上下文压缩、工具权限、Session、Trace、任务恢复和结果评估；原有 PaperAgent/LangGraph 研究流程只是首个可插拔 domain。

### 2 分钟应讲清

1. 为什么 LangGraph 不足以代表 Agent 工程能力；
2. 为什么轻量动态 loop 选择 PocketFlow，而复杂科研 workflow 保留 LangGraph；
3. 为什么抽 AgentLoop/Context/Policy/Tool/Eval 五个核心模块；
4. 为什么评最终状态而不是强制唯一工具轨迹；
5. 一次真实失败如何通过 trace 定位并修复；
6. 指标提升是多少、代价是多少、哪些仍未解决。

### 面试题暂不展开，但开发时必须留下证据

- Function Calling 与 MCP 的区别；
- checkpoint、transcript、memory、context compaction 的区别；
- permission、project trust、sandbox 的区别；
- 为什么 RAG 需要 Hybrid/Rerank，如何证明有效；
- LLM-as-a-judge 的偏差如何校准；
- 如何防 prompt injection 和工具越权；
- 为什么不用复杂 Multi-Agent；
- PocketFlow 的 shared store 有什么问题，如何避免状态污染；
- Flow-is-Node 与普通函数调用相比有什么价值；
- PocketFlow 和 LangGraph 的边界如何划分；
- crash、重复请求、429、半完成写操作如何恢复；
- SQLite 何时不够，什么时候换 PostgreSQL/向量库；
- 如何控制 token、延迟和外部 API 成本。

---

## 14. 明确不做

一周内不做：

- 为了名字好听重写整个项目为 Multi-Agent；
- 同时接多个向量数据库；
- GraphRAG、知识图谱、微调、RL 一起上；
- 无真实调用的 MCP mock 当作完成；
- 自动执行任意 shell/删除/网络写操作；
- 只用 LLM judge、没有 gold label 的“高分评估”；
- 为追求全绿删除失败样本；
- 在未冻结当前脏工作区前大规模重构。

---

## 15. 最终优先级

```text
P0：PocketFlow-based Agent Loop + Agent fixture + Tool Policy + Trace
P0：Context budget/compaction/replay + SQLite EvalRun
P1：coding_readonly profile + checkpoint/undo
P1：Failure injection + cost/latency dashboard
P2：MCP adapter + sandbox executor + controlled apply_patch
P2：独立 CLI/package 与更完整 Interview Mode
P3：独立 RAG Eval Lab（BM25/Dense/RRF/reranker/grounding）
```

如果时间只够做三件事，选择：

1. 真实 Eval 数据集和 baseline；
2. 统一 ToolRegistry/PolicyEngine；
3. Context compaction + replay。

这三项最能把项目从“会用框架”提升到“理解并实现 Agent 系统”。
