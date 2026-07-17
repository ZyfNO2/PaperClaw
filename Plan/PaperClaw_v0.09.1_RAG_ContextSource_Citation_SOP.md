# PaperClaw v0.09.1 RAG ContextSource / Citation / Grounding SOP

> 状态：Implementation complete / repository CI pending  
> 分支：`feat/v0.09.1-rag-contextsource-citation`  
> 依赖：PR #24 BM25 / Incremental Retrieval、PR #25 Shared ContextSource Registry  
> 范围：Retrieval ContextSource、Context budget、CitationAnchor、abstention、Grounding Eval、injection fixture、offline demo。

## 1. 架构

```text
ContextRequest raw Agent prompt
→ extract [Task] / remove fixed stopwords
→ RetrievalRequest
→ SQLiteBM25Retriever
→ stale + exact duplicate filtering
→ RankedResult
→ CitationAnchor + external_untrusted ContextCandidate
→ ContextSourceRegistry
→ ContextOrchestrator budget/trust selection
→ PromptAssembler
```

RAG 模块不构造 Provider Prompt。

## 2. CitationAnchor

Anchor 绑定：

- Manifest ID / corpus hash；
- Chunk ID / Document ID / Version ID；
- canonical URI / display name；
- content hash；
- line / paragraph / fragment locator；
- stable anchor ID 与引用 label。

Citation 不允许只绑定文件名或自由文本片段。

## 3. Retrieval ContextSource

- 只消费 PR #24 的 active `RankedResult`；
- defensive 再次过滤 duplicate chunk/content；
- 每个结果转换为 `kind=evidence_ref`；
- trust 固定为 `external_untrusted`；
- bucket 固定为 `retrieval`；
- metadata 保存 Anchor、rank、BM25 score、Manifest/corpus；
- ContextOrchestrator 负责 quota 与最终 section。

## 4. Query extraction

只提取 Agent prompt 的 `[Task]` 区段，去除固定英语停用词和重复 token。避免 `[Tools]`、History、Runtime protocol 或 “what/is/the” 等通用词污染 BM25 和 no-answer 判断。

## 5. No-answer / abstention

以下情况生成本地 trusted/pinned grounding constraint：

- 结果少于 `min_candidates`；
- 唯一文档数不足；
- configured index error fail-closed。

Constraint 要求不编造 retrieval-backed facts/citations，并明确说明 indexed evidence unavailable。它仍以 `ContextCandidate` 形式交给 Orchestrator，不直接拼 Prompt。

## 6. Prompt injection containment

恶意文档指令：

- 保留为证据正文；
- 只进入 `UNTRUSTED DATA`；
- 不进入 `RUNTIME PROTOCOL`；
- 不升级为 constraint/system rule；
- Citation 可指向事实，但不能把文档命令变成 Runtime 指令。

## 7. Grounding Eval

显式离线标注：

- cited anchor IDs；
- supporting anchor IDs；
- answerable；
- abstained。

指标：

- Citation Correctness = 正确支持引用 / 所有引用；
- Unsupported Claim Rate = 实际作答但无正确支持的 Claim / 实际作答 Claim；
- Abstention Accuracy。

未知或伪造 Anchor 按错误引用处理。

## 8. Offline demo

`scripts/run_v0_09_1_rag_demo.py`：

- 固定本地 Markdown fixture；
- 增量索引；
- BM25 retrieval；
- ContextSource / ContextOrchestrator assembly；
- injection containment；
- CitationAnchor；
- label-based grounded answer；
- Grounding metrics；
- 可选 JSON artifact 输出。

无网络、无 Provider、无 LLM。

## 9. 明确非目标

- answer-generation model；
- semantic entailment model；
- Dense Retrieval / RRF / reranker；
- online search；
- PDF/OCR；
- automatic citation insertion into arbitrary model text；
- ContextOrchestrator 内部改写；
- direct Prompt construction。

## 10. GO / NO-GO

`GO`：Anchor 版本绑定、stale/duplicate filtering、budget integration、abstention、injection containment、Citation/Unsupported metrics、offline demo 和 full CI 全部通过。

`NO-GO`：文档命令进入 trusted Runtime section、无证据仍生成伪引用、Anchor 不绑定 Version/locator、RAG 模块直接拼 Prompt、或依赖/CI 未明确。
