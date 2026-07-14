# PaperClaw v0.05 QueryEngine MVP Handoff

> 分支：`codex/v0.05-queryengine-mvp`
> Pull Request：#1（Draft）
> 日期：2026-07-15
> 当前判定：**Phase A/B/C 完成；v0.05 MVP = GO**

## 1. 交付结论

v0.05 已从骨架推进到可运行的最小 QueryEngine MVP：

```text
CLI / Test
    ↓
QueryEngine
    ↓
AgentRuntimeExecutor
    ↓
existing AgentRuntime / PocketFlow / ToolRegistry
```

本次没有引入：

- async 全栈；
- EventBus；
- background shell；
- Replay / OTel / LangSmith；
- 通用 Provider Gateway；
- 新 PermissionEngine；
- MultiAgent durability。

## 2. 已完成实现

### Phase A：QueryEngine façade

新增：

- `src/paperclaw/harness/contracts.py`
- `src/paperclaw/harness/query_engine.py`
- `src/paperclaw/harness/__init__.py`

实现：

- `RunLimits` / `RunRequest` / `ExecutionReport`；
- `RunResult` / `AgentRunView`；
- `RunExecutor` Protocol；
- `submit()` / `get_run()` / `request_stop()`；
- 单 active Run；
- cooperative stop token；
- Run 内单调 sequence；
- 唯一 terminal event；
- executor exception / contract violation 归一化。

### Phase B：生产 Runtime adapter

新增：

- `src/paperclaw/harness/agent_runtime_executor.py`

接线：

- 复用现有 `AgentRuntime` 与 PocketFlow graph；
- QueryEngine `run_id` 注入现有 runtime state；
- `AgentRuntime.last_state` 供 compatibility output 与异常后诊断；
- Model wrapper 在真实 provider call 前检查 `max_model_calls`；
- Tool wrapper 在真实 validation / execution 前检查 `max_tool_calls`；
- 工具仍走 `ToolRegistry → validate() → execute()`；
- validation deny 发射 `permission.denied`，不执行工具；
- optional Repository 接入 v0.04 `SessionService`；
- `recovery_required` 保留为 `blocked`；
- `ToolControlFlow` 只用于让 stop/budget 信号穿过 `safe_execute`，不改变普通 Tool error 归一化。

### Phase C：CLI 与演示

单 Agent CLI 已迁移：

```text
paperclaw <task>
paperclaw agent <task>
```

新增参数：

```text
--max-model-calls
--max-tool-calls
```

保留：

- `--workspace`；
- `--max-steps`；
- `--verbose-events`；
- Verify Gate 开关；
- 原 shared-state JSON compatibility output；
- `paperclaw team` 原 Coordinator 路径。

CLI 输出新增：

```json
{
  "query_engine": {
    "run_id": "...",
    "status": "completed",
    "stop_reason": "done",
    "model_calls": 3,
    "tool_calls": 2,
    "last_event_sequence": 12
  }
}
```

## 3. 验证结果

最终代码与确定性演示通过 GitHub Actions CI run `29352667961`：

```text
pytest on Windows: success
ruff lint: success
364 tests passed
0 failed
0 errors
```

v0.05 直接相关测试：18 个，全部通过。

覆盖：

- QueryEngine contracts；
- completed / failed / contract violation；
- ordered events / unique terminal；
- concurrent submit refusal；
- model call hard budget；
- tool call hard budget；
- max_steps；
- validation refusal；
- cooperative stop；
- optional SQLite Session binding；
- `recovery_required → blocked`；
- CLI 新旧入口兼容；
- create / run / verify 集成演示。

## 4. MVP 演示

测试：

```text
tests/integration/test_v0_05_mvp_demo.py
```

流程：

```text
submit
→ FileWriteTool 创建 hello.py
→ test-only RunPythonTool 执行 hello.py
→ done
→ completed RunResult
```

证据：

```text
artifacts/v0_05/mvp_demo_trace.json
```

该 Trace 固定验证：

- 文件真实创建；
- Python 执行成功；
- 3 次 model call；
- 2 次 tool call；
- 12 个事件严格单调；
- terminal event 恰好一个。

测试专用 `RunPythonTool` 没有加入生产工具列表。

## 5. 首轮 CI 发现与修正

首轮 CI：Ruff 通过，pytest 发现 7 项失败。

本次代码问题：

- CLI compatibility JSON 包含 cooperative token，不能序列化。

修正：

- 输出层排除 `cancel_event`，不改变 runtime state。

既有测试问题：

- 5 个 `PermissionGuardLite` 测试硬编码 Unix `/tmp`，Windows CI 无该目录。

修正：

- 改用 pytest `tmp_path`；
- 没有修改 PermissionGuardLite 生产实现。

修正后两轮完整 CI 通过；加入最终演示后仍全绿。

## 6. 当前 artifacts

```text
artifacts/v0_05/
├── query_engine_contract.md
├── mvp_test_report.md
├── mvp_demo_trace.json
├── known_limitations.md
└── file_manifest.txt
```

正式 SOP：

```text
Plan/PaperClaw_v0.05_HarnessQueryEngine_MVP_SOP.md
```

## 7. 仍然存在的边界

必须保留以下表述：

- synchronous single-active-run MVP；
- cooperative stop，不是强制取消；
- CLI 默认不自动创建 SQLite Session；
- ContextBuilder 尚未强制进入旧 Agent Prompt 主路径；
- 单 Agent 继续依赖 Tool validation；
- MultiAgent CLI 尚未迁移；
- 没有 token/cost budget；
- 没有 streaming / background task / EventBus；
- QueryEngine 只上浮 recovery，不做 reconciliation。

详见：

```text
artifacts/v0_05/known_limitations.md
```

## 8. 后续维护规则

v0.05 已 GO，不再继续“顺手完善 Harness”。后续只有满足以下条件才立项：

1. 有可复现真实失败或明确下游阻塞；
2. 一个独立用户故事；
3. 一个主要机制；
4. 可单独 GO / NO-GO；
5. 不依赖两个以上未实现候选包。

可选候选包括：

- CLI Session persistence 装配；
- ContextBuilder 进入 submit Prompt 路径；
- token/cost budget；
- streaming；
- background shell；
- MultiAgent QueryEngine adapter。

这些不能打包为 v0.05 的“尾工”。

## 9. 接手检查

```bash
python -m pytest tests/unit/test_query_engine.py -q
python -m pytest tests/unit/test_agent_runtime_executor.py -q
python -m pytest tests/unit/test_query_engine_runtime_boundaries.py -q
python -m pytest tests/unit/test_query_engine_cli.py -q
python -m pytest tests/integration/test_v0_05_mvp_demo.py -q
python -m pytest -q
python -m ruff check src/paperclaw tests --select E9,F63,F7,F82 --ignore F821
```

接手者不得仅凭 Handoff 宣称能力；以正式 SOP、CI、测试和 artifacts 为准。