# PaperClaw v0.09 MCP Protocol Foundation — Phase A SOP

> 状态：Phase A offline implemented / repository CI pending  
> 基线：`main@36f44de6b580ded14ff198d64c1e3d80bbfe3fe7`  
> 分支：`feat/v0.09-mcp-protocol-foundation`  
> 协议冻结：Model Context Protocol `2025-11-25`  
> 范围：v0.09 MCP Tool Gateway MVP 的协议层 Phase A，不代表完整 v0.09 已交付。

## 1. 用户故事

PaperClaw 可以启动一个明确配置的本地 MCP stdio Server，完成
`connect → initialize → discover → call → close` 生命周期，将 Server 工具描述
归一化为稳定合同，并在 Server 超时、断连、协议响应非法或 schema 不受支持时
fail-closed。

Phase A 只证明协议边界，不让 MCP Tool 进入 Agent Runtime。

## 2. 当前范围

### 2.1 必做

- [x] `MCPServerConfig`
- [x] `MCPServerIdentity`
- [x] `MCPConnectionState`
- [x] `MCPCapabilitySnapshot`
- [x] `MCPToolDescriptor`
- [x] `MCPInvocationRequest`
- [x] `MCPInvocationResult`
- [x] `MCPError`
- [x] 一个本地 `stdio` transport baseline
- [x] JSON-RPC 2.0 单请求生命周期
- [x] `initialize` 与 `notifications/initialized`
- [x] `tools/list` 分页发现
- [x] `tools/call`
- [x] tool schema normalization 与稳定 SHA-256
- [x] unknown / unsupported schema fail-closed
- [x] deterministic fake MCP server
- [x] timeout、disconnect、invalid response 测试

### 2.2 明确不做

- [ ] 不接 `ToolRegistry`
- [ ] 不接 Permission / approval
- [ ] 不做 capability selection 或 Top-K
- [ ] 不把 MCP 描述或 Server instructions 注入 Prompt
- [ ] 不支持 MCP Resources / Prompts
- [ ] 不支持远程写操作或副作用重试
- [ ] 不做多 Server 路由、冲突消解或健康评分
- [ ] 不接 Trace、Run Budget 或 ContextOrchestrator

未勾选项是明确非目标，不是本 Phase 的 pending。

## 3. 协议与 transport 冻结

Phase A 按官方 MCP `2025-11-25` 冻结：

- 基础消息为 JSON-RPC 2.0；
- Client 必须先发送 `initialize`；
- 成功协商后发送 `notifications/initialized`；
- 本地 transport 使用 Client 启动的 stdio 子进程；
- 每条消息为 UTF-8 单行 JSON，以换行符分隔；
- stdout 只承载 MCP 消息；
- initialize 不发送 cancellation；其他 request 超时后尽力发送
  `notifications/cancelled`，随后会话进入 `FAILED` 并关闭 transport。

官方参考：

- `https://modelcontextprotocol.io/specification/2025-11-25/basic/lifecycle`
- `https://modelcontextprotocol.io/specification/2025-11-25/basic/transports`
- `https://modelcontextprotocol.io/specification/2025-11-25/server/tools`
- `https://modelcontextprotocol.io/specification/2025-11-25/basic/utilities/cancellation`

## 4. 架构边界

```text
MCPServerConfig
        ↓
StdioMCPTransport
  launch / read / write / timeout / disconnect
        ↓
MCPClientSession
  connect / initialize / discover / call / close
        ↓
normalize_tool_descriptor
        ↓
MCPToolDescriptor + MCPInvocationResult
```

- `paperclaw.mcp` 不导入 Tool、Permission、Harness、Context、Trace 或 Agent。
- Session 采用同步 single-flight request，避免 Phase A 引入 async / multiplexing。
- MCP Server 返回的 `instructions` 不保留正文，只记录
  `server_instructions_ignored=True`。
- 工具必须先成功 discovery 才能 call。
- discovery 任一页失败时不提交部分工具集合。

## 5. Normalized contract

### 5.1 Server 配置与身份

- `server_id` 使用稳定 ASCII 标识；
- `MCPServerConfig.fingerprint` 包括命令、cwd、环境变量名、协议和限制；
- 环境变量值不进入 fingerprint，避免 Secret 派生值进入后续 metadata；
- `MCPServerIdentity` 只来自成功的 initialize response。

### 5.2 Tool descriptor

