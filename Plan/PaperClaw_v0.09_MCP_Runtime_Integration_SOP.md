# PaperClaw v0.09 MCP Runtime Integration SOP

> 状态：实现完成 / Offline GO  
> 分支：`feat/v0.09-mcp-runtime-integration`  
> Draft PR：`#23`  
> 前置：v0.08 PR #19、MCP Protocol Foundation PR #21 均已合并  
> 范围：把已发现 MCP Tool 接入现有 ToolRegistry、Run Budget、Permission 与 Trace；不做 capability selection。

## 1. Runtime 路径

本切片不创建第二套 Agent Runtime。MCP Tool 必须表现为现有 `Tool`，继续经过：

```text
MCPClientSession discover
→ node-safe Tool identity
→ existing ToolRegistry
→ invocation schema validation
→ invocation-time Permission recheck
→ existing max_tool_calls budget
→ MCPClientSession.call
→ redact before truncate
→ existing tool events / SQLite session_events
```

Server 连接、发现或调用失败只能影响对应 MCP connection，不能删除、替换或阻断已有本地 Tool。

## 2. 必做范围

- MCP Tool 注册到现有 `ToolRegistry`；
- 注册前完成全量名称冲突预检，失败时 Registry 不发生部分写入；
- 根据冻结的 normalized JSON Schema 在每次远程调用前校验参数；
- Permission 默认拒绝，调用方必须显式提供策略；
- Permission 在实际 invocation 边界重新检查；
- 远程调用支持有界 timeout；
- cooperative cancellation 关闭当前 MCP connection，并通过现有 `ToolControlFlow` 结束 Run；
- MCP Tool 复用 `AgentRuntimeExecutor` 的 `max_tool_calls`；
- MCP Tool 复用 `tool.started/tool.completed/tool.failed` 与 SQLite `session_events`；
- MCP result/error 先脱敏，再执行 Tool output truncate；
- Server connect/discover/call failure 不使本地 Tool 不可用；
- 本地 Tool 回归与全仓库测试保持通过。

## 3. 明确非目标

- capability selection / Top-K / capability routing；
- MCP description 或 Server instructions 注入 Context/Prompt；
- MCP Resources / Prompts；
- 多 Server 自动路由、同名冲突消解或健康评分；
- reconnect / capability refresh；
- Human approval UI；
- 远程写操作自动重试或幂等策略；
- 新的 QueryEngine、Budget、Trace 数据库或 Permission 框架。

## 4. Tool identity

现有 `NodeRegistry` 只接受 letters、digits、`:`、`_`、`-`。MCP 原始名称允许点号，因此 Registry/Agent action 名冻结为：

```text
mcp_<bounded_server_slug>_<bounded_tool_slug>_<identity_hash_12>
```

其中 hash 来自精确的 `server_id + NUL + remote_tool_name`。该格式：

- 与现有 NodeRegistry 兼容；
- 保留可读 server/tool slug；
- 通过 hash 避免规范化碰撞；
- 不改变 Permission identity，Permission 仍匹配精确 `server_id.tool_name`；
- ToolResult metadata 保留精确 `server_id`、remote tool 与 schema hash。

## 5. Permission contract

```text
MCPPermissionPolicy.authorize(
    descriptor,
    arguments,
    ToolContext,
) -> MCPPermissionDecision
```

默认策略是 `DenyAllMCPPermissionPolicy`。首切片提供显式 `AllowListMCPPermissionPolicy`。策略异常、无效响应和拒绝均 fail-closed。

## 6. Invocation Schema validation

Protocol Foundation 已在 discovery 时拒绝未知 schema dialect/keyword。本切片对已接受 subset 实现参数实例校验：

- type / enum / const；
- required / properties / additionalProperties；
- string length / pattern；
- array items / size / uniqueness；
- numeric bounds / multipleOf；
- object property count。

参数无效时不得调用 Server。

## 7. Timeout / cancellation

MCP Tool 在 daemon worker 中执行同步 session call，Runtime 线程周期检查 stop token、invocation deadline 和 call result/error。

- cancellation：关闭 connection，抛出 `ToolControlFlow`；
- timeout：返回结构化 `mcp_timeout` Tool failure 并关闭 connection；
- 关闭 connection 防止迟到响应污染下一次 single-flight request；
- reconnect 属于后续版本。

## 8. Trace 与脱敏

不新增 MCP TraceStore。注册后的 MCP Tool 由现有 `_BudgetedTool` 包装，调用进入已有 Tool lifecycle 与 `session_events` fact source。Trace 使用 node-safe Tool identity 标识 MCP invocation。

远端 output/error 在进入 `ToolResult` 前使用现有 `TraceRedactor` 脱敏，随后才执行 output truncate。当前通用 Tool lifecycle projection 不新增 MCP 专用 event schema。

## 9. Validation evidence

- 初始 CI run `29516623795`：569 tests passed、2 failed；发现并修复 MCP 点号 Tool name 与 NodeRegistry 不兼容，以及既有 Hypothesis Secret 生成值与固定 JSON key 碰撞问题；
- 最终代码验证 HEAD：`013fffd519e86efa88ef6e9d8e178a95224097de`；
- GitHub Actions run：`29517520350`；
- Windows pytest：`571 passed, 0 failed, 0 skipped`；
- pytest exit status：`0`；
- Ruff E9/F63/F7/F82：PASS；
- artifact digest：`sha256:83728a4cb5e7f26f657afd88c427954f3e4a11deee9326dedc75c510685a20b0`。

说明：pytest reportlog 同时记录 setup、call、teardown。`571` 是实际测试用例数；三阶段成功记录总数为 `1713`，不得将其表述为测试数量。

## 10. Gate

`GO`：MCP Tool 不绕过 Registry、schema、Permission、Budget 或 Trace；远端失败隔离；全量自动化回归通过。

`NO-GO`：MCP 调用绕过现有 Tool path、Permission 只在注册时检查、先截断后脱敏、Server 失败导致本地 Tool 消失，或 capability selection 被混入当前范围。
