# PaperClaw v0.05：最小 Harness 与 QueryEngine MVP SOP

> 版本：v0.05
> 状态：**已完成 / GO（MVP）**
> 更新：2026-07-15
> 前置：PaperClaw v0.04 已完成 / GO
>
> 验证路径：
> ```text
> Phase A/B/C implementation: DONE
> Offline deterministic validation: PASS
> Real LLM acceptance: PASS
> Final SOP closure: GO
> ```
> 目标：为现有单 Agent PocketFlow Loop 提供稳定、薄、可测试的会话级入口，使一次用户提交具有统一 Run、调用预算、事件、停止请求和结构化结果。

## 1. 版本结论

v0.05 采用 **薄 QueryEngine façade**，没有进行完整 Harness 重构。

本版本证明：

> CLI 与测试可以通过同一个 QueryEngine 入口调用现有 AgentRuntime，同时保持 PocketFlow、Model、ToolRegistry、工具 validation、Session 和文件安全边界。

工程价值由稳定边界与可验证接线衡量，不由类数量、异步化程度或基础设施复杂度衡量。

## 2. MVP 用户故事

```text
用户提交“创建 hello.py，运行并验证”
→ QueryEngine 创建唯一 AgentRun
→ 将 RunLimits 和 cooperative stop token 交给 AgentRuntimeExecutor
→ adapter 调用现有 AgentRuntime / PocketFlow / ToolRegistry
→ Model / Tool 在真实调用前检查预算
→ 工具继续执行既有 validate → execute 路径
→ Runtime 返回 completed / failed / blocked / stopped / budget_exhausted
→ QueryEngine 生成唯一 terminal event
→ CLI 与测试读取同一 RunResult
```

安全故事：工具 validation 拒绝的操作不得执行，拒绝事件必须可见，QueryEngine 不得绕过或重试。

## 3. MVP 范围

### 3.1 已交付

- 单 Conversation 顺序 `submit()`；
- 每次提交生成唯一 `run_id`；
- `RunLimits`、`RunRequest`、`ExecutionReport`、`RunResult`、`AgentRunView`；
- `RunExecutor` adapter 边界；
- `QueryEngine.submit/get_run/request_stop`；
- Run 内单调 event sequence；
- cooperative stop；
- `max_steps`、`max_model_calls`、`max_tool_calls`；
- executor exception 与 contract violation 归一化；
- 每个 Run 唯一 terminal event；
- 最小 `AgentRuntimeExecutor`；
- Model 与 Tool 调用前预算检查；
- ToolRegistry 与工具 validation 复用；
- 可选 v0.04 Repository / SessionService 接线；
- `recovery_required` → `blocked`；
- 单 Agent CLI 迁移；
- 确定性 create / run / verify 演示；
- 真实 LLM create / run / verify 验收；
- 真实 LLM 错误后修复验收；
- 真实 LLM 预算边界验收；
- 手动触发 real-llm-e2e GitHub Actions workflow；
- 脱敏真实运行 artifacts；
- 完整 CI 与 artifacts。

### 3.2 明确非目标

- 全栈 `asyncio`；
- streaming model delta；
- 后台 Bash、实时 stdout/stderr；
- 进程树强制取消；
- 新 PermissionEngine；
- Provider capability negotiation；
- token、cache、reasoning、monetary cost 计费；
- 中央 RetryPolicy；
- EventBus、backpressure、Offline Replay；
- LangSmith / OpenTelemetry；
- Agent / RAG Eval；
- MCP、Plugin、Hook；
- 并发 submit、多用户或分布式 Run；
- MultiAgent CLI 迁移。

## 4. 最小架构

```text
CLI / Test / future TUI
          ↓
      QueryEngine
          ↓
  AgentRuntimeExecutor
          ↓
 existing AgentRuntime / PocketFlow
   ├── budgeted ChatModel wrapper
   ├── ToolRegistry + budgeted Tool wrapper
   ├── tool.validate() → tool.execute()
   └── optional SessionService / EventSink
```

### QueryEngine 负责

- Run ID 与生命周期；
- 顺序 submit Gate；
- limits、stop token 与 event emitter 交付；
- terminal status 归一化；
- executor 契约检查；
- 只读 Run View。

### QueryEngine 不负责

- 直接调用 Model、Tool、Shell 或文件操作；
- 直接访问 SQLite 表或 Repository；
- 拼模型 Prompt；
- 自动重试外部副作用；
- 自动修复 `recovery_required`；
- 实现论文、RAG 或 SeededResearch 领域规则。

## 5. 冻结公开契约

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

允许终态：

```text
completed
failed
blocked
stopped
budget_exhausted
```

`running` 只允许存在于 `AgentRunView`。

## 6. Budget 与停止规则

- 全部 limits 原样传入 executor；
- Model wrapper 在 `ChatModel.complete()` 前检查；
- Tool wrapper 在底层 validation / execution 前检查；
- 达到上限后不进入底层调用；
- validation 已经开始的工具尝试计入 tool call；
- 超限返回 `budget_exhausted`；
- executor 报告计数超过 limits 时 QueryEngine 返回 contract violation；
- `request_stop()` 只设置 cooperative token；
- 不承诺中断已经执行中的同步 provider call 或子进程。

## 7. 最小事件

QueryEngine 生命周期事件：

```text
run.started
run.stop_requested
run.completed
run.failed
run.stopped
```

adapter 事件：

```text
model.started / model.completed / model.failed
tool.started / tool.completed / tool.failed
permission.denied
```

规则：

- 单 Run sequence 严格单调；
- terminal event 恰好一个；
- `blocked`、`stopped`、`budget_exhausted` 使用 `run.stopped` 并在 payload 保留 status；
- QueryEngine event 与 v0.04 SessionEvent 分层存在，不新建消息总线。

