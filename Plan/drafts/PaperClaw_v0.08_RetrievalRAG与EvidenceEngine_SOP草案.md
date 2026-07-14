# PaperClaw v0.08：Retrieval、RAG 与 Evidence Engine SOP 草案

> 状态：SOP 草案，待 v0.07 Trace / Eval 稳定后冻结  
> 目标：建立 Evidence Gap 驱动、可并发、可降级、可评估的 RetrievalEngine，并将检索结果推进为可追溯 Evidence，而不是直接塞给模型

> 执行前参考：[`PaperClaw_参考项目与可复用模块索引.md`](../../docs/reference/PaperClaw_参考项目与可复用模块索引.md) 中 PaperAgent Retrieval、AutoResearchClaw literature 和 Trace / Eval 清单。

## 目录

- [定位、Gate 与技术路径](#1-定位与命名)
- [数据契约与 Evidence 状态机](#4-核心数据契约)
- [摄取、查询与安全](#6-ingestion--chunking)
- [Eval、遗漏、风险与降级](#9-eval-设计)
- [实施阶段、Gate 与交付](#11-初步实施阶段)

## 1. 定位与命名

必须保持：

```text
QueryEngine       会话级 Agent 编排
QueryCompiler     Evidence Gap → backend query
RetrievalEngine   执行 sparse / dense / online retrieval
EvidenceEngine    identity、版本、去重、核验、Claim 状态
ContextBuilder    决定哪些 Evidence 进入模型
```

本版本不是“接一个向量库”，而是：

```text
Research Intent
→ Evidence Gap
→ QueryCompiler
→ RetrievalEngine
→ Resolve / Canonicalize / Verify
→ Rank / Rerank
→ EvidenceRecord
→ Context Candidate
```

## 2. 前置 Gate

- v0.04 已有 SQLite migration、ContextItem 和 Session；
- v0.05 已有 Harness、Budget、Permission、async adapter；
- v0.07 已有 EventEnvelope、TraceStore、EvalDataset 和 Replay；
- Offline 模式能强制网络调用为 0；
- 外部文本已按不可信 data 进入 Context；
- Secret 和远程请求 Trace 有 redaction。

## 3. 技术路径比较

| 路径 | 优点 | 缺点 | 决策 |
|---|---|---|---|
| SQLite FTS5 / BM25 only | 零服务、轻量、可解释 | 语义召回有限 | 必做 baseline |
| Dense only | 语义召回好 | 模型/索引版本、成本、误召回 | 不作为唯一检索 |
| BM25 + Dense + RRF | 稳健、易做 ablation | 多一路索引与配置 | MVP 推荐目标 |
| Hybrid + CrossEncoder | 排序质量更好 | latency、OOM、模型依赖 | optional adapter |
| 独立 Vector DB | 可扩展 | 运维与依赖过重 | 一月 MVP 延后 |

### 推荐选型

- Metadata / cache / document registry：SQLite；
- Sparse：SQLite FTS5，使用 `bm25()` baseline；
- Dense：`EmbeddingProvider` + `VectorIndex` Protocol；小数据可用内存矩阵或可选 FAISS，不提前绑定；
- Fusion：Reciprocal Rank Fusion（RRF）；
- Rerank：可选 CrossEncoder adapter；
- Online backend：Crossref、Semantic Scholar、arXiv、GitHub 等独立 async adapter；
- 并发：`asyncio.gather` + per-source `Semaphore` + retry-after / exponential backoff；
- Schema：沿用 typed dataclass / validator；若外部 API 边界复杂，再评估 Pydantic optional dependency。

## 4. 核心数据契约

```text
RetrievalIntent
EvidenceGap
QuerySpec
BackendQuery
RawHit
ScholarlyWorkIdentity
DocumentVersion
SourceArtifact
Chunk
RetrievalCandidate
RankedResult
EvidenceRecord
CitationAnchor
RetrievalRun
IndexManifest
```

关键字段：

```text
raw_topic
gap_id
query_id / rewrite_of
backend / backend_query
canonical_id / version_id
content_hash / index_version
rank / sparse_score / dense_score / rerank_score
source_url / accessed_at
trust / verification_status
exact_locator
trace_id
```

`raw_topic` 永久保留，任何 rewrite 都作为新 QuerySpec，不覆盖原始输入。

## 5. Evidence 状态机

```text
candidate
→ identity_resolved
→ metadata_verified
→ source_accessed
→ claim_extracted
→ claim_supported | claim_conflicted | rejected
```

必须区分：

- 论文身份真实；
- PDF / 网页已访问；
- 某段 Claim 已提取；
- Claim 被来源支持；
- Claim 适用于当前任务。

`metadata_verified` 绝不等于论文中所有方法和实验都已验证。

## 6. Ingestion / Chunking

每个 Chunk 必须绑定：

- canonical document + version；
- source artifact hash；
- 页码、章节、表格或代码位置；
- parser / OCR version；
- chunking config；
- content hash；
- access / license metadata。

风险：

- preprint 与正式版重复；
- correction / erratum / retraction；
- PDF 扫描、加密、双栏、公式和表格解析；
- Repo main 与论文 commit 不一致；
- 网页内容改变而缓存仍旧。

预案：DocumentVersionRelation、immutable artifact、parser failure 状态、metadata-only 降级，不允许模型补写缺失正文。

## 7. QueryCompiler

模型只提供结构化意图：

```json
{
  "gap_id": "gap-12",
  "lane": "counter_evidence",
  "task_atoms": ["concrete crack segmentation", "small dataset"],
  "constraints": ["pixel-level"],
  "exclude_terms": ["YOLO"]
}
```

QueryCompiler 负责：

- backend syntax；
- phrase / boolean / field query；
- 中英文同义词；
- 无锚点查询；
- query provenance；
- placeholder 和空 query 拒绝；
- rewrite budget；
- Query 与 Evidence Gap success condition 对齐。

## 8. Security / Permission

- PDF、README、网页、Repo 和检索摘要一律是不可信 data；
- 检索内容中的“忽略指令”“执行命令”不得进入 system instruction；
- URL fetch 需 scheme、host、IP、redirect 和大小限制，防 SSRF；
- 下载文件进入隔离 cache，不直接执行；
- Repo / Dataset 下载与代码执行是两个不同 Permission；
- API Key 不进入 query/event/cache；
- License 和 robots / provider terms 记录到 SourceArtifact；
- Online / cache-first / offline 模式由 Harness 强制。

## 9. Eval 设计

### Retrieval

```text
Recall@k
Precision@k
Hit Rate@k
MRR
nDCG@k
Duplicate Rate
Source Coverage
Counter-evidence Coverage
Empty Result Rate
Latency / Cost
```

### QueryCompiler

```text
raw_topic preservation
placeholder query rate
query drift rate
backend syntax validity
gap alignment
lane coverage
```

### Grounding

```text
Faithfulness
Citation Correctness
Citation Completeness
Claim–Evidence Alignment
Unsupported Claim Rate
Abstention Accuracy
```

评估集采用 graded relevance，并标注 supporting、competing、counter-evidence、resource、duplicate、invalid、lexically-similar-but-misleading。

## 10. 用户尚未覆盖的关键问题、风险推演与降级

```text
Hybrid + Reranker
→ BM25 + Dense + RRF
→ BM25
→ verified cache
→ metadata-only candidate
→ blocked / unresolved
```

降级不能提升 Evidence 状态。

| 故障 | 预案 |
|---|---|
| 429 / timeout | per-source retry/backoff，其他 source 继续 |
| Dense model 不可用 | BM25 baseline |
| Reranker OOM | 跳过 rerank并记录 degraded |
| SQLite/index 损坏 | integrity check、rebuild from immutable documents |
| PDF parse 失败 | metadata-only / OCR optional，不生成正文 Claim |
| DOI 指向错误标题 | identity conflict，拒绝 verified |
| 高相关但不回答 Gap | Gap-aware evaluator 降分 |
| 缓存过期且离线 | stale 标记，不假装 fresh |
| Prompt injection | data boundary + injection fixture |

## 11. 初步实施阶段

1. Evidence / Document / Query / Index Schema；
2. SQLite registry、FTS5 baseline 和 IndexManifest；
3. QueryCompiler 与 Offline fixture；
4. Async backend adapters、cache、dedup；
5. Dense / RRF / optional reranker；
6. Evidence Resolver / Verifier / CitationAnchor；
7. Retrieval + Grounding Eval；
8. 故障注入、性能和消融。

## 12. GO / 降级 / NO-GO

- `GO`：query provenance 100%、假身份不进 verified、每个 Context chunk 可回溯、Hybrid 有公平对照。
- `降级`：Dense/Reranker 延后，以 FTS5/BM25 + online metadata adapter 交付。
- `NO-GO`：检索结果直接升级 Evidence、Offline 仍联网、全文不可用却生成细节、Prompt injection 能提升权限。

## 13. 预期交付

```text
artifacts/v0_08/
├── retrieval_contract.md
├── evidence_state_machine.md
├── index_manifest.json
├── query_eval.json
├── retrieval_ablation.md
├── grounding_eval.md
├── failure_injection.md
└── implementation_summary.md
```

## 14. 明确延期

- 大规模 Vector DB；
- Knowledge Graph；
- 自动执行下载 Repo；
- 生产爬虫；
- 全学科 tokenizer / ontology；
- 未经许可的全文下载；
- 将 heuristic novelty score 当最终创新结论。

## 15. 参考

- [SQLite FTS5 官方文档](https://sqlite.org/fts5.html)
- [`PaperClaw_QueryEngine设计讨论稿.md`](../../docs/desgin/PaperClaw_QueryEngine设计讨论稿.md)
- [`PaperClaw_v0.07_TraceReplay与分层Eval_SOP草案.md`](PaperClaw_v0.07_TraceReplay与分层Eval_SOP草案.md)
- [`PaperClaw_参考项目与可复用模块索引.md`](../../docs/reference/PaperClaw_参考项目与可复用模块索引.md)
