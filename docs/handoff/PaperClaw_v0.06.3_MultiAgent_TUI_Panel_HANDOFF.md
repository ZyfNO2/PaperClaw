# PaperClaw v0.06.3 MultiAgent TUI Panel Handoff

## 状态

`AUTOMATED GO / DRAFT / WAITING PHYSICAL REAL-MODEL TTY ACCEPTANCE`

## 仓库与分支

- Repository: `ZyfNO2/PaperClaw`
- Branch: `feat/v0.06.3-multiagent-tui-panel`
- Draft PR: #16
- Base: `main@ec1ecbeaf37c0e6ea85a07c12446b3d8f9b8e409`
- Dependency: PR #15 / `feat/v0.06.2-multiagent-view-adapter`
- Validated implementation HEAD: `f02193f486cfb44e11e694476be920dac54306c7`

本 Handoff 发布后的文档提交 SHA 与最终文档 HEAD CI 记录在 PR #16 Conversation 中，避免在文档内递归引用自身提交。

## 已完成

- 新增独立 Textual `TeamApp`；
- Coordinator 在 Textual worker thread 中执行；
- EventEnvelope 通过 Textual Message queue 进入 `TeamViewReducer`；
- 展示 team status、Worker/task、Reviewer/fix round、Global Verify 和安全 timeline；
- 宽终端双栏、窄终端垂直布局；
- active run duplicate-start 与 unsafe-quit 拒绝；
- standalone runner 与 JSON plan fail-closed 校验；
- headless Textual、敏感 payload suppression、快速 Coordinator、并发 gate 与 runner tests；
- 任意 Coordinator 异常正文不进入 UI，只显示异常类型和固定 suppression 文案；
- PR #15 与本分支均在不 force-push 的情况下更新到 v0.07.x 最新 main。

## 主要文件

本切片专属文件：

- `src/paperclaw/tui/team_app.py`
- `src/paperclaw/tui/team_widgets.py`
- `src/paperclaw/tui/team_runner.py`
- `src/paperclaw/tui/team.tcss`
- `tests/unit/test_team_tui.py`
- `tests/unit/test_team_tui_runner.py`
- `Plan/PaperClaw_v0.06.3_MultiAgent_TUI_Panel_SOP.md`
- `docs/handoff/PaperClaw_v0.06.3_MultiAgent_TUI_Panel_HANDOFF.md`

PR #16 当前以 `main` 为 base，以便运行完整仓库 CI，因此 diff 还包含前置 PR #15 的四个新增文件。PR #15 合并后，PR #16 的有效审查范围会收缩为上述 v0.06.3 文件。

## 关键架构决定

1. 不修改现有单 Agent `PaperClawApp`，避免把 QueryEngine 与 Coordinator 生命周期混入同一 UI。
2. UI 只消费 PR #15 的 `TeamViewSnapshot`，不读取 Coordinator 私有状态。
3. Timeline 使用白名单，只显示 sequence、event type、agent ID、task ID，不格式化任意 payload。
4. Worker 面板只显示安全投影：截断 title/reason、status 与 changed-file count；不展示文件名。
5. 当前 Coordinator 没有安全取消合同，因此 active run 期间拒绝退出，不伪造 hard-cancel。
6. 为避免重新触碰已稳定的 v0.07 `cli.py`，首切片使用独立 module entry point。
7. Coordinator 异常仅公开异常类型；`str(exc)` 可能包含 Provider、路径或任务内容，必须留在 UI 边界之外。

## 开发中捕获的回归

第一次 Windows CI 暴露了快速 FakeCoordinator 的启动竞态：测试仅等待 `_run_in_flight == False`，可能在 `call_after_refresh` 真正启动前提前通过等待循环，随后在 teardown 时收到迟到事件。

修复后，测试等待稳定的 terminal `TeamViewSnapshot` 与非 active 状态，而不是只观察瞬时布尔值。该回归没有通过增加 sleep 掩盖，而是改为等待业务终态。

