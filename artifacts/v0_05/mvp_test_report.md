# PaperClaw v0.05 MVP Test Report

> 判定：**GO**
> 日期：2026-07-15
> 验证分支：`codex/v0.05-queryengine-mvp`
> Pull Request：#1

## 1. 独立 CI 结果

最终代码与确定性演示在 GitHub Actions CI run `29352667961` 中通过：

```text
pytest on Windows: success
ruff lint: success
```

环境：

- Windows Server 2025 GitHub-hosted runner；
- Python 3.12；
- 完整仓库 `python -m pytest -q`；
- Ruff 高信号规则 `E9,F63,F7,F82`。

机器可读 pytest report-log 统计：

```text
364 tests passed
0 failed
0 errors
```

其中与 v0.05 QueryEngine、adapter、CLI 和演示直接相关的测试共 18 个，全部通过。

## 2. Gate 矩阵

| 编号 | 场景 | 证据 | 结果 |
|---|---|---|---|
| M05-01 | submit | `test_query_engine.py`：唯一 run_id、executor request | PASS |
| M05-02 | completed | 结构化 `RunResult`、唯一 `run.completed` | PASS |
| M05-03 | executor failure | exception → `failed/executor_failed` + stable code | PASS |
| M05-04 | contract violation | executor 超 limits 报告被拒绝 | PASS |
| M05-05 | validation deny | `test_query_engine_runtime_boundaries.py`：底层工具未执行，`permission.denied` 可见 | PASS |
| M05-06 | budget | model/tool wrappers 在底层调用前硬拦截；step budget 映射正确 | PASS |
| M05-07 | cooperative stop | 模型返回后的下一工具边界停止，工具未执行 | PASS |
| M05-08 | event order | sequence 单调，terminal event 恰好一个 | PASS |
| M05-09 | recovery required | `recovery_required` 保持为 `blocked` | PASS |
| M05-10 | compatibility | `paperclaw agent` 与旧式 `paperclaw <task>` 均走 QueryEngine 并通过 | PASS |

## 3. 真实调用边界验证

### Model budget

fixture 允许模型给出两个动作，但 `max_model_calls=1`：

- 第一轮 provider call 执行；
- 第二轮在 `ChatModel.complete()` 前被拒绝；
- provider 实际调用次数保持 1；
- 返回 `budget_exhausted / max_model_calls`。

### Tool budget

fixture 连续请求两次同一工具，但 `max_tool_calls=1`：

- 第一工具执行一次；
- 第二次在底层 `validate()` / `execute()` 前被拒绝；
- 工具实际执行次数保持 1；
- 返回 `budget_exhausted / max_tool_calls`。

### Validation refusal

测试工具在既有 `validate()` 路径返回拒绝：

- QueryEngine 不直接调用工具；
- adapter 不绕过 validation；
- 工具 `execute()` 次数为 0；
- `permission.denied` 事件可见。

### Session binding

使用真实 `SQLiteRepository + SessionService`：

- user 与 assistant message 被持久化；
- model adapter event 被持久化；
- terminal `flow.stopped` 存在；
- QueryEngine 无 SQL 依赖。

## 4. 最小演示

测试：

```text
tests/integration/test_v0_05_mvp_demo.py
```

流程：

```text
QueryEngine.submit
→ FakeModel 选择 FileWriteTool
→ 创建 hello.py
→ test-only RunPythonTool 执行文件
→ 模型提交 done
→ completed + structured RunResult
```

确定性证据：

```text
artifacts/v0_05/mvp_demo_trace.json
```

断言：

- 文件真实创建；
- 执行成功；
- 3 次 model call、2 次 tool call；
- 12 个 QueryEngine event 严格单调；
- terminal event 恰好一个；
- 实际 trace 与仓库 fixture 完全一致。

`RunPythonTool` 仅存在于集成测试中，用于跨平台确定性演示，没有扩展生产工具面。

## 5. 首轮失败与修正记录

首轮 PR CI 中 Ruff 通过，pytest 暴露 7 项失败：

1. 两项本次引入问题：CLI 尝试 JSON 序列化 cooperative stop token；
2. 五项既有测试问题：权限测试将 workspace 硬编码为 Unix `/tmp`，在 Windows CI 中不存在。

修正：

- CLI compatibility output 排除运行时 `cancel_event` 对象；
- 权限测试改用 pytest `tmp_path`；
- 未修改 `PermissionGuardLite` 生产逻辑。

修正后的两轮完整 CI 均为 pytest + Ruff success；加入最终演示后再次完整 CI 通过。

## 6. GO 判断

v0.05 满足：

- M05-01–M05-10 全部通过；
- CLI 与测试使用同一 QueryEngine 入口；
- Model / Tool budget 在真实调用前生效；
- 工具继续走 Registry + validation；
- terminal state 唯一且结构化；
- 没有引入 async、EventBus、后台任务或新 Provider 基础设施。

因此判定：**PaperClaw v0.05 QueryEngine MVP = GO**。