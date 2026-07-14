# PaperClaw v0.05：最小 Harness 与 QueryEngine MVP SOP

> 版本：v0.05
> 状态：**正式冻结；Phase A 骨架已落地，Phase B/C 待实现**
> 更新：2026-07-15
> 前置：PaperClaw v0.04 已完成 / GO
> 目标：为现有单 Agent PocketFlow Loop 提供一个稳定、薄、可测试的会话级入口，使一次用户提交具有统一 Run、预算、事件、停止请求和结构化结果。

## 1. 版本结论

v0.05 采用 **薄 QueryEngine façade**，不进行完整 Harness 重构。

本版本只验证：

> CLI、测试和未来 TUI 能否通过同一个 QueryEngine 入口调用现有 Agent Runtime，同时保持模型、工具、Context、Session、PocketFlow 和文件安全逻辑的既有边界。

v0.05 不以类数量、异步化程度或基础设施复杂度作为完成标准。

## 2. 当前实现事实

冻结本 SOP 时，仓库中的真实状态是：

- `AgentRuntime` 仍直接运行现有 PocketFlow graph；
- `InstrumentedFlowRunner`、`SessionService`、`EventSink`、`ContextBuilder` 已存在；
- `AgentRuntime` 尚未完整接入上述 v0.04 Runtime 服务；
- 当前危险命令限制主要由 Tool 自身的 `validate()` 执行；
- 仓库中没有可直接注入的独立 `PermissionGuard` 实现；
- 因此 v0.05 不得宣称已经接入不存在的权限引擎。

## 3. MVP 用户故事

```text
用户提交“创建 hello.py，运行并验证”
→ QueryEngine 创建唯一 AgentRun
→ 将 RunLimits 和 cooperative stop token 交给现有 Runtime adapter
→ adapter 调用现有 AgentRuntime / PocketFlow / ToolRegistry
→ Runtime 返回 completed、failed、blocked、stopped 或 budget_exhausted
→ QueryEngine 生成唯一 terminal event
→ 返回结构化 RunResult
→ CLI 与测试读取同一结果契约
```

附加安全故事：工具拒绝的危险操作必须原样上浮，QueryEngine 不得绕过、重试或改写为成功。

## 4. MVP 范围

### 4.1 必做

- 一个 Conversation 内顺序处理 `submit()`；
- 每次提交生成唯一 `run_id`；
- 冻结 `RunLimits`、`RunRequest`、`ExecutionReport`、`RunResult`、`AgentRunView`；
- 冻结 `RunExecutor` 适配边界；
- `QueryEngine.submit/get_run/request_stop`；
- 最小、单调递增的 Run event sequence；
- cooperative stop request；
- `max_steps`、`max_model_calls`、`max_tool_calls` 契约；
- executor exception 和 contract violation 的结构化失败；
- 每个 Run 只能产生一个 terminal event；
- 生产 adapter 复用现有 AgentRuntime、ToolRegistry 和工具校验路径；
- CLI 与测试最终使用同一个 QueryEngine 入口；
- 保持 v0.01–v0.04 关键公共行为兼容。

### 4.2 不作为 v0.05 Gate

- 全栈 `asyncio`；
- streaming model delta；
- 后台 Bash、实时 stdout/stderr；
- 进程树强制取消；
- 独立 PermissionEngine / CommandClassifier 重构；
- Provider capability negotiation；
- token、cache、reasoning、monetary cost 统一计费；
- 中央 RetryPolicy、429 backoff；
- 多消费者 EventBus 与 backpressure；
- Offline Replay；
- LangSmith / OpenTelemetry exporter；
- Agent / RAG Eval；
- MCP、Plugin、Hook；
- 并发 submit、多用户或分布式 Run。

上述能力进入 v0.05.1 候选池或既定后续版本，不得顺手加入本 SOP。

## 5. 最小架构

```text
CLI / Test / future TUI
          ↓
      QueryEngine
          ↓
      RunExecutor
          ↓
 existing AgentRuntime / PocketFlow
   ├── ModelAdapter
   ├── ToolRegistry + tool validation
   ├── ContextBuilder（接线阶段复用）
   └── SessionService / EventSink（接线阶段复用）
```

### 5.1 QueryEngine 负责

- Run ID 和生命周期；
- 顺序 submit 限制；
- limits、stop token 和 event emitter 的交付；
- terminal status 归一化；
- executor 契约检查；
- 只读 Run View。

### 5.2 QueryEngine 不负责

- 直接执行 Tool、Shell 或文件操作；
- 直接访问 SQLite 表或 Repository；
- 拼接模型 Prompt；
- 判断检索关键词；
- 自动重试外部副作用；
- 自动修复 `recovery_required`；
- 实现论文、RAG 或 SeededResearch 领域规则。

## 6. 冻结公开契约

```python
class QueryEngine:
    def submit(self, text: str, *, limits: RunLimits | None = None) -> RunResult: ...
    def get_run(self, run_id: str) -> AgentRunView: ...
    def request_stop(self, run_id: str, reason: str = "user_requested") -> bool: ...
```

```python
@dataclass(frozen=True)
class RunLimits:
    max_steps: int = 20
    max_model_calls: int = 10
    max_tool_calls: int = 20
```

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

允许 terminal status：

```text
completed
failed
blocked
stopped
budget_exhausted
```

`running` 只允许出现在 `AgentRunView`，executor 不得返回 `running` 作为终态。

## 7. 最小事件

QueryEngine 层只冻结：

```text
run.started
run.stop_requested
run.completed
run.failed
run.stopped
```

Runtime adapter 可以转发：

```text
model.started / model.completed / model.failed
tool.started / tool.completed / tool.failed
permission.denied
```

规则：

