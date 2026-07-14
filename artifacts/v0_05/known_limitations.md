# PaperClaw v0.05 Known Limitations

> 版本判定：MVP GO
> 这些限制不阻止 v0.05 的薄 QueryEngine 用户故事成立，也不得在当前版本顺手扩张解决。

## 1. 同步、单活 Run

- 一个 `QueryEngine` 实例同一时间只允许一个 active `submit()`；
- 并发提交会明确报错，不排队；
- 没有多用户调度、分布式 Run 或 durable queue。

## 2. Cooperative stop 不是强制取消

- stop token 在模型或工具安全边界检查；
- 已经进入同步 provider call 的请求不会被强制中断；
- 已经启动的外部子进程不由 QueryEngine 终止；
- v0.05 不宣称 process-tree cancellation。

## 3. Budget 只覆盖调用次数

已实现：

- step count；
- model call count；
- tool call count。

未实现：

- token budget；
- cache token；
- reasoning token；
- monetary cost；
- wall-time budget；
- provider-specific quota negotiation。

工具进入 validation 后即计一次真实 tool attempt；被硬上限挡住、未进入底层的调用不计数。

## 4. CLI 默认不持久化 Session

`AgentRuntimeExecutor` 支持可选注入 v0.04 `Repository` 并连接 `SessionService`，但当前单 Agent CLI 默认没有自动创建 SQLite 数据库。

这避免在 v0.05 顺手增加数据库路径、生命周期和 migration UX。需要持久化的上层入口应显式装配 Repository。

## 5. ContextBuilder 尚未进入旧 Agent Prompt 主路径

v0.05 复用了 AgentRuntime / PocketFlow / ToolRegistry，并提供 Session 接线，但没有重写现有 Prompt 构建流程以强制通过 v0.04 `ContextBuilder`。

因此：

- QueryEngine 是统一执行入口；
- v0.04 Context 能力仍可独立使用；
- “每次 CLI submit 都由 ContextBuilder 编译 Prompt”不是 v0.05 已交付声明。

只有真实长任务出现 Context 丢失或下游版本明确依赖时，才应单独立项接线。

## 6. 权限体系没有统一重构

单 Agent 路径继续依赖：

```text
ToolRegistry → tool.validate() → tool.execute()
```

仓库已有 MultiAgent `PermissionGuardLite`，但 v0.05 没有把两套路径重构成通用 PermissionEngine。这样可以避免为 façade 接线重写稳定工具边界。

## 7. Event 不是通用消息总线

- QueryEngine events 通过同步 callback 发射；observer 异常会被隔离，不能改变 Run 终态或卡住后续 submit；
- 可选 Session 接线将 adapter events 写入 v0.04 SessionEvent；
- 没有多消费者、backpressure、持久订阅或 replay；
- QueryEngine sequence 与 SessionEvent sequence 是不同层级，不保证数值相同。

## 8. Recovery 仅上浮，不自动协调

`recovery_required` 被标准化为：

```text
status = blocked
stop_reason = recovery_required
```

QueryEngine 不执行：

- FileWrite reconciliation；
- Bash 结果推断；
- external API reconciliation；
- 自动副作用重试；
- 任意 crash 后继续。

## 9. MultiAgent CLI 未迁移

`paperclaw team` 仍使用现有 `Coordinator` 路径。v0.05 只迁移单 Agent CLI：

```text
paperclaw <task>
paperclaw agent <task>
```

没有证据证明 MultiAgent 需要统一 QueryEngine 前，不应扩大范围。

## 10. 流式与后台任务未实现

不支持：

- streaming model delta；
- background shell；
- 实时 stdout / stderr；
- RuntimeEventBus；
- Offline Replay；
- LangSmith / OpenTelemetry exporter。

这些属于独立候选能力，不能以“完善 Harness”为理由一起加入。
