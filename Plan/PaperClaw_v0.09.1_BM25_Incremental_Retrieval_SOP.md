# PaperClaw v0.09.1 BM25 / Incremental Retrieval SOP

> 状态：Implementation complete / repository CI pending  
> 分支：`feat/v0.09.1-bm25-incremental-retrieval`  
> Draft PR：`#24`  
> 前置：RAG Index Foundation PR #20 已合并  
> 范围：BM25 read-side、增量索引编排、失效过滤、完整性检查/重建、离线 Retrieval Eval。

## 1. 用户可见闭环

```text
local Markdown / text bytes
→ deterministic parse / chunk contracts from Phase A
→ incremental add | update | delete | noop
→ existing atomic SQLiteDocumentRegistry write path
→ ready IndexManifest
→ RetrievalRequest
→ FTS5 BM25 candidate pool
→ active Document / Version / Chunk validation
→ stale and exact-duplicate filtering
→ RankedResult
```

本 PR 不生成答案、不拼 Prompt、不接 ContextOrchestrator，也不引入 Dense Retrieval。

## 2. 冻结合同

- `RetrievalRequest`
- `RetrievalCandidate`
- `RankedResult`
- `IncrementalIndexResult`
- `IndexIntegrityReport`
- `IndexRebuildResult`
- `RetrievalJudgment`
- `RetrievalMetrics`

`RetrievalRequest` 可固定 `expected_manifest_id` 或 `expected_corpus_hash`。当前快照不匹配时抛出 `StaleIndexError`，不静默切换语料。

## 3. BM25 read-side

- 使用现有 SQLite FTS5 `chunk_fts`；
- query token 规范化、去重并安全引用；
- heading 权重 2.0，正文权重 1.0；
- `document_ids` 在 FTS 候选池限制之前生效；
- 排序 tie-breaker 为 `raw_rank → chunk_id → rowid`；
- `total_matches` 表示 scope 内原始 FTS 命中总数；
- 返回分数为 `max(0, -sqlite_bm25)`，仅用于当前查询内排序解释，不声明跨语料可比。

## 4. Stale invalidation 与 duplicate filtering

候选必须同时满足：

- FTS `chunk_id/document_id/version_id/text/heading` 与持久化 Chunk 完全一致；
- Chunk active；
- DocumentVersion active；
- Document 未删除。

任何残留、伪造或漂移 FTS row 都作为 stale 过滤。默认按 Chunk `content_hash` 删除完全相同内容；可通过请求关闭 exact duplicate filtering。

## 5. Incremental mutation

`IncrementalIndexer` 负责：

1. 选择 Phase A parser；
2. 创建稳定 Document/Artifact/Version/Chunk；
3. 判断 add / update / delete / unchanged noop；
4. 计算 mutation 后的 projected Manifest；
5. 将真实写入委托给现有 `SQLiteDocumentRegistry`。

不复制第二套写事务。并发状态发生变化时，Registry 的 Manifest count/corpus Gate 使事务回滚。

## 6. Broken index inspection / rebuild

`SQLiteIndexMaintainer.inspect()` 检查：

- active document/version/chunk counts；
- FTS missing/stale/duplicate/mismatched rows；
- 最新 Manifest state；
- Manifest schema/index version/content hash；
- Manifest counts 与 active corpus；
- Manifest corpus hash。

`rebuild()` 在 `BEGIN IMMEDIATE` 中删除全部 FTS rows，只从 active immutable Chunks 重建，并写入新的规范 ready Manifest。相同 `manifest_id` 或 `content_hash` 的损坏/历史行在写入前清理。

## 7. Retrieval Eval

离线 fixture 固定四类知识：

- asyncio cooperative cancellation；
- SQLite WAL / busy timeout；
- TCP sequence/ack/window；
- RAG stale/duplicate/source locator。

指标：

- Recall@K；
- MRR；
- graded nDCG@K。

Fixture Gate：Recall@3、MRR、nDCG@3 均为 1.0。该 fixture 用于回归，不代表公开 benchmark 成绩。

## 8. Test matrix

- Request normalization / deterministic ID；
- add → unchanged noop → update → delete；
- pinned Manifest stale rejection；
- stale old-version token 不可检索；
- exact duplicate filtering；
- fake stale FTS row filtering；
- heading drift filtering；
- document scope before candidate pool；
- legal `state=broken` Manifest fail-closed；
- tampered ready Manifest fail-closed；
- missing/stale FTS rebuild；
- rebuild over manifest identity collision；
- metric definitions；
- fixed fixture quality Gate；
- full non-live pytest and high-signal Ruff.

## 9. 明确非目标

- ContextSource / ContextOrchestrator；
- CitationAnchor / answer generation / grounding；
- no-answer / abstention；
- Dense Retrieval / embedding / vector database；
- RRF / reranker；
- PDF / OCR；
- online scholarly search；
- Prompt construction；
- automatic index repair during a user query。

## 10. GO / NO-GO

`GO`：

- active/stale/duplicate semantics deterministic；
- add/update/delete/noop 使用同一 Phase A Registry；
- broken Manifest 或 pinned snapshot drift fail-closed；
- rebuild 只信任 active immutable Chunks；
- fixed fixture metric Gate 通过；
- full repository CI and Ruff pass。

`NO-GO`：

- stale Version 可进入结果；
- document scope 在 pool 之后过滤；
- corrupted ready Manifest 被接受；
- rebuild 从 FTS 自身复制损坏内容；
- mutation 绕过 Phase A Registry；
- Context/Citation/Prompt 被混入当前 PR；
- CI 存在未解释失败。

## 11. 验证状态

- 独立 SQLite FTS5 query smoke：PASS；
- GitHub Actions API 当前由连接器返回 upstream 502；
- full repository pytest / Ruff 结果尚未读取；
- 在取得最终 branch HEAD CI 前，本 SOP 不宣告 Repository GO。
