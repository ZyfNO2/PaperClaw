# PaperClaw v0.09.1 RAG Storage Hardening SOP

> 状态：Implementation complete / CI pending  
> 分支：`test/v0.09.1-rag-storage-hardening`  
> Stack base：PR #24 `feat/v0.09.1-bm25-incremental-retrieval`

## 范围

- Windows-style file URI、空格与 CJK identity 稳定性；
- 不同 `PYTHONHASHSEED` 下 Chunk ID / Corpus hash 一致；
- malformed Markdown fence / heading 有界解析；
- CJK 无空格超长段落持续切分，无空 Chunk、死循环或重复 ID；
- add transaction 中断后 Document/Version/Chunk/FTS/Manifest 全回滚；
- concurrent reader 只能观察事务前或事务后快照；
- FTS corruption 后 rebuild 恢复准确 counts、Corpus hash 和检索结果。

## 非目标

- Dense Retrieval / RRF / Reranker；
- PDF/OCR；
- online retrieval；
- Grounding/Citation 语义修改；
-生产级跨进程写并发扩展。

## Gate

#24 先合并；本 PR rebase 到新 main 后运行定向测试、全仓库非 live pytest 与 Ruff。通过后再处理 #27。