- 工具名限制为 1–128 个 `[A-Za-z0-9_.-]` 字符；
- 内部 qualified name 为 `<server_id>.<tool_name>`；
- input/output schema 被递归规范化、key 排序、冻结并计算 SHA-256；
- description/title 有界；
- annotations、icons、`_meta` 和任意 Server instructions 不进入 normalized contract。

### 5.3 Schema fail-closed

Phase A 支持保守 JSON Schema 子集：

- `object/array/string/number/integer/boolean/null`；
- `properties/required/items/additionalProperties`；
- 常见数值、字符串、数组和元数据约束；
- 2020-12 与 draft-07 dialect 标识。

以下能力明确拒绝，直到后续版本定义语义与验证器：

- `$ref` / `$defs`；
- `oneOf` / `anyOf` / `allOf` / `not` / `if-then-else`；
- schema-valued `additionalProperties`；
- tuple-form `items`；
- 未知关键字、非有限数值、非 object 顶层 tool schema。

### 5.4 Invocation result

Phase A 只接受：

- `content[]` 中的 text block；
- 可选 object `structuredContent`；
- boolean `isError`。

image、audio、resource link、embedded resource 等内容 fail-closed，因为其存储、
权限、脱敏与 Context 合同尚未定义。

## 6. Error taxonomy

关键错误码：

- `INVALID_STATE`
- `TRANSPORT_START_FAILED`
- `TRANSPORT_DISCONNECTED`
- `REQUEST_TIMEOUT`
- `INVALID_JSON`
- `INVALID_RESPONSE`
- `MISMATCHED_RESPONSE_ID`
- `MESSAGE_TOO_LARGE`
- `PROTOCOL_ERROR`
- `PROTOCOL_VERSION_MISMATCH`
- `REQUIRED_CAPABILITY_MISSING`
- `INVALID_TOOL_SCHEMA`
- `UNSUPPORTED_TOOL_SCHEMA`
- `TOOL_NOT_DISCOVERED`
- `INVALID_TOOL_RESULT`
- `UNSUPPORTED_RESULT_CONTENT`
- `CLOSE_FAILED`

错误只携带 bounded message、server ID、request ID、RPC code 和 phase；不保留
完整响应、环境变量或 Server instructions。

## 7. Test matrix

| Case | Evidence | Expected |
|---|---|---|
| 正常 lifecycle | deterministic stdio fake server | initialize/discover/call/close PASS |
| 分页 discovery | 两页 tools/list | 顺序稳定、无部分提交 |
| schema canonicalization | 等价但不同 key/order | hash 与 normalized object 相同 |
| unsupported schema | `oneOf` | `UNSUPPORTED_TOOL_SCHEMA`，零工具注册 |
| request timeout | tools/call 不响应 | 有界退出、`FAILED` |
| disconnect | tools/call 前退出 | `TRANSPORT_DISCONNECTED`、`FAILED` |
| invalid JSON | tools/list 非 JSON | `INVALID_JSON`、`FAILED` |
| wrong response ID | tools/list ID 不匹配 | `MISMATCHED_RESPONSE_ID`、`FAILED` |
| ambiguous response | 同时 result/error | `INVALID_RESPONSE`、`FAILED` |
| unsupported result content | image block | `UNSUPPORTED_RESULT_CONTENT`、`FAILED` |
| version mismatch | initialize 返回旧版本 | disconnect、`FAILED` |
| Secret fingerprint | 环境值变化 | fingerprint 不变化 |

## 8. Gate

### Phase A GO

- 所有指定合同存在且不可变；
- local stdio lifecycle 可执行；
- unsupported schema 不产生可调用 descriptor；
- timeout、disconnect、invalid response 有界且结构化失败；
- fake server 测试与全仓库 CI 通过；
- 没有接入 Registry、Permission、Prompt 或 Runtime。

### Phase A NO-GO

- schema 未知仍可调用；
- initialize 前允许 tools/list/call；
- response ID 不匹配仍被接受；
- timeout 后 session 继续复用，可能消费迟到响应；
- MCP Server instructions 被保留为 Prompt 内容；
- 本 PR 修改现有 Tool / Agent 执行路径。

## 9. 验证命令

```powershell
python -m pytest tests/unit/test_mcp_protocol_foundation.py -q
python -m pytest --basetemp=tmp/pytest -q -m "not real_llm"
python -m ruff check src/paperclaw tests --select E9,F63,F7,F82 --ignore F821
```
