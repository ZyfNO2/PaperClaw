# PaperClaw v0.05 QueryEngine MVP Handoff

> 分支：`codex/v0.05-queryengine-mvp`
> 日期：2026-07-15
> 当前判定：**Phase A 完成；v0.05 尚未 GO**

## 1. 本次已完成

### 正式 SOP

新增：

- `Plan/PaperClaw_v0.05_HarnessQueryEngine_MVP_SOP.md`

该文档取代“把 Harness、async、后台 Shell、EventBus、Replay、Provider 统一重构一次完成”的旧路线，冻结为三阶段 MVP。

### 骨架代码

新增：

- `src/paperclaw/harness/contracts.py`
- `src/paperclaw/harness/query_engine.py`
- `src/paperclaw/harness/__init__.py`
- `tests/unit/test_query_engine.py`

已实现：

- `RunLimits`；
- `RunRequest`；
- `ExecutionReport`；
- `RunResult`；
- `AgentRunView`；
- `RunExecutor` Protocol；
- `QueryEngine.submit()`；
- `QueryEngine.get_run()`；
- `QueryEngine.request_stop()`；
- 单 Conversation 顺序 submit；
- cooperative stop token；
- Run 内单调 event sequence；
- 唯一 terminal event；
- executor exception 归一化；
- executor usage 超限检测。

## 2. 已验证内容

在隔离的 Python 3 环境中运行：

```bash
PYTHONPATH=src python -m pytest tests/unit/test_query_engine.py -q
```

结果：

```text
7 passed
```

同时运行了：

```bash
PYTHONPATH=src python -m compileall -q src/paperclaw/harness
```

结果：通过。

未完成的验证：

- 当前执行环境无法 clone GitHub 仓库，因此没有运行仓库全量 pytest；
- 当前环境没有 `ruff` 可执行文件，因此没有运行 Ruff；
- 以上两项必须在 Phase B 开始前由 CI 或本地 worktree 补跑。

## 3. 当前实现边界

### 已完成的是 façade，不是生产 adapter

`QueryEngine` 当前依赖注入 `RunExecutor`。单元测试使用 Stub executor，尚未连接真实 `AgentRuntime`。

不得把当前状态描述为：

- CLI 已迁移；
- Context / Session 已接线；
- 模型和工具预算已在真实调用前拦截；
- PermissionGuard 已接入；
- v0.05 已 GO。

### 权限事实

当前仓库没有独立的可注入 `PermissionGuard`。危险命令主要通过工具自身 `validate()` 拒绝。

Phase B 应复用：

```text
ToolRegistry → tool.validate() → tool.execute()
```

不要为了满足旧草案名称临时制造一个空 PermissionGuard。

## 4. 下一步实施顺序

### B1：最小 AgentRuntimeExecutor

新增一个小型 adapter，例如：

```text
src/paperclaw/harness/agent_runtime_executor.py
```

它只负责：

- 接收 `RunRequest`；
- 调用现有 `AgentRuntime`；
- 转发已有 event handler；
- 将现有 shared state 归一化为 `ExecutionReport`；
- 将 stop token 适配为现有 `cancel_event.is_set()`；
- 不修改 QueryEngine 公开接口。

### B2：真实预算前置检查

当前 Agent Runtime 只有 `max_steps`。必须补齐：

- 模型调用前检查 `max_model_calls`；
- 工具调用前检查 `max_tool_calls`；
- 计数包括失败调用；
- 达到上限后不得再进入对应调用；
- 返回 `budget_exhausted`，并保留具体 stop reason。

优先在现有调用边界加入最少字段和检查，不新增通用 Budget Engine。

特别注意：仅在 event callback 中统计并在事后停止不合格，因为那会允许超限调用已经发生。

### B3：Session / Event 接线

仅在 adapter 层决定是否打开或复用 `SessionService`：

- QueryEngine 不得直接访问 Repository 或 SQLite；
- 避免 `SessionService.close()` 与 QueryEngine 重复生成同一层 terminal event；
- QueryEngine `run.*` 与 v0.04 `flow.*` 可以并存，但语义必须清楚；
- `recovery_required` 上浮为 `blocked`，不要在 QueryEngine 中实现 recovery。

### C1：CLI 迁移

只迁移单 Agent 路径：

- 保留 `paperclaw <task>` 和 `paperclaw agent <task>`；
- 保留现有 workspace、max-steps、verbose-events 参数；
- 暂不迁移 MultiAgent Coordinator；
- CLI 输出从 `RunResult` 读取 terminal status，同时可保留兼容的 state/debug 输出。

### C2：集成 Gate

至少补齐：

- 真实 completed；
- model failure；
- tool failure；
- Bash/tool validation deny；
- max_steps；
- max_model_calls；
- max_tool_calls；
- cooperative stop；
- recovery_required → blocked；
- CLI compatibility。

## 5. 不要做的事情

本次 MVP 禁止加入：

- `asyncio` 全栈改造；
- background shell；
- stream / EventBus / backpressure；
- LangSmith、OTel、Replay；
- 通用 Provider Gateway；
- token/cost 计费平台；
- 新 PermissionEngine；
- MultiAgent durability；
- MCP / Plugin / Hook；
- 为未来 TUI 提前扩展公开接口。

## 6. 建议测试命令

```bash
python -m pytest tests/unit/test_query_engine.py -q
python -m pytest tests/unit -q
python -m pytest -q
python -m ruff check src tests
```

Phase B 每完成一个接线点，先跑定向测试，再跑全量回归。

## 7. 完成判定

当前只允许标记：

```text
v0.05 Phase A: DONE
v0.05 MVP: IN PROGRESS
```

只有正式 SOP 的 M05-01–M05-10 全部通过并完成 CLI 演示后，才能改为：

```text
v0.05 MVP: GO
```
