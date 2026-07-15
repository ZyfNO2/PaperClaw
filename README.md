# PaperClaw

PaperClaw 是一个面向 Coding / Research 场景的轻量 Agent Runtime。当前实现重点是用 PocketFlow 风格控制流搭建一个可测试、可解释、可逐步扩展的编码 Agent，而不是直接堆一个重工作流框架。

当前仓库已完成：

- v0.01：最小 ReAct 编码 Agent；
- v0.02：Verify / Reflection Gate 基线；
- v0.03：Coordinator / Worker / Reviewer MultiAgent 分工协作基线；
- v0.04：Context / Session / SQLite MVP 闭环；
- v0.05：最小 Harness / QueryEngine MVP；
- v0.06：Claw TUI MVP 的实现与离线 CI；
- v0.06.1：Safe Session Picker 首切片，真实 Windows Terminal / Live Provider 交互验收仍待完成。

尚未实现的设计项仍保持在 `Plan/` 和 `docs/desgin/` 中，不应视为已交付能力。

## 当前能力

### v0.01：最小 ReAct Loop

- 单步 `Reasoning -> Act -> Observation` 循环；
- 工具：`file_read`、`file_write`、`file_edit`、`grep`、`bash`；
- 工作区路径边界、显式覆盖写入、唯一精确替换；
- 命令超时、输出截断、基础 denylist；
- 非法 JSON、未知 action、工具错误、`max_steps` 有界退出；
- OpenAI-compatible 模型适配器；
- CLI 与 FakeModel 离线回归测试。

### v0.02：Verify / Reflection Gate

- `done` 从直接结束改为 `DoneProposal`；
- feature flag 控制的 Verify / Reflection Gate：`--enable-verification-gate`；
- VerificationPlan / VerificationEvidence / VerificationResult 契约；
- 文件存在、最新内容、验证命令时序检查；
- pytest / 相关命令摘要保留 `exit_code`、时长、截断标记与可解析统计；
- Reflection 只能消费已有 Evidence；
- 重复失败 signature 检测与 Reflection 轮数上限；
- 内存态结构化 trace。

### v0.03：MultiAgent 分工协作

- Coordinator / Worker / Reviewer 三角角色模型；
- `AgentTask` / `WorkerResult` / `AgentMessage` / `ReviewFinding` 结构化契约；
- Task DAG 校验；
- 并行 vs 单 Agent 决策 Gate；
- 最多 3 个 Worker 并发；
- `PermissionGuard Lite` 工具/路径权限检查；
- `FileLease` 文件写入所有权；
- `expected_hash` CAS 检测；
- 独立 Reviewer；
- `paperclaw agent` / `paperclaw team --plan plan.json` CLI。

### v0.04：Context / Session / SQLite MVP

> v0.04 验证 Context 持久化、角色裁剪、确定性压缩和安全恢复边界。

- 不可变 Context / Session / Checkpoint 契约；
- SQLite append-only event log 与单写者 Repository；
- `ContextBuilder` 的 collect → validate → scope → compact → persist；
- `RoleContextView` 角色裁剪；
- `Char4TokenEstimator` 与结构化 compaction；
- required constraint / Evidence ref 保留；
- `CheckpointWriter`、`ResumeCoordinator` 与文件 snapshot 校验；
- unsafe state 返回 `recovery_required`；
- `InstrumentedFlowRunner` 包裹 PocketFlow；
- `NodeRegistry` 与稳定 node ID。

产物：

- `artifacts/v0_04/implementation_summary.md`
- `artifacts/v0_04/test_report.md`
- `artifacts/v0_04/known_limitations.md`
- `artifacts/v0_04/mvp_demo_trace.json`

### v0.05：最小 Harness / QueryEngine MVP

> v0.05 为现有单 Agent Runtime 增加稳定、薄、同步的会话级入口，不重写 PocketFlow、Model、Tool 或 Session。

- `QueryEngine.submit/get_run/request_stop`；
- `RunLimits` / `RunResult` / `AgentRunView`；
- 单 Conversation 顺序 submit；
- Run 内单调 event sequence 与唯一 terminal event；
- `AgentRuntimeExecutor` 生产 adapter；
- `max_steps`、`max_model_calls`、`max_tool_calls`；
- Model / Tool 在真实调用前硬预算检查；
- Tool 调用继续经过 `ToolRegistry → validate → execute`；
- validation refusal 发射 `permission.denied`；
- cooperative stop；
- 可选 v0.04 Repository / SessionService 接线；
- `recovery_required` 标准化为 `blocked`；
- 单 Agent CLI 与测试使用同一 QueryEngine；
- `paperclaw <task>` 旧式入口保持兼容；
- MultiAgent `paperclaw team` 保持原 Coordinator 路径。

v0.05 明确不包含 async 全栈、streaming、后台 Shell、EventBus、Replay、通用 Provider Gateway、新 PermissionEngine 或 MultiAgent durability。

产物：

