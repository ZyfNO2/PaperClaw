# v0.39 Memory Semantics

## Scope

结构化 persistent memory 只允许两种 scope：

- `USER:<user_scope_id>`：同一用户可跨项目复用。
- `PROJECT:<project_scope_id>`：只对指定项目可见。

每次 list/search/snapshot 都显式传入 user/project scope；其他 scope 或跨 scope 查询会被拒绝。USER 与 PROJECT 的同名内容也保持为不同 `memory_id` 和不同 projection。

## Immutable lifecycle

`MemoryItem` 是 append-only 事实记录。replace 不覆盖原行，而是新增 item 并设置 `supersedes_memory_id`；remove 不删除行，而是新增 tombstone。active projection 只返回每个 chain 的当前非 tombstone head，history/search 仍能追溯原记录和替换关系。

每个 item 还保存 `created_from_run_id`、`created_from_sequence`、bounded `source_refs`、trust、importance、created_at 和 content hash。memory body 与 provenance metadata 分开存储。

## Session snapshot

Session 初始化时按确定性顺序选择 USER 与 PROJECT memory，生成并持久化 `MemorySnapshot`：

```text
USER pinned -> PROJECT pinned -> budgeted rendered content
```

同一 Session 中：

1. S1 创建时得到 snapshot A；
2. S1 中途 add/replace/remove 只改变持久化 active projection；
3. S1 后续 turn 仍使用 snapshot A，`rendered_hash` 不变；
4. 下一 Session S2 重新 capture，才看到新的 active projection。

reopen 会加载原 snapshot，而不会隐式重算；只有新 Session 或显式 capture 才会产生新 snapshot。

## L5 context

`StructuredMemoryContextSource` 将 memory 转成现有 `ContextItem`：

- pinned：来自 frozen snapshot，`memory_mode=pinned`，受保护预算优先注入；
- recall：每 turn 对当前 query 做 bounded lexical recall，`memory_mode=retrieved`，仅限显式 USER/PROJECT scope；
- 两类 item 都带 `memory_id`、scope、kind、trust、content_hash、source_refs，ContextAssemblyTrace 仅携带 bounded memory IDs。

## Trust and content boundary

`external_untrusted` 不能直接写入 persistent memory。只有显式用户确认才能晋升为 user-confirmed trust。memory body 不接收 transcript/evidence/artifact source-body 标记；外部材料只能作为 bounded `source_refs` provenance 保存。MVP 不做自动抽取，不把对话历史、证据正文或 artifact 正文当作 memory。

## Disabled and legacy behavior

没有 repository 或没有启用结构化 memory 时，旧的 file-backed memory adapter 保持原行为。结构化服务不改变现有 Context、Session、QueryEngine、ToolRegistry 的公共调用方式。

