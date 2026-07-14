# PaperClaw v0.05 QueryEngine Contract

> 状态：MVP 已冻结 / GO
> 日期：2026-07-15

## 1. 公开入口

```python
class QueryEngine:
    def submit(self, text: str, *, limits: RunLimits | None = None) -> RunResult: ...
    def get_run(self, run_id: str) -> AgentRunView: ...
    def request_stop(self, run_id: str, reason: str = "user_requested") -> bool: ...
```

v0.05 仅支持单个 Conversation 内顺序 `submit()`。并发提交明确拒绝，不排队、不隐式创建第二执行器。

## 2. RunLimits

```python
@dataclass(frozen=True)
class RunLimits:
    max_steps: int = 20
    max_model_calls: int = 10
    max_tool_calls: int = 20
```

三个字段均为正整数硬限制：

- `max_steps` 复用现有 AgentRuntime 的 step boundary；
- `max_model_calls` 在底层 `ChatModel.complete()` 调用前检查；
- `max_tool_calls` 在底层 Tool `validate()` / `execute()` 路径前检查；
- 达到上限后不再进入底层调用；
- 被工具自身 validation 拒绝的尝试计入 tool call，因为真实安全边界已经进入；
- 因上限被挡住、未进入底层的调用不计数。

## 3. RunExecutor 边界

```python
class RunExecutor(Protocol):
    def execute(
        self,
        request: RunRequest,
        *,
        emit: EventEmitter,
        stop_token: StopToken,
    ) -> ExecutionReport: ...
```

`QueryEngine` 只管理 Run 生命周期，不直接：

- 调用模型或工具；
- 拼 Prompt；
- 访问 SQLite / Repository；
- 重试外部副作用；
- 绕过工具 validation；
- 处理 recovery reconciliation。

生产实现为 `AgentRuntimeExecutor`，它适配现有同步 `AgentRuntime`，不重写 PocketFlow graph。生产 adapter 默认启用 v0.02 Verify / Reflection Gate；仅兼容性测试或明确的 legacy 调用可以显式关闭。

## 4. Terminal status

允许的终态：

```text
completed
failed
blocked
stopped
budget_exhausted
```

映射规则：

| Runtime stop reason | QueryEngine status |
|---|---|
| `done` / `completed_verified` | `completed` |
| `max_steps` / `max_model_calls` / `max_tool_calls` | `budget_exhausted` |
| `recovery_required` | `blocked` |
| `blocked_environment` / `verification_failed` | `blocked` |
| `cancelled` / `timeout` | `stopped` |
| 未识别失败 | `failed` |

`running` 仅允许出现在 `AgentRunView`，不得作为 executor 终态。

## 5. RunResult

```python
@dataclass(frozen=True)
class RunResult:
    run_id: str
    status: str
    output: str | None
    stop_reason: str
    model_calls: int
    tool_calls: int
    last_event_sequence: int
```

成功与否只由结构化 status 判定，不从自由文本 output 推断。

## 6. Event contract

QueryEngine 冻结以下生命周期事件：

```text
run.started
run.stop_requested
run.completed
run.failed
run.stopped
```

生产 adapter 可转发：

```text
model.started
model.completed
model.failed
tool.started
tool.completed
tool.failed
permission.denied
```

约束：

- 单个 Run 内 sequence 从 1 严格递增；
- 每个 Run 恰好一个 terminal event；
- `blocked`、`stopped`、`budget_exhausted` 均使用 `run.stopped`，具体 status 放在 payload；
- QueryEngine event 与 v0.04 SessionEvent 分层存在，不合并为新 EventBus。

## 7. Cooperative stop

`request_stop()` 只设置 cooperative token：

- 在下一个模型或工具安全边界生效；
- 不承诺强制中断正在执行的同步模型请求或子进程；
- 重复请求返回 `False`；
- 已终止 Run 返回 `False`；
- 不重复生成 stop-request event。

## 8. Session 接线

`AgentRuntimeExecutor` 可选接收 v0.04 `Repository`：

- 使用 QueryEngine 的 `run_id` 建立 Run；
- 保存 user / assistant message；
- 将 model/tool adapter event 写入 `SessionService`；
- 最终调用 `SessionService.close()`；
- QueryEngine 本身不访问 SQL。

CLI 的 v0.05 默认路径未强制开启 SQLite 持久化；持久化由上层装配决定。

## 9. 明确非目标

v0.05 不包含：async 全栈、流式 delta、后台 Shell、EventBus、Replay、通用 Provider Gateway、token/cost 计费、独立新 PermissionEngine、MultiAgent durability、MCP/Plugin/Hook。