- `Plan/PaperClaw_v0.05_HarnessQueryEngine_MVP_SOP.md`
- `artifacts/v0_05/query_engine_contract.md`
- `artifacts/v0_05/mvp_test_report.md`
- `artifacts/v0_05/mvp_demo_trace.json`
- `artifacts/v0_05/known_limitations.md`
- `docs/handoff/PaperClaw_v0.05_QueryEngine_MVP_HANDOFF.md`

### v0.06：Claw TUI MVP

> v0.06 是同步 QueryEngine 的可选 Textual 薄客户端。当前自动化验证已完成，真实 Windows Terminal / Live Provider 交互验收仍为 pending。

- `paperclaw tui [task]`；
- optional `textual` dependency；
- `ChatLog`、`PromptInput`、`RunStatus`、`ToolTimeline`；
- `VerificationInspector` 结构化聚合显示；
- Textual Worker thread 包装同步 `QueryEngine.submit()`；
- UI-local 单调事件 reducer，拒绝 stale / duplicate / post-terminal 更新；
- `/help`、`/new`、`/cancel`、`/quit`；
- single active run 与 duplicate-submit 拒绝；
- cooperative stop 边界提示；
- Textual 缺失、无 TTY 或 `--no-tui` 时 CLI fallback；
- 窄终端单列退化；
- TUI widget 不直接执行 Tool、访问 Repository/SQLite 或构造 Prompt。

v0.06 不包含 token streaming、Shell stream/background、Permission Dialog、Context/Trace/Cost Inspector、MultiAgent view、Web UI/API 或强制进程取消。

产物：

- `Plan/PaperClaw_v0.06_Claw_TUI_MVP_SOP.md`
- `artifacts/v0_06/implementation_summary.md`
- `artifacts/v0_06/mvp_test_report.md`
- `artifacts/v0_06/mvp_demo_trace.json`
- `artifacts/v0_06/tui_boundary.md`
- `artifacts/v0_06/known_limitations.md`
- `docs/handoff/PaperClaw_v0.06_TUI_MVP_HANDOFF.md`

### v0.06.1：Safe Session Picker 首切片

> 本切片只重新打开已安全关闭的 conversation。旧 Run 保持 ended，下一次提交创建 fresh Run。

- `paperclaw tui --database <path>` 显式启用 SQLite 持久化；
- `/sessions` 只列出不存在 active Run 的 conversation；
- `/preview <index|conversation_id>` 显示只读消息摘要；
- `/open <index|conversation_id>` 重新验证并打开 conversation；
- picker 使用 `mode=ro` 与 `PRAGMA query_only = ON`；
- selection 本身无写副作用；
- 新提交沿用现有 `AgentRuntimeExecutor -> SessionService -> SQLiteRepository` 路径创建新 Run；
- 无 `--database` 时保持 v0.06 内存行为；
- `--no-tui` 时不打开数据库。

不包含 checkpoint replay、crash reconciliation、active process reconnect，也不自动把历史消息注入模型 prompt。

产物：

- `Plan/PaperClaw_v0.06.1_Safe_Session_Picker_SOP.md`
- `artifacts/v0_06_1/session_picker_contract.md`
- `artifacts/v0_06_1/known_limitations.md`
- `docs/handoff/PaperClaw_v0.06.1_Safe_Session_Picker_HANDOFF.md`

## 安装与测试

安装核心与开发依赖：

```powershell
python -m pip install -e ".[dev]"
python -m pytest -q --basetemp=tmp/pytest
```

只安装可选 TUI：

```powershell
python -m pip install -e ".[tui]"
```

`main` 当前独立 CI 基线：

```text
376 passed
Ruff high-signal checks passed
```

## 运行

CLI 会自动读取仓库根目录 `.env` 中的：

- `PAPERCLAW_API_KEY`
- `PAPERCLAW_BASE_URL`
- `PAPERCLAW_MODEL`
- `PAPERCLAW_TIMEOUT_SECONDS`（可选）

单 Agent：

```powershell
paperclaw agent "创建 hello.py，使其输出 PaperClaw OK，并运行验证" `
  --workspace . `
  --max-steps 8 `
  --max-model-calls 6 `
  --max-tool-calls 8
```

旧式入口：

```powershell
paperclaw "创建 hello.py 并运行验证" --workspace .
```

TUI：

```powershell
paperclaw tui --workspace .
```

启用 SQLite 持久化与 Safe Session Picker：

```powershell
paperclaw tui --workspace . --database paperclaw.db
```

`--database` 的父目录必须已经存在；SQLite 可创建数据库文件，但不会创建缺失的目录。

启动后使用：

```text
/sessions
/preview 1
/open 1
```

启动后自动提交一条任务：

```powershell
paperclaw tui "创建 hello.py 并运行验证" --workspace .
```

显式使用 CLI fallback：

```powershell
paperclaw tui "直接结束并输出 fallback-ok" --no-tui --workspace .
```

关闭 Verify Gate：

```powershell
paperclaw agent "创建 hello.py" --workspace . --no-enable-verification-gate
```

MultiAgent：

```powershell
paperclaw team --plan plan.json --workspace .
```
