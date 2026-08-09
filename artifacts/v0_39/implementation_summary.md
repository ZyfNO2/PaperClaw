# PaperClaw v0.39 Implementation Summary

## 状态

- 版本：v0.39 Structured Persistent Memory
- 分支：`feat/v0.39-memory-runtime`
- 基线：`main` 的 merge-base `5891d87`
- 当前实现提交（产物生成前）：`062b520`
- 结论：`GO / offline_validated`
- 说明：本版本没有运行真实 LLM、外部 Memory Provider、联网检索或 CI，因此不宣称 `live_validated`。

## 已实现闭环

1. SQLite v4 additive migration，增加 `memory_items` 与 `memory_snapshots`，不破坏旧 Context/Session 数据。
2. `MemoryItem` immutable history：add、replace、tombstone remove、active-head projection、history search。
3. USER/PROJECT scope isolation；仅允许显式的 USER 与 PROJECT scope。
4. `MemoryService` 作为唯一 domain mutation boundary；`MemoryRepository` 作为持久化 adapter。
5. Session 初始化时创建并持久化 frozen `MemorySnapshot`；同一 Session 不因中途写入而刷新 pinned snapshot。
6. L5 `StructuredMemoryContextSource`：pinned memory 与 per-turn lexical recall 都转成现有 `ContextItem`，保留 `memory_id`、scope、kind、trust、source_refs provenance。
7. 复用现有 `ToolRegistry`、`ContextAssembler`、`SessionService`、`Trace`；没有新增第二套 Runtime。
8. 保留 legacy file-backed memory adapter，空/禁用结构化 memory 时旧路径继续工作。

## 关键安全与边界决策

- `external_untrusted` 不能直接晋升为 persistent memory；需要显式用户确认，确认后才按 user-confirmed trust 写入。
- memory body 不接收 transcript/evidence/artifact source-body 标记；外部来源只保留 bounded `source_refs`。
- snapshot 使用确定性 scope/kind/importance/time/id 排序，并持久化 `rendered_hash`。
- recall 使用本地 bounded lexical scoring；没有 embeddings、vector DB、外部 provider 或自动抽取。
- Trace 只记录 bounded metadata 与 memory IDs，不记录完整 memory body。

## 证据入口

- 完整测试命令与真实输出：[`test_report.md`](test_report.md)
- 生命周期、scope、snapshot 语义：[`memory_semantics.md`](memory_semantics.md)
- 可复现的 frozen snapshot 结构示例：[`frozen_snapshot_demo.json`](frozen_snapshot_demo.json)
- 已知限制与未运行项：[`known_limitations.md`](known_limitations.md)
- 文件清单：[`file_manifest.txt`](file_manifest.txt)

