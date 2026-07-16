# PaperClaw v0.09 MCP Runtime Integration SOP

> 状态：实现中 / stacked on MCP Protocol Foundation  
> 分支：`feat/v0.09-mcp-runtime-integration`  
> 依赖：v0.08 Context Orchestration、v0.09 MCP Protocol Foundation  
> 范围：把已发现 MCP Tool 接入现有 ToolRegistry、Run Budget、Permission 与 Trace，不做 capability selection。

## 1. 目标

本切片不创建第二套 Agent Runtime。MCP Tool 必须表现为现有 `Tool`，继续经过：

```text
ToolRegistry
→ invocation schema validation
→ invocation-time Permission recheck
→ existing max_tool_calls budget
→ MCPClientSession.call
→ redact before truncate
→ existing tool events / session_events Trace
```

Server 连接、发现或调用失败只能影响对应 MCP Tool/connection，不能删除、替换或阻断已有本地 Tool。

## 2. 范围

### 2.1 必做

- MCP Tool 以稳定限定名注册到现有 `ToolRegistry`；
- 注册前完成全部名称冲突预检，失败时 Registry 不发生部分写入；
- 根据冻结的 normalized JSON Schema 在每次远程调用前校验参数；
- Permission 默认拒绝，调用方必须显式提供策略；
- Permission 在实际 invocation 边界重新检查，不能只在 discovery/registration 时检查；
- 远程调用支持有界 timeout；
- cooperative cancellation 会关闭当前 MCP connection，并通过现有 `ToolControlFlow` 结束 Run；
- MCP Tool 自动复用 `AgentRuntimeExecutor` 的 `max_tool_calls`；
- MCP Tool 自动复用现有 `tool.started/tool.completed/tool.failed` 与 SQLite `session_events`；
- MCP result/error 先脱敏，再执行 Tool output truncate；
- Server connect/discover/call failure 不使本地 Tool 不可用；
- 本地 Tool 既有测试和完整回归保持通过。

### 2.2 明确不做

- capability selection / Top-K / capability routing；
- MCP description 或 Server instructions 注入 Context/Prompt；
- MCP Resources / Prompts；
- 多 Server 自动路由、同名冲突消解或健康评分；
- reconnect / capability refresh；
- Human approval UI；
- 远程写操作自动重试或幂等策略；
- 新的 QueryEngine、Budget、Trace 数据库或 Permission 框架。

## 3. 关键合同

### 3.1 Tool 命名

```text
mcp.<server_id>.<remote_tool_name>
```

远端原始名称和 schema hash 保留在 Tool metadata；限定名用于现有 Registry、Prompt action parser、Run Budget 与 Trace。

### 3.2 Permission

```text
MCPPermissionPolicy.authorize(
    descriptor,
    arguments,
    ToolContext,
) -> MCPPermissionDecision
```

默认策略是 `DenyAllMCPPermissionPolicy`。首切片提供显式 `AllowListMCPPermissionPolicy`，匹配 `server_id.tool_name`。策略异常、无效响应和拒绝均 fail-closed。

### 3.3 Schema validation

Protocol Foundation 已在 discovery 时拒绝未知 schema dialect/keyword。本切片对已接受 subset 实现 invocation-instance validation：

- type / enum / const；
- required / properties / additionalProperties；
- string length / pattern；
- array items / size / uniqueness；
- numeric bounds / multipleOf；
- object property count。

参数无效时不得调用 Server。

### 3.4 Timeout / cancellation

MCP Tool 在 daemon worker 中执行同步 session call，Runtime 线程每 50ms 检查：

- stop token；
- invocation deadline；
- call result/error。

取消关闭 connection 后抛出 `ToolControlFlow`；timeout 返回结构化 Tool failure 并关闭 connection，避免迟到响应污染后续 single-flight 请求。

## 4. Trace 与脱敏

不新增 MCP TraceStore。注册后的 MCP Tool 由现有 `_BudgetedTool` 包装，因此调用进入已有：

```text
tool.started
permission.denied / tool.failed
 tool.completed / tool.failed
session_events
TraceEvent projection
```

Tool 名使用限定名即可识别 MCP invocation。远端 output/error 在进入 `ToolResult` 前使用现有 `TraceRedactor` 删除配置环境值、Bearer 与路径信息，随后才执行 output truncate。

## 5. 测试矩阵

- registration 与本地 Tool 共存；
- collision/registration failure 原子性；
- invalid arguments 不越过 schema gate；
- default deny；
- permission 每次调用重验和运行中撤销；
- timeout；
- cooperative cancellation；
- redact-before-truncate；
- Server discovery failure 后本地 Tool 正常；
- 真实本地 stdio Fake Server register/call；
- AgentRuntime `max_tool_calls`；
- SQLite `session_events` 中 MCP Tool lifecycle；
- 全仓 Windows pytest 与 Ruff。

## 6. Gate

`GO`：MCP Tool 不绕过 Registry、schema、Permission、Budget 或 Trace；远端失败隔离；全部自动化回归通过。

`NO-GO`：MCP 调用绕过现有 Tool path、Permission 只在注册时检查、先截断后脱敏、Server 失败导致本地 Tool 消失，或未满足前置 PR 合并顺序即宣称 main-ready。
