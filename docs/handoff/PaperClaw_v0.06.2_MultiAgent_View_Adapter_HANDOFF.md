# PaperClaw v0.07.8 MultiAgent View Adapter Handoff

## 状态

`IMPLEMENTATION GO / DRAFT PR / AUTOMATED CI PASS`

MultiAgent View Adapter 已实现并在当前 v0.07.x 主线上通过完整 Windows 离线回归。正式版本编号现统一为 `v0.07.8`。

## 仓库与分支

- Repository: `ZyfNO2/PaperClaw`
- Formal version: `v0.07.8`
- Base: `main@ec1ecbeaf37c0e6ea85a07c12446b3d8f9b8e409`
- Legacy branch ref: `feat/v0.06.2-multiagent-view-adapter`
- Draft PR: `#15`
- Current HEAD before renumbering docs: `711f3c1a186e20773e7b2bc0705c8fbf842174d3`

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
- legacy path `Plan/PaperClaw_v0.06.2_MultiAgent_View_Adapter_SOP.md`
- legacy path `docs/handoff/PaperClaw_v0.06.2_MultiAgent_View_Adapter_HANDOFF.md`

文件路径保留原编号是为了维持现有 PR 历史；文档正文与 PR 元数据中的正式版本统一为 `v0.07.8`。

## 关键架构决定

1. 首先冻结 UI 无关的 read-side projection，不直接修改 Textual App。
2. Adapter 只消费现有 EventEnvelope v1，不创建第二套 event store。
3. `LiveTeamView` 是 observational consumer，不控制 Worker、Coordinator 或工具执行。
4. Snapshot 只保留聚合事实，未知事件 payload 不进入可见状态。
5. Global Verify 可以作为唯一允许的 post-team-terminal aggregate adjustment，且最多接受一次。

## 自动化验证

GitHub Actions run `29452574020` / run #141：

- Environment: Windows Server 2025 / Python 3.12；
- pytest call phase: **475 passed, 0 failed, 0 skipped**；
- pytest exit status: `0`；
- Ruff E9/F63/F7/F82 gate: **PASS**；
- artifact: `pytest-results-29452574020`；
- artifact digest: `sha256:dbe6ebbc82cbffbbc6e033e45e4b127dc93ae956a4032a0e642b671cf3183f6f`。

测试数量来自 artifact 中 `pytest_reportlog.jsonl` 的 call-phase 记录，不是从 PR 文本推断。

## 未执行或未通过的真实测试

- 未执行物理 TUI 测试：本 PR 没有修改或接线 Textual UI，不能把 adapter 单测冒充真实界面验收。
- 未执行真实 Provider：本模块不调用模型或网络服务。
- 用户可见面板由 v0.07.9 PR #16 提供。

## 当前已知限制

- 当前是 adapter/contract slice，不包含用户可见的 TUI panel。
- 已有团队事件对 timeout/cancel 的细粒度表达仍受现有事件源限制。
- Snapshot 不包含 DAG 边结构；只展示任务聚合和 Worker 状态。

## 尚未完成事项

- Owner review；
- PR #15 合并后再处理堆叠的 v0.07.9 PR #16；
- 若 main 在合并前继续变化，应重新验证 merge ref。

## 下一位开发者接手步骤

1. 确认 PR #15 仍为 Draft、mergeable；
2. 检查 diff 仍只包含本 Handoff 所列新增文件；
3. 运行下列验证命令；
4. 只有用户明确要求时才将 Draft 标为 Ready 或合并；
5. PR #15 必须先于 v0.07.9 PR #16。

## 建议验证命令

```powershell
python -m pytest -q tests/unit/test_team_view.py --basetemp=tmp/pytest-team-view
python -m pytest -q -m "not real_llm" --basetemp=tmp/pytest
python -m ruff check src/paperclaw tests --select E9,F63,F7,F82 --ignore F821
```

## 编号说明

本功能原先以 `v0.06.2` 开发，现正式调整为 `v0.07.8`。旧 branch ref 与文件路径仅作为历史兼容标识。

## 最终判定

当前 adapter 切片实现状态：`GO`。

用户可见 MultiAgent TUI panel：由 `v0.07.9` PR #16 提供。

PR 状态：`DRAFT / AUTOMATED CI PASS / WAITING OWNER REVIEW`。