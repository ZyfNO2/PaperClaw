# PaperClaw v0.09 Shared ContextSource Registration Contract

> 状态：Implementation complete / Repository CI PASS / Offline GO  
> 分支：`feat/v0.09-context-source-registration-contract`  
> Draft PR：`#25`  
> 范围：冻结 MCP Capability Selection 与 RAG Retrieval ContextSource 共用的注册、冻结、DI 与 Trace 边界。

## 1. 目标

PR 5 与 PR 6 都需要向 v0.08 `ContextOrchestrator` 提供 `ContextCandidateSource`。本切片只建立一个公共注册入口，避免两个分支分别修改 Executor dependency injection。

```text
MCP selection source ─┐
                      ├→ ContextSourceRegistry.freeze()
RAG retrieval source ─┘          ↓
                    ContextOrchestratedAgentRuntimeExecutor
                                  ↓
                         ContextOrchestrator
                                  ↓
                         PromptAssembler
```

注册器不拼 Prompt、不分配 token、不提升 trust、不选择候选，也不授予 Tool Permission。

## 2. 公共合同

- `ContextSourceDescriptor`
- `ContextSourceRegistrySnapshot`
- `ContextSourceRegistry`
- `ContextSourceRegistryError`
- `ContextSourceRegistryFrozen`
- `ContextSourceCollectionError`
- `SourceKind`

Source kind 冻结为：

- `retrieval`
- `tool_selection`
- `memory`
- `custom`

## 3. 注册规则

- `source_id`：1–128 个 `[A-Za-z0-9_.-]` 字符；
- 同一 `source_id` 不可重复；
- Source 必须实现 callable `collect(ContextRequest)`；
- descriptor 包含 kind、priority、scopes、enabled；
- deterministic order：priority 降序，再按 `source_id`；
- disabled Source 不执行；
- Runtime 构造时 Registry 冻结，之后不能再注册；
- snapshot fingerprint 只基于 descriptor，不基于 Source 对象地址或候选正文。

## 4. 收集规则

- Registry 自身实现 `ContextCandidateSource`；
- 每个 Source 只能返回 `ContextCandidate`；
- 跨 Source 或单 Source 内 candidate ID 冲突 fail-closed；
- Source 异常包装为 `ContextSourceCollectionError`，只暴露 source ID 与异常类型；
- 原始异常正文不进入 Registry 错误消息；
- Registry 不改变 Candidate trust、priority、bucket、scope 或 content。

## 5. Runtime DI

`ContextOrchestratedAgentRuntimeExecutor` 新增：

```python
context_source_registry: ContextSourceRegistry | None = None
```

规则：

- custom `orchestrator` 与 `context_source_registry` 互斥；
- Registry 在 Runtime 构造时冻结；
- 冻结 Registry 作为普通 Source 传给 `ContextOrchestrator`；
- 未提供 Registry 时保持 v0.08 原行为；
- 旧 `AgentRuntimeExecutor` 不变。

## 6. Trace

现有 `context.assembly.completed/failed` 事件新增：

- `context_source_registry_fingerprint`
- `context_source_count`

不记录 Source 对象、候选正文、Prompt 或 Secret。

## 7. Test Gate

- 注册顺序不同但 descriptor 集合相同 → snapshot/fingerprint 相同；
- duplicate source ID 拒绝；
- freeze 后注册拒绝；
- priority/source ID 顺序稳定；
- disabled Source 不执行；
- Source 异常有界且可归因；
- candidate ID collision 拒绝；
- Executor 冻结 Registry；
- Candidate 只通过 Orchestrator 进入 Prompt；
- external candidate 仍进入 `UNTRUSTED DATA`；
- Trace 含 fingerprint/count，不含正文；
- custom orchestrator + Registry 拒绝；
- full pytest/Ruff PASS。

## 8. 明确非目标

- MCP capability metadata 或 Top-K；
- RAG query、Citation 或 grounding；
- Source 动态热插拔；
- Source-specific timeout/retry/circuit breaker；
- Source scope/permission policy；
- Prompt section rendering；
- Context budget policy 修改；
- QueryEngine 修改。

## 9. 验证结果

```text
Validated HEAD: b3625c9f0e6d851fb81b09a7444aa91cb0fd26dd
GitHub Actions run: 29541766937
Windows pytest: 567 passed, 0 failed, 0 skipped
pytest exit status: 0
Ruff E9/F63/F7/F82: PASS
artifact: pytest-results-29541766937
artifact digest: sha256:0621460b94791cba0aca7b89c05c1298f76bdff0de2efc9e5a081d0668524aed
```

测试数按 `pytest_reportlog.jsonl` 的 call-phase 记录统计。

## 10. 后续使用

PR #26 注册 `tool_selection` Source；PR #27 注册 `retrieval` Source。二者均返回 `ContextCandidate`，均不得直接构造 Provider Prompt。
