# v0.39 Known Limitations and Deviations

## Durable runtime hardening boundary

8. Exact-head GitHub CI cannot be claimed before this local branch is pushed;
the final handoff records it as `AWAITING REAL TEST`.
9. The local full non-live suite reached `1078 passed, 23 skipped, 12 deselected`
but retains two pre-existing Bash failures (`test_bash_tool_respects_stop_token_mid_execution`
and `test_bash_timeout_kills_child_process_tree`) caused by this Windows
environment's PowerShell command quoting/timeout path. They are not modified by
v0.39.
10. Real LLM, Docker isolation and manual native-OS validation were not run;
they are `NOT VERIFIED` and v0.40/v0.41 remain out of scope.
11. The full repository Ruff check reports 873 pre-existing findings across
unrelated files. The v0.39 slice passes the high-signal CI command and its
new contract test has no Ruff findings; no repository-wide rewrite was made.
12. No mypy, pyright or equivalent type-check gate is configured in the
active repository CI, so type validation is `NOT CONFIGURED / NOT VERIFIED`.

1. 本版本只做 offline validation。没有运行 real LLM、联网搜索、外部 Memory Provider、真实 TUI 人工演示或 CI。
2. memory extraction 仍由显式 service/tool 调用触发；没有自动从 transcript、evidence 或 artifact 抽取 memory。
3. recall 使用确定性的 Python lexical fallback，没有 FTS5、embeddings、vector database 或 reranker。
4. repository-backed structured memory 已接入 persistent TUI/runtime executor；legacy `ServiceRuntimeFactory` 的默认 file-backed memory 路径继续保留，用于 backward compatibility，尚未把结构化 memory 作为所有默认运行模式的强制默认项。
5. `pyproject.toml` package version 仍是 `0.38.0`；本次没有扩大范围做发行版本号切换。
6. 旧 `FileMemoryStore` 与新的 structured `MemoryService` 并存，顶层导出保留旧 `MemorySnapshot` 名称，并以 `StructuredMemorySnapshot` 暴露 v0.39 snapshot，避免破坏旧 API。
7. 当前 SOP/spec 的 checkbox 没有被自动改写；实现证据和验收结果记录在本目录，后续若要把设计文档 checkbox 标成完成，应另行做文档提交并复核其范围。
