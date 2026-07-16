# PaperClaw v0.08 Context Orchestration / Dynamic Prompt Assembly MVP SOP

> 状态：实施中  
> 冻结日期：2026-07-16  
> 基线：`main@36f44de6b580ded14ff198d64c1e3d80bbfe3fe7`  
> 开发分支：`feat/v0.08-context-orchestration-mvp`  
> Draft PR：`#19`

## 1. 用户可见闭环

用户通过现有 `QueryEngine` 提交 Coding / Research 任务。启用 v0.08 adapter 后，每次模型调用前，Runtime 将现有 Agent prompt、Workspace、结构化 Task State、历史消息、Tool 结果、v0.04 ContextItem / Checkpoint 与未来外部 ContextSource 的候选统一转成 `ContextCandidate`，在固定预算中完成冲突处理和选择，最后生成一个带稳定版本、fingerprint 和可回溯 Trace 的 Provider 输入。

旧 `AgentRuntimeExecutor` 保留为兼容路径。`QueryEngine` 不拼 Prompt、不读取 Repository、不执行 Tool。

## 2. 架构边界

```text
QueryEngine
    Run lifecycle / limits / stop / events / result
        ↓
ContextOrchestratedAgentRuntimeExecutor（opt-in composition）
        ↓
AgentRuntimeExecutor / Agent Loop
        ↓
Context-aware ChatModel boundary
        ↓
ContextOrchestrator
    collect → deduplicate → resolve → allocate → assemble
        ↓
PromptAssembler
    RUNTIME PROTOCOL / SELECTED CONTEXT / UNTRUSTED DATA
        ↓
Provider ChatModel
```

硬边界：

1. `QueryEngine` 保持薄 façade；
2. Context 层不调用 Tool，不授予 Permission；
3. 所有扩展来源只返回 `ContextCandidate`，不得直接拼 Prompt；
4. `external_untrusted` 只进入 `UNTRUSTED DATA`；
5. Trace 不保存 raw prompt、raw candidate content 或 Secret；
6. `session_events` 继续是 durable event fact source；
7. protected 内容无法容纳时 fail-closed，不做随机截断；
8. v0.04 `ContextBuilder`、compaction、scope 和 Snapshot 能复用则复用，不复制第二套持久化 Pipeline。

## 3. MVP 最小契约

- `ContextRequest`
- `ContextPolicy`
- `ContextCandidate`
- `ContextSelection`
- `ContextConflict`
- `ContextBudgetAllocation`
- `PromptSection`
- `PromptAssembly`
- `ContextAssemblyTrace`
- `ContextCandidateSource` Protocol

关键可审计字段：

```text
run_id / step_id
source / source_ref
layer / kind / scope
priority / trust / freshness
estimated_tokens / selected_tokens
selection_reason / exclusion_reason
conflict_group / conflict_resolution
compressible / pinned / sensitive
content_hash / policy_version / prompt_version / fingerprint
```

## 4. 确定性策略

### 4.1 Trust 与冲突

默认顺序：

```text
system
> trusted_local / project
> user
> tool_output
> external_untrusted
```

同一 trust 内：

1. `fact` 优先于 `hypothesis`；
2. priority 高者优先；
3. freshness 新者优先；
4. `candidate_id` 作为稳定 tie-breaker。

用户显式修正通过同一 `conflict_group` 和更高 freshness 使旧 preference 失效。外部 instruction 不能升级为 system/project rule。

### 4.2 预算

```text
available_input = max_input_tokens - output_reserve_tokens
```

protected：

- Runtime prompt；
- L0 / L1；
- constraint；
- evidence_ref；
- 未完成 todo；
- 显式 pinned candidate。

protected 总量超过 available input 时抛出 `ContextAssemblyBudgetExhausted`。非 protected 内容按显式 bucket quota 选择；每个排除项记录稳定原因。

### 4.3 Prompt section

稳定顺序：

1. `RUNTIME PROTOCOL`；
2. `SELECTED CONTEXT`；
3. `UNTRUSTED DATA`。

只有内容 hash、candidate ID、section trust、Prompt version 进入 fingerprint。raw content 不进入 durable Trace。

## 5. 三阶段实施

### Phase A：契约与 Orchestrator

- [x] 冻结 v0.08 最小契约；
- [x] 实现 collect / deduplicate / resolve / allocate / assemble；
- [x] 实现 protected fail-closed；
- [x] 实现稳定 Prompt version 与 fingerprint；
- [x] 预留 `ContextCandidateSource` Protocol；
- [x] 复用 v0.04 ContextBuilder / Snapshot 选择路径。

