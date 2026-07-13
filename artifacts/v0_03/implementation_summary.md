# PaperClaw v0.03 实现摘要

## 目标

引入 Coordinator / Worker / Reviewer 三角角色模型，实现可控任务拆分、并行执行、作用域隔离与独立验收。

## 本次落地

- 新增 `paperclaw.multiagent` 包：
  - `contracts.py`：AgentTask、WorkerResult、AgentMessage、FileLease、ReviewFinding、TeamBudget、TeamStopReason 等结构化契约。
  - `coordinator.py`：团队状态 owner、DAG 验证、并行调度、结果汇总、Reviewer 调用、Fix-Review 闭环、团队预算聚合与取消级联。
  - `worker.py`：基于现有 AgentRuntime 的作用域包装，输出 WorkerResult 并上报 step / model_call / tool_call 计数。
  - `reviewer.py`：规则化只读 Reviewer，生成 finding、verdict，并将 blocker/high 转换为 Fix Task。
  - `lease.py`：文件写入 lease 管理，支持 acquire/release/冲突检测。
  - `permissions.py`：PermissionGuardLite，统一工具与路径权限检查，检测 symlink/junction 逃逸。
  - `scoped_tools.py`：带作用域、lease、CAS、TOCTOU 重验证的 file_read/write/edit/grep/bash 包装器。
  - `dag.py`：DAG 校验（无环、依赖存在、具体文件写冲突、acceptance criteria、预算）。
  - `events.py`：EventEnvelope v1 与线程安全事件发射。
- 扩展 CLI：`paperclaw agent`（默认单 Agent）与 `paperclaw team --plan plan.json`（MultiAgent）。
- Worker 状态推导增强：模型 `done` 提议不能覆盖 scope/lease/cas 失败；最终状态确定后再发出 task.completed/failed 事件。
- 在 v0.03 SOP 收尾阶段修复 `ReflectNode` 中事件发射引用了未定义的 `shared` 变量导致的 `NameError`，保证 Verify/Reflection gate 在启用时正常运行。
- 修复 Coordinator 顺序 DAG 执行漏洞：单 Agent 路径现在按拓扑顺序执行全部任务，并在依赖失败时阻塞下游任务。
- 强制 CAS：已存在文件的 `file_write` / `file_edit` 必须携带 `expected_hash`；新文件使用空字符串 sentinel；缺失时返回 `cas_missing` 且文件不被覆盖。
- 团队 model-call 预算：并行调度时悲观预留 `max_steps` 作为 model-call 上限，超额任务被取消，防止并发 Worker 瞬时突破限制。
- Task 级 timeout：`AgentTask.timeout_seconds` 传入 AgentRuntime，`DecideActionNode` 在步骤间检查 wall-clock 超时。
- 绝对 wall-time deadline：`run_deadline` 在 `_run_parallel` 入口计算，所有 fix-review 轮次共享同一截止时间。
- 取消安全：`Worker.cancel()` 不再立即释放 lease；改为杀死注册子进程 + 设置 cancel event；lease 由 `Worker.run()` 在线程自然退出后释放；线程未终止时返回 `unknown_outcome`。

## 兼容性

- 单 Agent CLI 保持向后兼容；未指定子命令时默认进入 agent 路径。
- MultiAgent 包装器复用 v0.01/v0.02 AgentRuntime，Verify / Reflection gate 通过 `enable_verification_gate` 参数透传。

## 风险与现实观察

- 当前 DAG 写冲突只检测具体文件路径 / expected_artifacts 重叠；共享目录由运行时 lease 保护。
- Reviewer 为规则实现，Fix Task 闭环已落地但复杂语义判断需要后续版本结合真实模型。
- 测试在 Windows 上需设置 `TEMP`/`TMP` 环境变量到本地可写目录（如 `g:\PaperClaw\tmp\pytest_temp`）绕过系统临时目录权限限制；`--basetmp` 参数在 pytest 9.x 不被支持。

## 测试基线

- 全量命令：`$env:TEMP="g:\PaperClaw\tmp\pytest_temp"; $env:TMP="g:\PaperClaw\tmp\pytest_temp"; python -m pytest -q`
- 结果：`101 passed, 1 skipped`

## v0.04 前非阻塞债（Review 子代理审查发现）

以下问题不阻断 v0.03 合并，但应在 v0.04 前清理：

- **N1 团队 Trace 丢失 stop_reason**：Worker 本地 `trace_events` 中的 `stop_reason`（timeout / max_steps / cancelled / scope_violation）未合并进 team_state；`task.failed` payload 仅含 `status` 与 `changed_files`。建议在 `task.failed` payload 中补 `stop_reason`，或在 Worker 退出时转发关键事件。
- **N2 provider/contract_id/model 字段缺失**：`model_call` 事件硬编码 `model="decide"`，团队事件无 `provider`、`contract_id`。属于已知债，影响可解释性。
- **N3 max_wall_time_seconds=0 语义不一致**：`max_wall_time_seconds=0` 会导致立即 BUDGET_EXHAUSTED（deadline = 当前时刻），而 `timeout_seconds=0` 表示禁用。两者对 0 的语义相反，建议统一为"0 = 禁用"或在文档明确 `max_wall_time_seconds` 不接受 0。
- **N4 TeamStopReason.TIMEOUT/CANCELLED 为死代码**：Coordinator 从未把 `stop_reason` 设为这两个值；Task timeout 映射为 `WorkerStatus.FAILED`，外部取消走 `_cancelled_task_ids`。建议要么产出真实的 TIMEOUT/CANCELLED 团队停止原因，要么从契约删除死枚举。
- **N5 预留 model-call 上限未覆盖 Reflection 轮**：并行调度时用 `capped_task.max_steps` 同时作为 step 和 model-call 预留上限，但启用 Verify Gate 时 ReflectNode 失败会额外调用 `model.complete`，存在有界超支。Worker 计数器事后校正总额，团队总账最终正确。
- **N8 缺少 timeout_seconds=0 legacy 回退路径的显式测试**：代码层面向后兼容正确（`if timeout and timeout > 0` 守卫），但没有测试断言"传 0 时不会因 timeout 停止"。建议补单测锁定该行为。
- **N9 _cancel_active_worker 在主循环内重复触发**：每个调度 tick 都会对仍 alive 的被取消 task 重新调用 `_cancel_active_worker`，每次 `thread.join(timeout=10)` 阻塞主调度线程最多 10s。建议在首次 cancel 后把该 task 移出 `active_workers` 或标记为"cancelling"避免重复 join。
