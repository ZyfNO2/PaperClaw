# PaperClaw v0.05：最小 Harness 与 QueryEngine MVP SOP 草案

> 状态：**MVP 草案，等待 v0.04 收口后冻结**
> 更新：2026-07-14
> 目标：给现有 PocketFlow Agent Loop 加一个薄的会话级入口，使一次用户提交具有统一 Run、预算、事件、权限入口和结构化结果。
> 原则：v0.05 只做 façade 与接线，不重写已工作的 Model、Tool、Context、Session 和 Flow。

## 目录

- [1. 拆分结论](#1-拆分结论)
- [2. MVP 用户故事](#2-mvp-用户故事)
- [3. 技术路径与选择](#3-技术路径与选择)
- [4. MVP 范围](#4-mvp-范围)
- [5. 最小架构与契约](#5-最小架构与契约)
- [6. 最小运行规则](#6-最小运行规则)
- [7. 实施阶段](#7-实施阶段)
- [8. 测试与 Gate](#8-测试与-gate)
- [9. 演示与交付](#9-演示与交付)
- [10. 后续增强边界](#10-后续增强边界)
- [11. 风险预案](#11-风险预案)
- [12. 既有实现参考](#12-既有实现参考)

---

## 1. 拆分结论

旧版 v0.05 同时要求：

- async QueryEngine；
- AgentRun、Budget、Cancellation；
- 完整 ToolExecutor 与 PermissionEngine；
- Async ModelGateway 与 normalized usage；
- ShellTaskManager、后台任务、stream、process tree kill；
- RuntimeEventBus、Backpressure；
- Local TraceStore、Replay、LangSmith exporter；
- 429、timeout、DB failure、consumer lag fault injection。

这些至少属于五个独立系统。v0.05 现在只验证：

> 现有能力能否通过一个稳定、薄、可测试的 QueryEngine 入口运行，而不让 CLI、TUI 或 domain 直接拼接 Runtime 内部模块。

---

## 2. MVP 用户故事

```text
用户提交“创建 hello.py，运行并验证”
→ QueryEngine 创建 AgentRun
→ 加载 v0.04 Context / Session
→ 调用现有 PocketFlow FlowRunner
→ Tool 调用继续经过现有 Registry / PermissionGuard
→ 达到 done、failed、blocked 或 budget_exhausted
→ 返回结构化 RunResult
→ CLI 与测试读取同一结果和事件
```

附加安全演示：危险命令被现有 PermissionGuard 拒绝，QueryEngine 不能绕过该结果。

---

## 3. 技术路径与选择

| 路径 | 做法 | 优点 | 风险 |
|---|---|---|---|
| A：完整 Harness 重构 | 立即异步化 Model、Shell、Tool、Event 和 Session | 长期统一 | 改动面大，难区分 Runtime 收益与重构问题 |
| B：薄 QueryEngine façade | 组合现有 Protocol，只补 Run / Event / Budget / Result | 可快速验证、向后兼容 | 暂不支持流式和后台任务 |

采用方案 B。

不在 v0.05 为了“看起来像 Claude Code”重写整个执行栈。真正的工程价值是稳定边界和可验证接线，而不是类的数量。

---

## 4. MVP 范围

### 4.1 必做

- 一个 Conversation 内顺序处理 `submit()`；
- 每次 submit 创建唯一 `AgentRun`；
- 注入现有 ModelAdapter、FlowRunner、ToolRegistry、PermissionGuard、ContextBuilder、SessionService；
- 复用现有 PocketFlow 控制流；
- 最小 RuntimeEvent；
- `max_steps`、`max_model_calls`、`max_tool_calls`；
- 节点边界的 cooperative stop；
- 统一 `RunResult` 与 `stop_reason`；
- Tool / Permission 结果原样回流；
- CLI 与测试走同一个 QueryEngine 入口；
- 保持 v0.01–v0.04 公共接口兼容。

### 4.2 不作为 v0.05 Gate

- 将全部代码改成 `asyncio`；
- streaming model delta；
- background Bash；
- 实时 stdout / stderr stream；
- Windows process-tree 强制取消；
- `allow_session` / `deny_session` 权限缓存；
- 完整 CommandClassifier；
- 多 Provider capability negotiation；
- token / cache / reasoning / cost 统一计费；
- 中央 RetryPolicy、429 backoff；
- EventBus 多消费者与 backpressure；
- Offline Replay；
- LangSmith / OpenTelemetry exporter；
- Agent / RAG Eval；
- MCP、Plugin、Hook；
- 并发 submit 或多用户。

这些能力统一进入 v0.05.1 增强候选池或既定 v0.07。

---

## 5. 最小架构与契约

### 5.1 组件关系

```text
CLI / Test / future TUI
          ↓
      QueryEngine
          ↓
       AgentRun
          ↓
  existing FlowRunner
    ├── ModelAdapter
    ├── ToolRegistry
    ├── PermissionGuard
    ├── ContextBuilder
    └── SessionService / EventSink
```

QueryEngine 只负责生命周期编排，不直接：

- 读写业务文件；
- 拼 Prompt；
- 执行 Shell；
- 判断检索关键词；
- 访问数据库表；
- 实现 SeededResearch 规则。

### 5.2 最小公开接口

```python
class QueryEngine:
    def submit(self, text: str, *, limits: RunLimits | None = None) -> RunResult: ...
    def get_run(self, run_id: str) -> AgentRunView: ...
    def request_stop(self, run_id: str, reason: str = "user_requested") -> bool: ...
```

MVP 可以保持同步。`request_stop()` 只保证在下一个 Node / Tool 边界生效，不承诺中断正在运行的模型请求或子进程。

### 5.3 最小数据契约

```python
@dataclass(frozen=True)
class RunLimits:
    max_steps: int = 20
    max_model_calls: int = 10
    max_tool_calls: int = 20

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

允许状态：

```text
running
completed
failed
blocked
stopped
budget_exhausted
```

禁止加入没有真实路由语义的状态名。

### 5.4 最小事件

```text
run.started
model.started
model.completed / model.failed
tool.started
tool.completed / tool.failed
permission.denied
run.completed / run.failed / run.stopped
```

沿用已有 `EventSink` 和单调 sequence。v0.05 不新建通用消息总线。

---

## 6. 最小运行规则

### 6.1 Budget

- 每次进入模型前检查 `max_model_calls`；
- 每次执行工具前检查 `max_tool_calls`；
- 每个 Flow step 前检查 `max_steps` 和 stop request；
- 超限返回 `budget_exhausted`，不能伪装成 failed 或 completed；
- 不在本版本加入 wall-time、token cost 和 monetary cost budget。

### 6.2 Permission

- QueryEngine 不直接调用工具实现；
- Tool 调用必须沿现有 Registry / scoped wrapper / PermissionGuard 路径；
- deny 必须形成结构化事件和 observation；
- 模型不得通过改写 Prompt 覆盖 deny；
- v0.05 不实现交互式 ask UI。

### 6.3 Stop 与错误

- cooperative stop 只在安全边界检查；
- 正在运行的同步模型或 Shell 不承诺立即取消；
- Model / Tool exception 转成 `run.failed` 和稳定 error code；
- `recovery_required` 从 v0.04 原样上浮为 blocked，不由 QueryEngine 自动修复；
- QueryEngine 不拥有 retry 权，MVP 默认不自动重试外部副作用。

---

## 7. 实施阶段

### Phase A：Façade 与契约

- [ ] 定义 `RunLimits`、`RunResult`、`AgentRunView`；
- [ ] 实现 `QueryEngine.submit/get_run/request_stop`；
- [ ] 完成依赖注入；
- [ ] 单元测试确认 QueryEngine 不直接访问 Tool / SQLite 实现。

### Phase B：现有 Runtime 接线

- [ ] 接入 FlowRunner、Context 与 Session；
- [ ] 接入 EventSink；
- [ ] 接入基本预算和 cooperative stop；
- [ ] 接入现有 PermissionGuard；
- [ ] 归一化错误与 stop reason。

### Phase C：演示与回归

- [ ] CLI 切到 QueryEngine 入口；
- [ ] 完成 create / run / verify 演示；
- [ ] 完成 permission denied 与 budget exhausted 演示；
- [ ] 运行相关回归；
- [ ] 输出最小 artifacts 并完成 Review。

三个 Phase 之外的新模块一律进入候选池。

---

## 8. 测试与 Gate

| 编号 | 场景 | 通过标准 |
|---|---|---|
| M05-01 | submit | 创建唯一 run_id 并调用现有 FlowRunner |
| M05-02 | completed | 返回结构化 RunResult 和 completed event |
| M05-03 | model failure | 返回 failed，不丢 error code |
| M05-04 | tool failure | observation 与 Run 状态一致 |
| M05-05 | permission deny | Tool 不执行，deny 事件可见 |
| M05-06 | step budget | 达到上限后 budget_exhausted |
| M05-07 | cooperative stop | 下一安全边界停止并保留 stop_reason |
| M05-08 | event order | sequence 单调且 terminal event 唯一 |
| M05-09 | recovery required | v0.04 blocked 状态原样上浮 |
| M05-10 | compatibility | 既有 CLI / integration 关键路径不回归 |

### GO

- M05-01–M05-10 通过；
- CLI 与测试使用同一 QueryEngine；
- 所有 Tool 调用仍经过权限路径；
- terminal state 唯一且结构化；
- 一条用户任务可演示；
- 没有为了 MVP 引入新的异步框架、消息总线或 Provider 抽象。

### NO-GO

- QueryEngine 直接执行 Tool / Shell；
- Permission 可被绕过；
- 超预算仍继续模型或工具调用；
- completed 没有 terminal event；
- 为接入 QueryEngine 重写现有稳定 Flow；
- 把 cooperative stop 宣称成进程级强制取消。

---

## 9. 演示与交付

### 演示

```text
query_engine.submit("创建 hello.py，运行并验证")
→ completed + structured RunResult

query_engine.submit("执行被禁止的命令")
→ permission.denied + blocked/failed

query_engine.submit("持续循环", max_steps=2)
→ budget_exhausted
```

### 交付物

```text
artifacts/v0_05/
├── query_engine_contract.md
├── mvp_test_report.md
├── mvp_demo_trace.json
├── known_limitations.md
└── implementation_summary.md
```

不要求本版本生成 cancellation、replay、LangSmith、background shell 等未实现报告。

---

## 10. 后续增强边界

后续候选见：

[`PaperClaw_v0.05.1_Harness增强候选池.md`](PaperClaw_v0.05.1_Harness增强候选池.md)

Trace / Replay / Eval 仍归 v0.07，不因 Harness 已有事件就提前塞入 v0.05。

---

## 11. 风险预案

| 风险 | 预案 |
|---|---|
| QueryEngine 变 God Object | 只依赖 Protocol，禁止直接 Tool / SQL |
| 为统一接口重写现有模块 | adapter 优先；无法适配时记录债务 |
| 同步执行被误称可取消 | 明确 cooperative boundary |
| Event 概念重复 | 复用 EventSink，不创建第二套 EventBus |
| Permission 被 façade 绕过 | bypass test 作为硬 Gate |
| MVP 又加入 exporter / replay | 直接登记 v0.05.1 或 v0.07 |
| 状态过多 | 只保留有真实路由的六种状态 |

---

## 12. 既有实现参考

| 参考项目 | 必读路径 | 借鉴目标 | 禁止照搬 |
|---|---|---|---|
| PaperClaw | `src/paperclaw/runtime/flow_runner.py` | 现有 PocketFlow 执行入口 | 新建第二套 Flow |
| PaperClaw | `src/paperclaw/context/session.py` | SessionService 接线 | QueryEngine 直接写表 |
| PaperClaw | `src/paperclaw/tools/registry.py` | ToolRegistry 边界 | QueryEngine 直接实例化 Tool |
| PaperClaw | `src/paperclaw/multiagent/permissions.py` | 现有 PermissionGuard 行为 | 在 MVP 重写完整 PermissionEngine |
| AutoResearchClaw | `researchclaw/pipeline/runner.py` | runner 生命周期与 stop reason | 复制 23-stage pipeline |
| AutoResearchClaw | `researchclaw/llm/client.py` | Model response / error adapter 思路 | 搬入同步 fallback 链和多 Provider 重构 |
| AutoResearchClaw | `researchclaw/server/websocket/events.py` | UI 消费稳定事件 | 在 MVP 建 WebSocket server |
| PaperAgent | `apps/api/app/services/retrieval/tool_orchestrator.py` | orchestrator 不拥有 adapter 实现 | 把 Retrieval Query 混入 QueryEngine |

执行前记录参考仓库 commit / worktree。Implementation Summary 必须说明哪些已有 PaperClaw 模块被复用、哪些长期设计被主动延期。