### Phase B：单 Agent Runtime 接线

- [x] 新增 opt-in `ContextOrchestratedAgentRuntimeExecutor`；
- [x] 保留旧 `AgentRuntimeExecutor`；
- [x] 每次 Provider call 前 assembly；
- [x] assembly completed / failed 进入 QueryEngine event；
- [x] Repository 启用时写入现有 `session_events`；
- [ ] 定向单元与集成测试 CI 通过；
- [ ] 处理 CI 发现的回归。

### Phase C：Eval、离线演示与留档

- [ ] 固定跨域 fixture；
- [ ] 生成可复现离线 demo artifact；
- [ ] 运行全量非 live pytest 与 Ruff；
- [ ] 记录测试数、失败、skipped、warning；
- [ ] 更新 README；
- [ ] 生成 implementation summary / known limitations / file manifest；
- [ ] 生成最终 Handoff；
- [ ] 运行 SOP completion hook 或记录云端不可执行边界。

## 6. 测试与 Eval Gate

| Gate | 验证方式 | 完成条件 |
|---|---|---|
| Constraint Retention | protected overflow / selection tests | protected 保留率 100%；无法容纳时 fail-closed |
| Context Precision | bucket quota fixture | 低优先候选按明确原因排除 |
| Conflict Accuracy | trust / fact / freshness fixtures | winner 与规则一致，loser 可追踪 |
| Injection Containment | external README fixture | 外部命令只在 `UNTRUSTED DATA` |
| Determinism | 同 fixture 重复 assembly | prompt 与 fingerprint 完全一致 |
| Runtime Wiring | FakeModel + QueryEngine | 每个 model call 恰有一个 assembly event |
| Durable Trace | SQLite integration | assembly event 写入原 `session_events`，无 raw prompt |
| Compatibility | legacy executor regression | 旧路径不出现 v0.08 assembly event |
| Full Regression | GitHub Actions Windows pytest | 非 live suite 无失败 |
| Static Correctness | Ruff high-signal gate | PASS |

## 7. GO / NO-GO

`GO`：

- QueryEngine 无 Prompt / Context 逻辑；
- opt-in Runtime 每个 Provider call 都有 PromptAssembly；
- protected 内容不静默丢失；
- external instruction 不进入高 trust section；
- fingerprint deterministic；
- assembly Trace 不含 raw prompt；
- 旧单 Agent executor 保持兼容；
- 定向测试、全量非 live pytest 与 Ruff 通过。

`NO-GO`：

- QueryEngine 或 Tool 层直接拼 Prompt；
- Context 超限随机截断；
- hypothesis 覆盖 verified fact；
- 外部 instruction 进入 Runtime/System section；
- durable event 保存 raw prompt 或 Secret；
- legacy executor 行为被强制替换；
- CI 存在未解释失败。

## 8. 明确非目标

- RAG / 向量数据库；
- MCP Client / Server；
- 长期 Memory lifecycle；
- LLM summarizer 硬依赖；
- 自动 Skill 生成；
- Provider-specific Prompt Cache；
- 通用 policy DSL；
- QueryEngine 直接接入 RAG、MCP、Memory 或 Tool；
- MultiAgent shared/private context 的完整策略。

## 9. 交付物

```text
src/paperclaw/context/orchestration.py
src/paperclaw/harness/context_runtime_executor.py
tests/unit/test_context_orchestration.py
tests/unit/test_context_runtime_executor.py
tests/integration/test_v0_08_context_assembly_demo.py
scripts/run_v0_08_context_demo.py
artifacts/v0_08/implementation_summary.md
artifacts/v0_08/test_report.md
artifacts/v0_08/known_limitations.md
artifacts/v0_08/file_manifest.txt
artifacts/v0_08/mvp_demo_trace.json
docs/handoff/PaperClaw_v0.08_Context_Orchestration_MVP_HANDOFF.md
```

## 10. Post-MVP 触发池

以下不属于 v0.08 完成条件：

- SQLite `memory_items` 与 Memory lifecycle；
- provider cache hint；
-动态 ContextSource 权重；
- optional LLM summarizer；
- MultiAgent shared/private policy；
- Context assembly TUI Inspector。

只有真实失败 Trace、Eval 或下游 MCP/RAG 用户故事证明必要时，才另开 SOP。
