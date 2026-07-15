# PaperClaw v0.06.2 MultiAgent View Adapter SOP

> 状态：实现完成，等待 Draft PR CI
> 基线：`main@725e8a81425efa987f59a6f66ce0021fe7978261`
> 分支：`feat/v0.06.2-multiagent-view-adapter`
> 冲突策略：不修改 `cli.py`、`tui/`、`trace/` 或任何 v0.07.x 文件。

## 1. 用户故事

用户需要观察 MultiAgent 团队的任务分工和终态，而不是只看到单 Agent 的 ToolTimeline。当前 Coordinator 已经发出稳定 EventEnvelope v1，但没有安全、UI 无关的 team-to-view adapter。

本切片冻结只读投影合同：

```text
Coordinator EventEnvelope v1
             ↓
      TeamViewReducer
             ↓
 immutable TeamViewSnapshot
             ↓
 future TUI / CLI / tests
```

## 2. 实现范围

- `WorkerView`：task id、agent id、截断 title、状态、changed-file 数量、结构化 reason；
- `TeamViewSnapshot`：团队状态、任务计数、Worker 计数、fix round、review verdict、Global Verify aggregate；
- `TeamViewReducer`：严格 run_id 与 sequence 边界；
- stale、duplicate、cross-run 和普通 post-terminal event 拒绝；
- 允许一个后置 `global_verification.completed` 调整 effective terminal；
- `LiveTeamView.handle_event` 可直接传给现有 `Coordinator(event_handler=...)`；
- `project_coordinator_result` 可从现有 trace/result 重建最终视图；
- unknown event 只推进 sequence，不投影任意 payload。

## 3. 安全边界

视图不保存或暴露：

- user goal；
- Worker objective；
- Prompt；
- hidden reasoning；
- 工具输出；
- changed-file 名称；
- 任意未知 payload；
- Repository、SQLite 或 workspace 内容。

只保留 changed-file 数量等聚合事实。

## 4. 明确非目标

- 修改 Textual App 布局；
- 新增 CLI 参数；
- Trace Inspector 重复实现；
- 持久化第二套 team event store；
- Worker 控制、重试或取消；
- DAG 编辑器；
- Web UI/API；
- v0.07 Trace schema 或 exporter 改动。

## 5. 验收矩阵

- [x] team.started / task assigned/completed/failed / review / fix / terminal 可投影；
- [x] stale、duplicate、cross-run、普通 post-terminal event 被拒绝；
- [x] Global Verify aggregate 可在 team terminal 后安全调整一次；
- [x] unknown payload 不进入 snapshot；
- [x] changed-file 名称不进入 snapshot，仅保留数量；
- [x] LiveTeamView 可作为 Coordinator event handler；
- [x] 缺失 terminal event 时可由 CoordinatorResult 防御性收口；
- [ ] GitHub Actions Windows 全量 pytest；
- [ ] Ruff high-signal gate。

## 6. 接线方式

```python
from paperclaw.multiagent.coordinator import Coordinator
from paperclaw.multiagent.team_view import LiveTeamView

team_view = LiveTeamView()
coordinator = Coordinator(
    model_factory,
    workspace,
    event_handler=team_view.handle_event,
)
coordinator.run(goal, tasks)
snapshot = team_view.snapshot
```

v0.07.x 合并后，TUI 只需消费 `TeamViewSnapshot`，无需导入 Coordinator、Worker、Repository、SQLite 或 Trace 实现。