## 8. 实施结果

### Phase A：Façade 与契约——DONE

- [x] contracts；
- [x] `submit/get_run/request_stop`；
- [x] 顺序 submit Gate；
- [x] ordered events 与唯一 terminal event；
- [x] exception / contract violation；
- [x] Stub executor tests。

### Phase B：现有 Runtime 接线——DONE

- [x] `AgentRuntimeExecutor`；
- [x] 复用现有 AgentRuntime / PocketFlow；
- [x] model call 前预算；
- [x] tool call 前预算；
- [x] ToolRegistry / validation；
- [x] 可选 SessionService / EventSink；
- [x] `recovery_required` 上浮；
- [x] QueryEngine 公开接口保持不变。

### Phase C：CLI、演示与收口——DONE

- [x] 单 Agent CLI 切到 QueryEngine；
- [x] 保留 `paperclaw <task>` 与 `paperclaw agent <task>`；
- [x] 保留原 shared-state 输出兼容层；
- [x] 增加 model/tool call limit 参数；
- [x] create / run / verify 演示；
- [x] validation deny、budget、stop、recovery、CLI tests；
- [x] 完整 Windows pytest 与 Ruff；
- [x] 输出 `artifacts/v0_05/`。

## 9. Gate

| 编号 | 场景 | 结果 |
|---|---|---|
| M05-01 | submit / unique run | PASS |
| M05-02 | completed / structured result | PASS |
| M05-03 | executor failure | PASS |
| M05-04 | contract violation | PASS |
| M05-05 | validation deny | PASS |
| M05-06 | model/tool/step budget | PASS |
| M05-07 | cooperative stop | PASS |
| M05-08 | event order / unique terminal | PASS |
| M05-09 | recovery required → blocked | PASS |
| M05-10 | CLI compatibility | PASS |
| M05-11 | Real LLM create/run/verify | PASS |
| M05-12 | Real LLM repair loop | PASS |
| M05-13 | Provider budget boundary | PASS |

独立 CI：

```text
GitHub Actions run 29352667961
pytest on Windows: success
ruff lint: success
364 tests passed
```

## 10. 真实 LLM 验收

真实 provider 测试位于：

```text
tests/e2e/test_v0_05_real_llm.py
```

使用标记：

```text
@pytest.mark.real_llm
```

三项验收全部通过：

| 编号 | 场景 | 证据 |
|---|---|---|
| E2E-01 | create / run / verify | `test_real_llm_create_run_verify`：真实 LLM 创建 `hello.py`，通过 `bash` 运行 `python hello.py`，输出匹配 `PaperClaw v0.05 REAL LLM OK.`，`status=completed`，`model_calls=3`，`tool_calls=2`，`terminal_event_count=1` |
| E2E-02 | repair loop | `test_real_llm_repair_after_error`：真实 LLM 先创建含错误的 `hello.py`，观察到失败，修复后再次运行成功，`status=completed` |
| E2E-03 | provider budget boundary | `test_real_llm_model_budget_boundary`：`max_model_calls=1` 时 provider 仅被调用一次，最终 `status=budget_exhausted`，`stop_reason=max_model_calls` |

手动触发工作流：

```text
.github/workflows/real-llm-e2e.yml
```

触发方式：

```text
workflow_dispatch
```

需要 Secrets：

```text
PAPERCLAW_API_KEY
PAPERCLAW_BASE_URL
PAPERCLAW_MODEL
```

重复运行入口：

```text
scripts/run_v0_05_real_llm_acceptance.py
```

该脚本写入的脱敏产物：

```text
artifacts/v0_05/real_llm/
├── run_summary.json
├── event_trace.json
├── generated_files/
│   └── hello.py
├── tool_results.json
├── environment.json
└── redaction_report.md
```

最近一次真实运行摘要（`deepseek-v4-flash`）：

```json
{
  "provider": "openai-compatible",
  "model": "deepseek-v4-flash",
  "status": "completed",
  "stop_reason": "done",
  "model_calls": 3,
  "tool_calls": 2,
  "terminal_event_count": 1
}
```

## 11. 最小演示与交付物

演示：

```text
QueryEngine.submit
→ FileWriteTool 创建 hello.py
→ test-only RunPythonTool 执行
→ done
→ completed + RunResult
```

交付物：

```text
artifacts/v0_05/
├── query_engine_contract.md
├── mvp_test_report.md
├── mvp_demo_trace.json
├── known_limitations.md
├── file_manifest.txt
└── real_llm/
    ├── run_summary.json
    ├── event_trace.json
    ├── generated_files/
    │   └── hello.py
    ├── tool_results.json
    ├── environment.json
    └── redaction_report.md
```

`RunPythonTool` 仅用于跨平台确定性测试，没有加入生产工具面。

## 12. GO 判定

v0.05 已满足：

- M05-01–M05-13 全部通过；
- CLI 与测试使用同一 QueryEngine；
- Model / Tool budget 在真实调用前生效；
- Tool 调用继续经过 Registry / validation；
- terminal state 唯一且结构化；
- 真实 LLM 完成 create/run/verify、repair loop、budget boundary 三项验收；
- 真实运行产物已脱敏归档；
- 手动 real-llm-e2e workflow 就位；
- 没有为 MVP 引入 async、EventBus、后台任务或新 Provider 抽象。

最终判定：**PaperClaw v0.05 QueryEngine MVP = GO**。

后续增强必须从 `artifacts/v0_05/known_limitations.md` 中按真实失败一次选择一个小型用户故事，不得恢复旧版“大 Harness 一次完成”的路线。