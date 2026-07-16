# PaperClaw v0.09 MCP Capability Selection SOP

> 状态：Implementation complete / repository CI pending  
> 分支：`feat/v0.09-mcp-capability-selection`  
> 依赖：PR #23 MCP Runtime、PR #25 Shared ContextSource Registry  
> 范围：Capability metadata index、task/keyword/scope/permission Top-K、ContextCandidate 接入、selection Eval、离线 MCP MVP E2E。

## 1. 架构

```text
MCP discovery
→ MCPRuntimeConnection.descriptors
→ MCPCapabilityIndex.freeze
→ task / keyword / scope / selection-eligibility Top-K
→ MCPCapabilityContextSource
→ external_untrusted ContextCandidate
→ ContextSourceRegistry
→ ContextOrchestrator
→ PromptAssembler
→ existing AgentRuntime / MCP Runtime invocation
```

MCP selection 模块不构造 Provider Prompt。只有 `PromptAssembler` 渲染最终输入。

## 2. Metadata index

每个 capability 保存：

- exact `server_id.tool_name`；
- node-safe registry Tool name；
- title / bounded Server description；
- normalized keywords；
- input field names；
- scopes；
- input schema hash。

Index 拒绝 remote identity 或 Registry identity 冲突，Runtime 构造前冻结，并生成确定性 fingerprint。

## 3. Selection

请求：task、scopes、Top-K。

Gate 顺序：

1. scope intersection；
2. selection-time permission eligibility；
3. keyword overlap；
4. weighted lexical score；
5. score 降序、qualified name 稳定 tie-break；
6. Top-K。

Selection-time Permission 只表示候选可见性，不授予执行权限。MCP Runtime 在 invocation 前仍重验 Schema 与 Permission。

## 4. Prompt injection containment

- Server instructions 在 Protocol Foundation 已丢弃；
- Server description 不再保留在基础 ToolRegistry description；
- ToolRegistry 只显示 generic MCP Runtime 描述；
- 被选中的 Server description 仅存在于 `external_untrusted` ContextCandidate；
- `ContextOrchestrator` 将其放入 `UNTRUSTED DATA`；
- Context priority 不授予 Permission。

## 5. Eval

固定 fixture 覆盖：echo、integer add、academic search。

指标：

- Recall@K；
- MRR；
- graded nDCG@K；
- Top-1 Accuracy。

Fixture Gate：四项均为 1.0。该结果是确定性回归，不是公开 benchmark。

## 6. Offline E2E

真实本地 stdio Fake MCP Server：

```text
connect → initialize → discover → register
→ capability index → Top-1 ContextCandidate
→ ContextOrchestrator / UNTRUSTED DATA
→ Agent selects node-safe Tool name
→ Schema validation → invocation Permission recheck
→ tools/call → result → done
```

## 7. 明确非目标

- Dense semantic capability retrieval；
- LLM-based selector；
- automatic multi-server health routing；
- capability refresh/reconnect；
- Human approval UI；
- MCP Resources / Prompts；
- direct Prompt construction；
- invocation Permission replacement。

## 8. GO / NO-GO

`GO`：稳定 Top-K、scope/eligibility filtering、description containment、ContextOrchestrator 接入、Eval Gate 和完整离线 E2E 全部通过。

`NO-GO`：Server description 进入基础 trusted Tool prompt、selection 被当成执行授权、MCP 模块直接拼 Prompt、依赖未明确、或 CI 有未解释失败。
