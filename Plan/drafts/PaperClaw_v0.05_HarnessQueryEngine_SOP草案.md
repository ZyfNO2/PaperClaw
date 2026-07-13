# PaperClaw v0.05：Harness Engineering 与 QueryEngine SOP 草案

> 状态：SOP 草案，待 v0.04 完成后冻结  
> 前置：v0.04 Context Engineering 通过验收  
> 目标：把 Agent Loop、Context、工具、权限、任务、Trace、预算和 Eval 组装为可替换、可测试的 Agent Harness

> 执行前参考：[`PaperClaw_参考项目与可复用模块索引.md`](../../docs/reference/PaperClaw_参考项目与可复用模块索引.md) 中 v0.05 清单，重点阅读 AutoResearchClaw `pipeline/runner.py`、`llm/client.py`、WebSocket events / MCP registry，以及 PaperAgent retrieval orchestrator。

## 目录

- [Harness 定位与核心模块](#1-harness-的定位)
- [Shell、Event 与 Permission](#3-bashtool-在-harness-中的归属)
- [运行模式与最小演示](#6-harness-模式)
- [技术选型、遗漏与风险](#10-技术选型草案)
- [实施阶段、Gate 与交付](#13-初步实施阶段)

## 1. Harness 的定位

Harness 不是新的 Agent 范式，而是包围模型与 Agent Loop 的工程运行环境：

```text
Model
  被 Harness 管理
    ├── Context
    ├── Tools
    ├── Permission
    ├── Budget
    ├── Runtime Event
    ├── Session
    ├── Shell Task
    ├── Trace / Replay
    └── Eval
```

它让 ReAct、Reflection、MultiAgent 和未来 Research Agent 共享同一套运行时能力。

## 2. 核心模块候选

```text
QueryEngine
AgentRun
ModelGateway
ToolRegistry
ToolExecutor
PermissionEngine
BudgetController
RuntimeEventBus
SessionStore
ShellTaskManager
TraceStore
ReplayRunner
EvalRecorder
```

QueryEngine 详细讨论见：

- [`PaperClaw_QueryEngine设计讨论稿.md`](../../docs/desgin/PaperClaw_QueryEngine设计讨论稿.md)
- [`PaperClaw_v0.07_TraceReplay与分层Eval_SOP草案.md`](PaperClaw_v0.07_TraceReplay与分层Eval_SOP草案.md)

## 3. BashTool 在 Harness 中的归属

BashTool 的长期形态应拆为：

```text
BashTool
    负责工具 Schema 和 Agent 入口

CommandClassifier
    判断 read/search/list/test/build/package/git/write/destructive

PermissionEngine
    allow / deny / ask / sandbox

ShellTaskManager
    spawn / stream / timeout / background / cancel / notify

CommandResultNormalizer
    stdout / stderr / exit_code / task metadata
```

不能让 BashTool 单个类同时拥有命令解析、安全策略、任务管理、UI 和 Session。

## 4. Runtime Event

所有能力通过统一事件流暴露：

```text
run.started
context.compiled
model.started/completed
tool.proposed/started/completed/failed
permission.requested/decided
verification.completed
reflection.completed
agent.spawned/completed
task.started/completed
shell.backgrounded/notified/cancelled
run.completed/failed/cancelled
```

事件服务于：

- CLI / TUI；
- Trace；
- Offline Replay；
- Eval；
- 故障复现；
- 面试演示。

## 5. Permission 草稿

```text
allow_once
allow_session
deny_once
deny_session
ask
transform
sandbox
```

策略输入包括：工具、副作用、命令语义、路径、Agent Role、Task Scope、历史拒绝和当前模式。

Prompt 只引导模型，Permission Engine 在执行层强制边界。

## 6. Harness 模式

```text
full_agent
lite_chain
offline_replay
```

三种模式共享顶层事件和结果契约，只改变联网、Reflection、自主工具选择和 fixture 来源。

## 7. 最小演示

- 同一 Agent Loop 可由 CLI 和测试 Harness 驱动；
- 一次 Bash 长测试可以取消并记录 stop reason；
- 高风险命令触发 Permission Request；
- Offline Replay 不调用真实模型和网络；
- Trace 可以重建 action / observation 顺序；
- 替换 Model Provider 不修改 Agent Loop。

## 8. 草稿验收方向

- Runtime 与具体 UI 解耦；
- 所有工具调用都经过 ToolExecutor 和 Permission；
- 所有 Run 受多维预算控制；
- Event sequence 稳定且可序列化；
- cancel 能传递到模型、Shell 和子 Agent；
- Replay 可复现实质性决策输入；
- Provider、Tool、Session adapter 可替换；
- Harness 不包含 SeededResearch 业务判断。
- LangSmith 只作为可选 Trace / Eval adapter；内部 TraceStore 和 Offline Eval 不依赖其在线服务。

## 9. 暂不设计

- 完整 MCP；
- 分布式 Worker；
- OS 级 Sandbox 选型；
- 云端多租户；
- 生产级计费；
- 插件市场；
- 最终后台任务 UI。

等 v0.04 的 Context / Session 契约稳定后，再编写正式 SOP。

## 10. 技术选型草案

| 能力 | 推荐选型 | 边界 |
|---|---|---|
| QueryEngine | 原生 `asyncio` 会话级 orchestrator | 一个 engine 对应 conversation；一次 submit 对应 AgentRun |
| Event | 内部 typed dataclass event + sequence | 参考 OpenTelemetry trace/span，但暂不硬依赖 OTel SDK |
| Export | Json / SQLite / LangSmith adapter | Export 失败不阻塞 Runtime |
| Permission | Policy rules + explicit decision cache | Prompt 不拥有最终权限 |
| Shell Task | `asyncio.create_subprocess_*` + TaskManager | 前台、后台、cancel、timeout、stream 统一 |
| Provider | Async ModelGateway protocol | streaming、usage、cancel、retry、structured output |
| Config | typed config + environment overlay | Secret 与普通配置分离 |
| Retry | 中央 RetryPolicy | Node 不得无限自行 retry |

## 11. 用户尚未覆盖的关键问题

- **事件 Schema version**：TUI、Replay、LangSmith 和 Eval 都依赖 Event，字段变化必须可兼容。
- **cancel propagation**：取消必须到达模型流、Bash 子进程、Worker、Permission wait 和数据库写入。
- **exactly-once 幻觉**：本地系统很难真正保证 exactly-once，应设计 at-least-once + idempotency。
- **Permission TOCTOU**：判断允许后到执行前，路径或文件可能改变，需要执行时重验。
- **Shell operator parsing**：PowerShell 与 POSIX Bash 语法不同，不能用同一字符串规则假装安全。
- **Provider usage 一致性**：不同 Provider 的 token、reasoning、cache 和 cost 字段不同，需要 normalized usage。
- **Backpressure**：模型 delta、Shell 输出和多个 Worker 事件可能淹没 TUI / TraceStore。
- **Secret redaction**：输入、环境、命令输出和 exception 都可能泄露 secret。
- **Hook / Plugin trust**：未来 Skill、MCP、Hook 不能默认可信，需要 provenance 和 capability scope。

## 12. 风险推演与预案

| 场景 | 后果 | 预案 |
|---|---|---|
| LangSmith 不可用 | Trace export 阻塞任务 | 本地 TraceStore 为事实源；异步 exporter + bounded queue |
| 用户取消但 Bash 子进程残留 | 资源泄露、继续修改文件 | Windows Job Object / process tree kill adapter；超时后记录 cleanup_failed |
| Permission allow_session 范围过宽 | 后续危险参数被自动放行 | decision fingerprint 包含 tool、作用域、风险类和参数规范化摘要 |
| Event 消费者过慢 | 内存增长 | 有界队列；delta 合并；关键事件不可丢，低价值流式事件可采样 |
| Provider retry 重复 tool call | 副作用重复 | model call / tool call 唯一 ID；执行前查询结果 ledger |
| QueryEngine 变 God Object | 无法测试和替换 | 只编排 Protocol；工具、Context、Permission、Store 独立 |
| 配置组合爆炸 | 难以复现 | config hash、profile fixture、拒绝未知字段、默认配置单一 |
| Hook 抛异常 | 主 Run 被插件拖死 | Hook timeout、隔离错误、critical/noncritical 分类 |

## 13. 初步实施阶段

1. RuntimeEvent / TraceSpan v1 与兼容策略；
2. QueryEngine、AgentRun、Budget、Cancellation；
3. ToolExecutor、PermissionEngine、decision cache；
4. Async ModelGateway 与 normalized usage；
5. ShellTaskManager 和 process tree cleanup；
6. Local TraceStore、Replay、Exporter；
7. failure injection：429、timeout、cancel、permission wait、DB failure、consumer lag。

## 14. GO / 降级 / NO-GO

- `GO`：取消可传播、权限不可绕过、事件可重放、Exporter 可故障隔离。
- `降级`：后台 Shell 和 OTel exporter 延后；保留前台 async shell + JSON/SQLite Trace。
- `NO-GO`：QueryEngine 直接执行工具、LangSmith 成为唯一事实源、cancel 后子进程继续、Permission 仅存在于 Prompt。

## 15. 预期交付

```text
artifacts/v0_05/
├── runtime_event_v1.md
├── query_engine_contract.md
├── permission_matrix.md
├── cancellation_report.md
├── replay_report.md
└── implementation_summary.md
```
