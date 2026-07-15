# PaperClaw v0.06.3 MultiAgent TUI Panel SOP

> 状态：自动化实现与 Windows CI 完成；Draft PR #16；等待物理终端真实模型验收
> 日期：2026-07-16

## 1. 目标

在不把 MultiAgent Runtime 内部对象直接暴露给 Textual 的前提下，为单次 `Coordinator` 执行提供可运行、只读、可审计的团队状态面板。

数据边界固定为：

```text
Coordinator EventEnvelope v1
→ TeamViewReducer / TeamViewSnapshot
→ TeamApp widgets
```

TUI 不解析 Worker prompt、objective、acceptance criteria、工具输出、隐藏 reasoning 或 changed-file 名称。

## 2. 用户故事

用户从一个既有 team-plan JSON 启动 MultiAgent 执行后，可以在终端中看到：

- team lifecycle 与最终 stop reason；
- task/Worker 的 aggregate 状态；
- completed / failed / blocked / cancelled / running 数量；
- Reviewer verdict 与 fix round；
- Global Verify aggregate 状态；
- 只包含事件类型和安全标识符的生命周期时间线。

用户不能通过该界面强制终止正在执行的 Coordinator，也不能从界面读取任意事件 payload。

## 3. 范围

### 3.1 必须实现

1. 独立 `TeamApp`，通过 worker thread 调用同步 `Coordinator.run()`。
2. `TeamStatus`、`TeamWorkers`、`TeamReview`、`TeamTimeline` 四个只读视图。
3. 所有业务状态只从 `TeamViewSnapshot` 读取。
4. 重复启动保护；运行中拒绝退出，避免假装提供 hard cancel。
5. 宽/窄终端响应式布局。
6. 独立可执行入口：

   ```bash
   python -m paperclaw.tui.team_runner --plan team-plan.json --workspace .
   ```

7. TTY、Textual optional dependency、plan/workspace 输入的 fail-closed 处理。
8. Headless Textual 测试和 plan loader 测试。
9. UI 异常信息不得直接展示任意异常正文。

### 3.2 明确不做

- 不修改现有单 Agent `PaperClawApp`；
- 不修改 `paperclaw` CLI；
- 不实现 DAG 编辑器、Worker 控制按钮、通用 retry 或 task reassignment；
- 不实现 hard cancel、进程树终止或 active process reconnect；
- 不展示 prompt、objective、acceptance criteria、工具输出、隐藏 reasoning 或文件名；
- 不修改 Trace、Provider、Replay、Eval、Exporter 或持久化路径；
- 不声称完成真实 Provider / 真实终端端到端验收。

## 4. 架构约束

### 4.1 Runtime 边界

`TeamApp` 只依赖一个 `CoordinatorLike` protocol 和 `CoordinatorFactory`。生产 runner 负责构造真实 `Coordinator`，测试使用 deterministic fake。

Coordinator callback 只把事件投递回 Textual message loop。状态归约继续由 v0.06.2 `TeamViewReducer` 完成，避免 UI 与 MultiAgent 状态机形成第二套实现。

### 4.2 数据最小化

- Worker panel 可展示：task ID、agent ID、截断 title、status、changed-file count、稳定 reason。
- Timeline 可展示：sequence、event type、agent ID、task ID。
- Timeline 禁止读取或格式化 `payload` 中的任意值。
- 未知事件只显示 unknown marker 和事件类型，不显示 payload。
- 运行时异常只显示异常类型或固定错误码，不显示 `str(exc)`。

### 4.3 生命周期

- mount 后自动启动一次；
- active run 中重复 `R` 被拒绝；
- active run 中 `Q` 被拒绝；
- terminal 后允许重新运行；
- 每次重新运行 reset reducer 和 timeline；
- final `CoordinatorResult` 用于补齐未观察到的终态。

## 5. 验收矩阵

| 需求 | 验证方式 |
|---|---|
| Coordinator 在后台线程运行 | Headless Textual fake Coordinator 测试 |
| aggregate 状态正确 | terminal snapshot 断言 |
| Worker / Reviewer / Global Verify 面板 | widget snapshot / rendered state 断言 |
| 不泄露 objective、goal、reasoning、tool output、文件名 | 敏感 fixture 负断言 |
| 快速 Coordinator 不触发启动竞态 | 等待 terminal projection 的回归测试 |
| active 时拒绝 duplicate run / quit | blocking Coordinator 测试 |
| plan JSON 转换为 runtime contracts | loader 单元测试 |
| no-TUI 在 Provider 初始化前失败 | runner 单元测试 |
| 异常正文不进入 UI | secret-bearing exception 回归测试 |
| Windows 回归与 Ruff | GitHub Actions |

## 6. 验证命令

```bash
python -m pytest tests/unit/test_team_view.py tests/unit/test_team_tui.py tests/unit/test_team_tui_runner.py -q
python -m pytest -q
python -m ruff check . --select E9,F63,F7,F82
```

真实终端验收：

```bash
pip install -e ".[tui]"
python -m paperclaw.tui.team_runner --plan <team-plan.json> --workspace <workspace>
```

真实终端和真实模型测试必须单独记录，不得用 FakeCoordinator 或 headless test 代替。

## 7. 合并策略

PR #16 必须保持 Draft，并堆叠在 PR #15。先使用 `main` 目标运行完整 CI；最终验证完成后可把 base 调整为 `feat/v0.06.2-multiagent-view-adapter`，使审查 diff 只包含 v0.06.3 专属文件。

不得自动合并或删除分支。