随后补充了带 secret-bearing exception text 的 Coordinator fixture，并将 UI 错误边界改为只显示 `RuntimeError` 等异常类型，确认 secret text 不进入 timeline。

## 自动化验证

实现 HEAD `f02193f486cfb44e11e694476be920dac54306c7`：

- GitHub Actions run: `29453180907` / run #146
- Windows Server 2025 / Python 3.12
- pytest call phase: **481 passed, 0 failed, 0 skipped**
- pytest exit status: `0`
- Ruff E9/F63/F7/F82: **PASS**
- artifact: `pytest-results-29453180907`
- artifact digest: `sha256:c01378efa6882b3d7098aa0c443866b1ee60e451b9b2e5d31c942edd2a5201b7`

测试数量和退出状态已从 artifact 中的 `pytest_reportlog.jsonl` 独立解析。

覆盖重点：

- responsive headless mount；
- Worker completed/failed、Reviewer verdict 与 team stop projection；
- changed-file name、goal/objective、tool output、review reasoning 不进入 timeline；
- secret-bearing exception detail 不进入 timeline；
- 快速 Coordinator terminal 投影无启动竞态；
- duplicate run 与 active-run quit rejection；
- valid/invalid team plan；
- `--no-tui` 在 Provider 初始化前 fail-closed；
- v0.07.x 最新 main 上的全仓回归。

## 尚未执行的真实测试

物理 TTY + 真实 Provider MultiAgent 执行未在当前云端环境完成，因此不能声明真实 UI/模型验收通过。

### 操作条件

- Windows Terminal 或其他真实 TTY；
- `pip install -e ".[tui]"`；
- 可用的 OpenAI-compatible Provider 环境配置；
- 一个至少包含两个可并行 task 的 JSON plan；
- 隔离测试 workspace。

### 命令

```powershell
python -m paperclaw.tui.team_runner --plan .\team-plan.json --workspace .\safe-workspace
```

### 检查项

1. 宽屏显示左右 panel；
2. 终端缩窄至 87 列或更少后上下堆叠，无崩溃；
3. Worker status 随事件更新；
4. Reviewer verdict、fix round、Global Verify 在对应事件后显示；
5. terminal 后最终 status/stop reason 正确；
6. active run 按 `R` 不启动第二个 team；
7. active run 按 `Q` 不强退；
8. UI 不出现 goal/objective、完整文件名、tool output、review reasoning 或异常正文；
9. terminal 后按 `Q` 正常退出。

通过标准：以上九项全部满足，且 Coordinator 最终结果与面板一致。失败标准：任何崩溃、重复运行、active-run 强退、状态错位或敏感 payload 泄漏。

应返回：终端录屏或截图、可脱敏 plan、最终终端输出及异常日志。

## 已知限制

- 尚未接入 `paperclaw team --tui`，当前使用 module entry point；
- 没有 Coordinator cancel API；
- 不支持编辑 DAG、控制单个 Worker 或 task reassignment；
- Team events 仍是现有内存事件，不自动写入 v0.07 durable Trace；
- headless Textual 测试不能替代物理终端验收；
- PR 保持 Draft，未自动合并。

## 下一位开发者接手

1. 确认 PR #15 先于 #16 处理，且当前仍 mergeable、CI 通过；
2. 在真实 TTY 完成上述九项验收；
3. 将证据和结论写回本 Handoff；
4. 如需产品级 CLI，在最新 main 上做独立小提交，将 `team --tui` 显式接到 `team_runner`，不要复制 Coordinator 组装逻辑；
5. 重新运行全仓 pytest 与 Ruff；
6. 只有用户明确要求时才将 Draft 改为 Ready 或合并。

## 建议验证命令

```powershell
python -m pytest tests/unit/test_team_view.py tests/unit/test_team_tui.py tests/unit/test_team_tui_runner.py -q
python -m pytest -m "not real_llm" -q
python -m ruff check . --select E9,F63,F7,F82
```