- sequence 在单个 Run 内严格单调；
- terminal event 恰好一个；
- `blocked`、`stopped`、`budget_exhausted` 使用 `run.stopped`，具体状态保存在 payload；
- QueryEngine event 不替代 v0.04 SessionEvent；Phase B 只做接线，不新建通用消息总线。

## 8. Budget、停止与错误规则

### 8.1 Budget

- QueryEngine 必须把全部 `RunLimits` 原样交给 executor；
- executor 必须在模型或工具调用前做硬预算检查；
- executor 报告的调用次数不得超过 limits；
- 超限必须返回 `budget_exhausted`，不能伪装成 `failed` 或 `completed`；
- QueryEngine 检测到 executor 报告超限时返回 `executor_contract_violation`；
- 本版本不增加 wall-time、token cost 或 monetary cost budget。

### 8.2 Cooperative stop

- `request_stop()` 只设置 cooperative token；
- executor 在现有安全边界检查；
- 不承诺中断正在执行的同步模型请求或子进程；
- 重复 stop request 返回 `False`，不重复发事件。

### 8.3 错误与恢复

- executor exception → `failed / executor_failed`；
- executor 契约违规 → `failed / executor_contract_violation`；
- v0.04 `recovery_required` → `blocked`，QueryEngine 不自动修复；
- QueryEngine 不拥有副作用 retry 权。

## 9. 实施阶段

### Phase A：Façade 与契约——已完成

- [x] 定义 contracts；
- [x] 实现 `QueryEngine.submit/get_run/request_stop`；
- [x] 实现顺序 submit Gate；
- [x] 实现 ordered events 与唯一 terminal event；
- [x] 实现异常和 executor contract violation 归一化；
- [x] 使用 Stub executor 完成骨架测试。

### Phase B：现有 Runtime 接线——待实现

- [ ] 实现最小 `AgentRuntimeExecutor`；
- [ ] 复用现有 `AgentRuntime` 和 PocketFlow graph；
- [ ] 在真实模型调用前检查 `max_model_calls`；
- [ ] 在真实工具调用前检查 `max_tool_calls`；
- [ ] 复用 ToolRegistry 和 Tool validation；
- [ ] 按需接入 v0.04 SessionService / EventSink；
- [ ] 将 `recovery_required` 原样上浮为 blocked；
- [ ] 不改变 QueryEngine 公开接口。

### Phase C：CLI、集成演示与收口——待实现

- [ ] 单 Agent CLI 切到 QueryEngine；
- [ ] 保留现有 CLI 参数和输出兼容层；
- [ ] 完成 create / run / verify 演示；
- [ ] 完成 denied、budget_exhausted、stop 演示；
- [ ] 运行全量回归；
- [ ] 输出 `artifacts/v0_05/`；
- [ ] 独立 Review 后决定 GO / NO-GO。

## 10. 测试与 Gate

| 编号 | 场景 | 通过标准 | 当前状态 |
|---|---|---|---|
| M05-01 | submit | 唯一 run_id，调用 executor | Phase A 已覆盖 |
| M05-02 | completed | 结构化 RunResult，唯一 completed event | Phase A 已覆盖 |
| M05-03 | executor failure | failed，不丢稳定 error code | Phase A 已覆盖 |
| M05-04 | contract violation | 超 limits 的报告被拒绝 | Phase A 已覆盖 |
| M05-05 | permission deny | Tool 不执行，拒绝结果上浮 | Phase B/C 待覆盖 |
| M05-06 | budget | 模型/工具调用前硬拦截 | Phase B/C 待覆盖 |
| M05-07 | cooperative stop | 下一安全边界停止 | Phase A 骨架已覆盖；集成待测 |
| M05-08 | event order | sequence 单调、terminal 唯一 | Phase A 已覆盖 |
| M05-09 | recovery required | blocked 原样上浮 | Phase B/C 待覆盖 |
| M05-10 | compatibility | CLI 和关键集成路径不回归 | Phase C 待覆盖 |

### MVP GO

只有满足以下条件才能宣布 v0.05 GO：

- M05-01–M05-10 全部通过；
- CLI 与测试使用同一个 QueryEngine；
- 所有 Tool 调用仍走既有 Registry / validation 路径；
- 模型和工具预算在调用前生效；
- terminal state 唯一且结构化；
- 未为 MVP 引入 async framework、消息总线或新 Provider 层。

### NO-GO

- QueryEngine 直接执行 Tool、Shell 或 SQL；
- 工具安全校验被绕过；
- 超预算后仍继续调用；
- 同一 Run 产生多个 terminal event；
- 为接线重写稳定 PocketFlow graph；
- 把 cooperative stop 宣称为强制取消；
- Phase A 骨架被错误宣称为完整 v0.05 GO。

## 11. 当前交付物

```text
src/paperclaw/harness/
├── __init__.py
├── contracts.py
└── query_engine.py

tests/unit/test_query_engine.py

docs/handoff/PaperClaw_v0.05_QueryEngine_MVP_HANDOFF.md
```

Phase C 完成后再创建：

```text
artifacts/v0_05/
├── query_engine_contract.md
├── mvp_test_report.md
├── mvp_demo_trace.json
├── known_limitations.md
└── file_manifest.txt
```

不得为了填满目录而提前制造未验证 artifacts。

## 12. 停止条件

出现以下任一情况立即停止扩展并回到本 SOP：

- 需要重写 Model、Tool、Context、Session 或 PocketFlow；
- 一个 adapter 需要三个以上新基础设施模块；
- 无法在调用前执行预算检查；
- SessionEvent 与 QueryEngine event 被强行合并成新 EventBus；
- 为未来 TUI、MCP 或多用户提前增加抽象；
- 新功能无法对应 M05-01–M05-10 中的明确验收项。
