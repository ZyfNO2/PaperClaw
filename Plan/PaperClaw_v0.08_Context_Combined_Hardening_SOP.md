# PaperClaw v0.08 Context / Combined Hardening SOP

> 状态：Implementation complete / CI pending  
> 分支：`test/v0.08-context-combined-hardening`  
> 基线：`main@872c4532fe00b3a3e8b72202fdd4c504594d8acc`

## 范围

- Context、MCP、Retrieval 三包同树导入；
- candidate permutation determinism；
- rendered Prompt 任意预算边界；
- protected overflow fail-closed；
- 不同 `PYTHONHASHSEED` 下 Context fingerprint、MCP schema hash、RAG stable ID 一致；
- 10k candidates 有界完成、Trace 截断且不保存正文；
- MCP environment value 与 Context raw content 不进入 fingerprint/Trace。

## 非目标

- 长期 Memory；
- LLM summarizer；
- ContextSource 动态权重；
- MultiAgent shared/private policy；
- QueryEngine 修改；
- MCP/RAG 新功能。

## Gate

定向测试、全仓库非 live pytest 与 Ruff 高信号规则全部通过。
