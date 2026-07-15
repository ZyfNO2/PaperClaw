# PaperClaw v0.06.2 MultiAgent View Adapter Handoff

## 状态

`IMPLEMENTATION GO / DRAFT PR / WAITING FINAL HEAD CI`

MultiAgent View Adapter 首切片已经实现，并在实现 HEAD `92aebf140109c6bef133f9ad784c5a72e7ab0370` 上通过完整 Windows 离线回归。本文档提交后仍需以最终分支 HEAD 的 CI 为最终证据。

## 仓库与分支

- Repository: `ZyfNO2/PaperClaw`
- Base: `main@725e8a81425efa987f59a6f66ce0021fe7978261`
- Branch: `feat/v0.06.2-multiagent-view-adapter`
- Draft PR: `#15`

## 已完成内容

- 新增 immutable `WorkerView`、`TeamViewSnapshot` 与 `TeamViewUpdate`；
- 新增 `TeamViewReducer`，消费现有 MultiAgent EventEnvelope v1；
- 校验单一 run_id 与严格递增 sequence；
- 拒绝 stale、duplicate、cross-run 和普通 post-terminal event；
- 支持 team/task/review/fix-round/budget/terminal 聚合状态；
- 允许一个后置 `global_verification.completed` 事件调整 effective terminal；
- 新增线程安全 `LiveTeamView.handle_event`，可直接传给现有 Coordinator；
- 新增 `project_coordinator_result`，可由现有 trace/result 重建最终视图；
- unknown event 只推进 sequence，不投影任意 payload；
- 仅保留 changed-file 数量，不保留文件名、目标、Prompt、reasoning 或工具输出。

## 修改和新增的主要文件

- `src/paperclaw/multiagent/team_view.py`
- `tests/unit/test_team_view.py`
- `Plan/PaperClaw_v0.06.2_MultiAgent_View_Adapter_SOP.md`
- `docs/handoff/PaperClaw_v0.06.2_MultiAgent_View_Adapter_HANDOFF.md`

所有文件均为新增文件。没有修改 v0.07–v0.07.6 堆叠分支涉及的 CLI、Trace、Provider、Replay、Eval、Exporter 或 Harness 路径。

## 关键架构决定

1. 首先冻结 UI 无关的 read-side projection，不直接修改 Textual App。
2. Adapter 只消费现有 EventEnvelope v1，不创建第二套 event store。
3. `LiveTeamView` 是 observational consumer，不控制 Worker、Coordinator 或工具执行。
4. Snapshot 只保留聚合事实，未知事件 payload 不进入可见状态。
5. Global Verify 可以作为唯一允许的 post-team-terminal aggregate adjustment，且最多接受一次。

## 已执行测试和 CI

实现 HEAD：`92aebf140109c6bef133f9ad784c5a72e7ab0370`

GitHub Actions run `29450712508` / run #123：

- Environment: Windows Server 2025 / Python 3.12；
- pytest call phase: **403 passed, 0 failed, 0 skipped**；
- pytest exit status: `0`；
- Ruff E9/F63/F7/F82 gate: **PASS**；
- artifact: `pytest-results-29450712508`；
- artifact digest: `sha256:980f4ae7f0681edd9c84dab0bd52d2e3e4ca93b5a85ef221d20e67e1efcc6199`。

测试数量来自 artifact 中 `pytest_reportlog.jsonl` 的 call-phase 记录，不是从 PR 文本推断。

## 未执行或未通过的真实测试

- 未执行物理 TUI 测试：本 PR 没有修改或接线 Textual UI，不能把 adapter 单测冒充真实界面验收。
- 未执行真实 Provider：本模块不调用模型或网络服务。
- 未将 TeamViewSnapshot 接入现有 TUI，因为 `src/paperclaw/tui/` 与 `src/paperclaw/cli.py` 属于 v0.07.x 合并期的高冲突路径。

## 当前已知限制

- 当前是 adapter/contract slice，不包含用户可见的 TUI panel。
- 已有团队事件对 timeout/cancel 的细粒度表达仍受 v0.03 事件源限制。
- Snapshot 不包含 DAG 边结构；只展示任务聚合和 Worker 状态。
- Draft PR 基于 v0.07.x 合并前的 `main`，合并前应更新 base 并重新运行最终 CI。

## 尚未完成事项

- 等待本文档与 SOP 状态更新后的最终 HEAD CI；
- v0.07.x 全部合并后更新 PR base；
- 在没有内容冲突的前提下复跑全量 Windows pytest 与 Ruff；
- 后续以单独小 PR 将 `TeamViewSnapshot` 渲染到 TUI，不应把 UI 接线混入当前 adapter PR。

## 下一位开发者接手步骤

1. 确认 PR #15 仍为 Draft；
2. 等 v0.07–v0.07.6 合并到 `main`；
3. 将分支更新到最新 `main`，不得覆写 v0.07.x 实现；
4. 检查 diff 仍只包含本 Handoff 所列新增文件；
5. 运行下列验证命令；
6. 只有最终 HEAD CI 通过后，才考虑单独创建 TUI wiring PR。

## 建议验证命令

```powershell
python -m pytest -q tests/unit/test_team_view.py --basetemp=tmp/pytest-team-view
python -m pytest -q -m "not real_llm" --basetemp=tmp/pytest
python -m ruff check src/paperclaw tests --select E9,F63,F7,F82 --ignore F821
```

## 最终判定

当前 adapter 切片实现状态：`GO`。

用户可见 MultiAgent TUI panel 状态：`NOT IMPLEMENTED BY DESIGN / DEFERRED UNTIL v0.07.x MERGE`。

PR 状态：`DRAFT / WAITING FINAL HEAD CI AND POST-v0.07.x BASE UPDATE`。
