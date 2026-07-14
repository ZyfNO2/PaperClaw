# PaperClaw v0.07：Trace、Replay 与分层 Eval SOP 草案

> 状态：SOP 草案，待 v0.05 Harness 事件契约稳定后冻结  
> 性质：横切 v0.02–v0.06 及后续 SeededResearch 的基础能力  
> 目标：建立内部可重放 Trace，以 LangSmith 作为可选观测 adapter，并分别评估 Agent、RAG、Context、MultiAgent 和工程成本

> 执行前参考：[`PaperClaw_参考项目与可复用模块索引.md`](../../docs/reference/PaperClaw_参考项目与可复用模块索引.md) 中 Trace / Eval 清单，重点阅读 AutoResearchClaw ARC-Bench / assessor、academic-research-skills `evals/` 和 Draftpaper-loop Claim / Citation Evidence。

## 目录

- [Trace 分层与 LangSmith 定位](#1-核心结论)
- [Eval 分层与评估对象](#4-eval-总体分层)
- [数据模型、版本接入与演示](#11-eval-数据模型草稿)
- [契约、技术选型与遗漏](#16-trace-契约补充)
- [风险、实施阶段与 Gate](#19-风险推演与预案)
- [交付与参考](#22-预期交付)

## 1. 核心结论

Trace 和 Eval 不能等到项目最后再补。

```text
Trace 回答：系统实际发生了什么？
Eval 回答：发生得是否正确、稳定、高效？
```

推荐架构：

```text
PaperClaw Runtime Event
        ↓
Internal TraceStore（事实源）
        ├── Offline Replay
        ├── EvalRunner
        ├── 本地 JSON / SQLite
        └── LangSmith Adapter（可选）
```

原则：

- PaperClaw 内部 Trace Schema 是事实源；
- LangSmith 用于可视化、过滤、比较、数据集和评估，不成为 Runtime 硬依赖；
- LangSmith 不可用时，Agent Loop、Verify、Replay 和本地 Eval 仍能运行；
- 测试负责硬正确性，Eval 负责质量度量和版本比较；
- 优先使用确定性 Code evaluator，再以 Human 和 LLM-as-judge 补充主观指标；
- Agent Eval 与 RAG Eval 分开建模，最终通过同一个 EvalRun 汇总。

---

## 2. Trace 分层

### 2.1 Trace / Span / Event

```text
Trace
    一次完整 AgentRun 或用户任务

Span
    Trace 中一个有持续时间的操作，如模型调用、工具执行、检索、验证

Event
    某个瞬时状态变化，如 permission.denied、context.compacted
```

建议层级：

```text
conversation / thread
  └── agent_run trace
        ├── context.build span
        ├── model.call span
        ├── tool.execute span
        ├── verification span
        ├── reflection span
        ├── agent.worker span
        ├── retrieval span
        └── finalization span
```

### 2.2 Span 类型

```text
agent
model
tool
shell_task
permission
context
retrieval
rerank
verification
reflection
multiagent_task
review
eval
```

### 2.3 最小字段

```python
@dataclass
class TraceSpan:
    trace_id: str
    span_id: str
    parent_span_id: str | None
    conversation_id: str
    run_id: str

    span_type: str
    name: str
    sequence: int

    started_at: datetime
    ended_at: datetime | None
    status: str

    inputs: dict
    outputs: dict
    error: dict | None
    attributes: dict
```

`attributes` 至少逐步覆盖：

```text
agent_id / task_id / role
provider / model / prompt_version
tool_name / command_class
permission_decision
context_snapshot_id / token_count
retrieval_backend / query_id / top_k
verification_status / reflection_decision
latency_ms / input_tokens / output_tokens / cost
git_commit / config_hash / fixture_version
```

### 2.4 Trace 安全

- `.env`、API Key、Token 和 Cookie 不进入 Trace；
- 文件和工具大输出默认摘要化或引用化；
- Sensitive ContextItem 按策略脱敏；
- LangSmith 上传前进行第二次过滤；
- Offline 模式禁止远程 Trace Export；
- Trace 失败不能阻塞核心 Agent Loop；
- Export 采用异步缓冲并有本地 fallback。

---

## 3. LangSmith 集成定位

LangSmith 当前官方能力覆盖 Trace 查看与比较、性能监控、告警、自动化、用户反馈、数据集、离线评估和在线评估。

PaperClaw 只通过 adapter 接入：

```python
class TraceExporter(Protocol):
    async def export_span(self, span: TraceSpan) -> None: ...
    async def flush(self) -> None: ...
```

候选实现：

```text
JsonTraceExporter
SQLiteTraceExporter
LangSmithTraceExporter
CompositeTraceExporter
```

LangSmith Adapter 负责：

- 将 `conversation_id` 映射为 thread；
- 将 AgentRun 映射为 root run / trace；
- 将模型、工具、检索、Verify 和 Worker 映射为 child runs；
- 上传 tag、metadata、latency、tokens 和 feedback；
- 将标注或线上坏例导出为本地 Eval Dataset 候选。

LangSmith Adapter 不负责：

- 决定 Agent 是否继续；
- 保存唯一 Session 状态；
- 代替 Permission；
- 代替本地 Trace；
- 代替 Verify；
- 在 Offline Replay 中联网。

---

## 4. Eval 总体分层

```text
L0 Contract / Test Eval
    Schema、权限、路径、超时、确定性正确性

L1 Component Eval
    Model、Tool、QueryCompiler、Retriever、Reranker、Context

L2 Agent Trajectory Eval
    工具选择、参数、恢复、策略遵循、成本

L3 Outcome / Final-State Eval
    任务最终状态是否满足用户目标

L4 Conversation / System Eval
    多轮一致性、恢复、MultiAgent、用户体验

L5 Domain Eval
    SeededResearch、论文核验、Evidence、Tailor、Review
```

评估不能只给一个总分。每层需要独立指标和失败类型，否则无法定位问题来自检索、Context、工具还是最终回答。

---

## 5. Offline 与 Online Eval

### 5.1 Offline Eval

用于开发阶段：

- 单元评估；
- 回归测试；
- Prompt / Model / Tool 版本对比；
- 历史 Trace 回放；
- 成本和延迟 Benchmark；
- 故障注入。

目标对象：

```text
Dataset
  └── Example
        ├── input
        ├── reference_output（可选）
        ├── acceptance_criteria
        └── metadata
```

每个关键组件先人工整理约 5–10 个高质量案例，再逐渐吸收真实失败 Trace。

### 5.2 Online Eval

后续用于真实 Runs / Threads：

- 异常和失败监控；
- Permission violation；
- 高成本或高延迟任务；
- 用户取消和负反馈；
- 无法恢复的工具错误；
- 检索空结果或 Citation 缺失；
- Session / Conversation 级质量。

Online Eval 没有 reference output，主要使用安全规则、异常检测、Human feedback 和 reference-free evaluator。

### 5.3 闭环

```text
线上坏 Trace
    ↓
人工或规则筛选
    ↓
转为 Offline Example
    ↓
修复并运行回归实验
    ↓
新版本上线观察
```

---

## 6. Evaluator 类型

### 6.1 Code Evaluator

优先使用，适合：

- JSON / Schema 合法；
- 文件是否创建；
- 测试是否通过；
- Tool 参数是否正确；
- Permission 是否越权；
- Citation ID 是否存在；
- Context 是否保留 required constraint；
- Offline 模式是否发生联网；
- 假论文是否泄漏进最终引用。

### 6.2 Human Evaluator

用于：

- Task 拆解是否合理；
- 回答是否真正解决用户问题；
- 科研故事是否清楚但不过度；
- Reviewer Finding 是否有价值；
- TUI 是否易于理解和控制。

### 6.3 LLM-as-Judge

只用于难以完全规则化的维度：

- 回答相关性；
- 解释清晰度；
- 研究方案完整性；
- Claim 与 Evidence 的语义对齐；
- Review 是否覆盖主要风险。

约束：

- Judge Prompt 版本化；
- 优先 few-shot rubric；
- 重要结论抽样人工复核；
- Judge 不能覆盖确定性失败；
- 不让被评 Agent 给自己评分。

### 6.4 Pairwise Eval

用于比较：

- Prompt vA vs vB；
- ReAct vs ReAct + Reflection；
- 单 Agent vs MultiAgent；
- 不同 Context Compaction；
- BM25 vs Dense vs Hybrid；
- 不同模型或预算。

当绝对评分困难时，Pairwise 往往比单独打分更稳定。

---

## 7. Agent Eval

### 7.1 Outcome 指标

- Task Success Rate；
- Final-State Correctness；
- Required Claim Coverage；
- Verified Completion Rate；
- False Completion Rate；
- Recovery Success；
- `pass@k` / `pass^k`；
- Blocked 状态判断准确率。

`pass@k` 可描述多次尝试中至少一次成功的能力；`pass^k` 更强调连续多次都成功的稳定性。两者不能混用。

### 7.2 Trajectory 指标

- Tool Selection Accuracy；
- Tool Argument Validity；
- Invalid Action Rate；
- Redundant Tool Call Rate；
- Read-before-Write Compliance；
- Verification-after-Write Compliance；
- Permission Violation Rate；
- Repeated Failure Rate；
- Step Efficiency；
- Trajectory Edit Distance（仅用于诊断，不强制唯一 gold path）。

Agent 最终状态正确时，不应仅因工具顺序不同判失败；轨迹指标主要用于定位效率、安全和策略问题。

### 7.3 成本与工程指标

- 总模型调用数；
- input / output tokens；
- Tool 调用数；
- wall time；
- cost；
- retry / fallback 次数；
- Context token utilization；
- Trace export failure rate；
- cancellation latency。

---

## 8. RAG Eval

RAG Eval 必须拆成 Retrieval 和 Generation 两段。

### 8.1 Retrieval Eval

- Recall@k；
- Precision@k；
- Hit Rate@k；
- MRR；
- nDCG@k；
- MAP（数据规模允许时）；
- Source Coverage；
- Duplicate Rate；
- Diversity；
- Freshness；
- Counter-evidence Coverage；
- Empty Result Rate；
- Retrieval Latency / Cost。

对于 SeededResearch，还要评估：

- 真论文解析率；
- 错误 DOI 拒绝率；
- Seed Role Accuracy；
- Competing Baseline Coverage；
- Repo / Dataset Link Validity；
- Evidence Gap Satisfaction Rate；
- 假论文引用泄漏率。

### 8.2 Generation / Grounding Eval

- Answer Relevance；
- Faithfulness / Groundedness；
- Citation Correctness；
- Citation Completeness；
- Claim–Evidence Alignment；
- Unsupported Claim Rate；
- Conflict Disclosure；
- Abstention Accuracy；
- Context Utilization；
- Source Attribution Accuracy。

### 8.3 QueryCompiler Eval

- 原始 `raw_topic` 保持；
- Query 与 Evidence Gap 对齐；
- Placeholder Query Rate；
- Query Drift Rate；
- Backend Syntax Validity；
- 无锚点查询覆盖；
- 竞争与反证 Lane 覆盖；
- Query Rewrite Success。

### 8.4 RAG 实验矩阵

后续至少对照：

```text
BM25
Dense Retrieval
BM25 + Dense
RRF Fusion
Hybrid + Reranker
```

每个配置记录同一 Dataset version、top-k、reranker、embedding、chunking、模型、成本和 Trace。

---

## 9. Context Eval

- Constraint Retention；
- Context Precision；
- Context Recall；
- Compaction Drift；
- Stale Memory Rate；
- Relevant Memory Hit Rate；
- Context Token Efficiency；
- Source Traceability；
- Role Context Leakage；
- Task State Recovery Success；
- 多次压缩后的事实一致性。

Context Eval 回答“最终给模型看了什么，以及是否充分”；RAG Eval 回答“检索取回了什么”。两者不能合并成一个 Groundedness 分数。

---

## 10. MultiAgent Eval

- Task Decomposition Validity；
- DAG Validity；
- Parallelizable Task Detection；
- Duplicate Work Rate；
- File Conflict Rate；
- Scope Violation Rate；
- Coordination Overhead；
- Worker Local Success；
- Global Integration Success；
- Reviewer Catch Rate；
- Reviewer False Positive Rate；
- Fix-Review Convergence；
- 单 Agent / MultiAgent 成本收益比。

多 Agent 不能仅以“用了几个 Agent”作为能力指标。必须证明拆分带来速度、质量、覆盖或稳定性收益。

---

## 11. Eval 数据模型草稿

首批 Agent repair Dataset 采用 [`PaperClaw_跨领域修复型测试题集_v0.01.md`](../testsets/PaperClaw_跨领域修复型测试题集_v0.01.md)：图像识别、大语言模型、三维重建各 1 题。v0.07 负责将其从设计稿升级为版本化 fixture，并记录 seed hash、private verifier、独立 run、`pass@k` / `pass^k` 与完整 Trace。

```python
@dataclass
class EvalExample:
    example_id: str
    inputs: dict
    reference_outputs: dict | None
    acceptance_criteria: list[str]
    metadata: dict
    split: str
    dataset_version: str

@dataclass
class EvalRun:
    eval_run_id: str
    dataset_id: str
    dataset_version: str
    git_commit: str
    config_hash: str
    model_config: dict
    started_at: datetime

@dataclass
class EvalResult:
    eval_run_id: str
    example_id: str
    trace_id: str
    metrics: dict
    feedback: list[dict]
    failure_type: str | None
```

每次实验必须能够回答：

- 用了哪个代码 commit；
- 哪个 Dataset version；
- 哪个 Prompt / Tool / Model 配置；
- 对应哪条 Trace；
- 哪些 evaluator；
- 结果为何变化。

---

## 12. 分版本接入草稿

### v0.02 Verify / Reflection

- Verify / Reflection 最小事件；
- Verification Evidence；
- False Completion、Repair Success、Reflection Limit 指标。

### v0.03 MultiAgent

- agent_id / task_id / parent-child span；
- Task DAG Trace；
- Worker / Reviewer Eval。

### v0.04 Context Engineering

- ContextSnapshot span；
- token composition；
- Compaction Eval；
- Session Resume Eval。

### v0.05 Harness Engineering

- 正式 TraceStore / EventBus；
- LangSmith Adapter；
- EvalRunner；
- Offline Replay；
- Dataset / Experiment 版本化；
- Agent、Tool、Permission 和成本 Dashboard 数据。

### v0.06 Claw 交互层

- Trace Panel；
- Eval 结果查看；
- 用户反馈；
- 失败 Trace 导出；
- LangSmith deep link（可选）。

### SeededResearch

- QueryCompiler / Retrieval / Rerank / Grounding Span；
- RAG Eval；
- Seed Audit、Evidence Gap、Claim–Evidence 和 Academic Review Eval。

---

## 13. 最小演示方向

1. 对同一 fixture 运行 ReAct 和 ReAct + Reflection；
2. 本地 Trace 展示每次模型、工具、Verify 和 Reflection；
3. 将同一 Trace 可选导出 LangSmith；
4. 比较 Task Success、False Completion、步骤、token、成本和时延；
5. 对一个小型 RAG fixture 比较 BM25、Dense 和 Hybrid；
6. 展示 Recall@k、MRR、nDCG、Citation Correctness 和 Groundedness；
7. 从失败 Trace 一键生成新的 Offline Eval Example 草稿。

---

## 14. 草稿验收方向

- Trace 关闭或 LangSmith 不可用时核心 Runtime 正常运行；
- 每个 AgentRun 都有唯一 trace_id；
- Span parent-child 和 sequence 可重建执行顺序；
- Secret 不进入本地或远程 Trace；
- Offline Replay 不发生真实网络或模型调用；
- EvalRun 绑定 commit、配置、Dataset version 和 Trace；
- 确定性失败不能被 LLM Judge 覆盖；
- Agent、RAG、Context、MultiAgent 指标分层输出；
- 同一 fixture 可比较两个版本；
- 失败案例可以沉淀为回归数据。

---

## 15. 暂不设计

- LangSmith 具体 SDK 调用代码；
- 云端账号、Key 和费用配置；
- 生产告警阈值；
- 完整人工标注平台；
- 大规模 Benchmark 数据集；
- 最终 LLM Judge 模型；
- Dashboard UI；
- 数据保留和多租户策略。

等 v0.02/v0.03 产出真实 Trace 后，再根据事件形态和失败案例编写正式 Trace / Eval SOP。

## 16. Trace 契约补充

正式 v0.07 至少冻结：

```text
EventEnvelope
TraceManifest
SpanRecord
ArtifactRef
ContextSnapshotRef
RedactionRecord
ExportOutboxItem
ReplayManifest
```

EventEnvelope 必须补充：

- `schema_version`、`event_id`、幂等键；
- `operation_id` 与 `attempt`；
- `agent_id / task_id / parent_task_id`；
- monotonic duration 与 wall-clock timestamp 分离；
- `producer_version / runtime_version / config_hash`；
- 大对象只保存 content-addressed ArtifactRef；
- redaction policy/version；
- orphan span reconciliation。

### Replay 两种语义

- **Deterministic replay**：复用保存的模型响应和工具 Observation，只验证状态迁移、Reducer、UI 和 Eval；
- **Re-execution**：重新调用模型或工具，比较新版本行为，必须创建新 run_id。

禁止把 re-execution 宣称为严格可复现 Replay。

## 17. 技术选型草案

| 能力 | 推荐选型 | 边界 |
|---|---|---|
| 本地事实源 | SQLite append-only events + materialized views | Event 与 snapshot 同事务或 outbox |
| Span 语义 | 兼容 OpenTelemetry 的 trace/span/event/link 思路 | 不在 MVP 强制依赖 OTel SDK |
| 大对象 | SHA-256 ArtifactRef + retention | 不把大 Prompt/PDF/stdout 直接塞 Event |
| 远程观测 | LangSmith optional exporter | 远程失败不影响 Runtime |
| Eval | pytest/code evaluator 优先 | LLM Judge 不覆盖 hard failure |
| 数据集 | versioned JSONL/SQLite examples | git commit、config、prompt、index 全冻结 |
| 比较 | paired / pairwise | 同一 examples、同一预算 |

## 18. 用户尚未覆盖的问题

- Event 重复、乱序、缺失和 child-before-parent；
- Trace exporter 401/429/queue full；
- cancelled run 留下 orphan span；
- Eval 自己产生 Trace 后递归触发 Eval；
- Dataset、Index、Prompt、Judge 版本不一致却强行比较；
- Remote export 后用户删除本地 Session 的数据生命周期；
- Sampling 导致审计链缺失；
- LLM Judge 被评测输出 prompt-inject；
- 小数据集方差和过拟合；
- dirty worktree 实验不可复现。

## 19. 风险推演与预案

| 场景 | 预案 |
|---|---|
| 事件重复 / 乱序 | event_id dedup + per-trace sequence + upcaster |
| 进程在 Span 中崩溃 | 启动时将未闭合 Span 标记 interrupted/orphan |
| LangSmith 离线 | 本地 outbox；指数退避；不丢主 Trace |
| Secret 嵌套在 payload | EventBus 前中央 redactor + export 二次 redaction + canary test |
| Artifact 被删除 | Trace 标记 missing_artifact，不伪造内容 |
| Judge 非法 JSON | evaluator error，不给默认高分 |
| Dataset 与 index 不匹配 | 拒绝生成可比较结论 |
| Eval 只优化固定样例 | train/dev/test split + hidden fixture + historical failures |
| Trace 体积爆炸 | TTL、ArtifactRef、delta coalescing；本地 hard failure 不采样 |

## 20. 初步实施阶段

1. EventEnvelope/Span/Artifact v1 与 upcaster；
2. SQLite append-only TraceStore 和 outbox；
3. orphan reconciliation 与 deterministic replay；
4. LangSmith exporter 和 ID mapping；
5. EvalDataset/EvaluatorSpec/EvalRun/EvalResult；
6. Agent、Context、MultiAgent、成本分层指标；
7. failure injection 与 secret canary；
8. 失败 Trace → Offline Example 闭环。

## 21. GO / 降级 / NO-GO

- `GO`：本地 Trace 完整、Replay 状态一致、Eval 绑定版本、Exporter 可故障隔离。
- `降级`：LangSmith 延后；保留 JSON/SQLite Trace、pytest evaluator 和本地报告。
- `NO-GO`：Trace 关闭导致 Runtime 失败、Secret 进入 Trace、Replay 重放真实副作用、缺版本仍输出比较结论。

## 22. 预期交付

```text
artifacts/v0_07/
├── event_contract_v1.md
├── trace_schema.md
├── replay_report.md
├── eval_dataset_manifest.json
├── experiment_comparison.md
├── redaction_report.md
└── langsmith_export_report.md
```

---

## 23. 参考资料

- [LangSmith Observability 官方文档](https://docs.langchain.com/langsmith/observability)
- [LangSmith Evaluation Concepts 官方文档](https://docs.langchain.com/langsmith/evaluation-concepts)
- [`PaperClaw_v0.05_HarnessQueryEngine_SOP草案.md`](PaperClaw_v0.05_HarnessQueryEngine_SOP草案.md)
- [`PaperClaw_QueryEngine设计讨论稿.md`](../../docs/desgin/PaperClaw_QueryEngine设计讨论稿.md)
- [`PaperClaw_上下文系统与提示词工程骨架.md`](../../docs/desgin/PaperClaw_上下文系统与提示词工程骨架.md)

一句话总结：

> PaperClaw 先用内部 Trace 记录真实执行，再用分层 Eval 判断 Agent、RAG、Context 和 MultiAgent 是否正确、稳定且值得；LangSmith负责可选的观测、实验比较和反馈闭环，而不是替代本地 Runtime。
