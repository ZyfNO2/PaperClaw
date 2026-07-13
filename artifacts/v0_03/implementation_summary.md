# PaperClaw v0.03 实现摘要

## 目标

引入 Coordinator / Worker / Reviewer 三角角色模型，实现可控任务拆分、并行执行、作用域隔离与独立验收。

## 本次落地

- 新增 `paperclaw.multiagent` 包：
  - `contracts.py`：AgentTask、WorkerResult、AgentMessage、FileLease、ReviewFinding、TeamBudget、TeamStopReason 等结构化契约。
  - `coordinator.py`：团队状态 owner、DAG 验证、并行调度、结果汇总、Reviewer 调用。
  - `worker.py`：基于现有 AgentRuntime 的作用域包装，输出 WorkerResult。
  - `reviewer.py`：规则化只读 Reviewer，生成 finding 与 verdict。
  - `lease.py`：文件写入 lease 管理，支持 acquire/release/冲突检测。
  - `permissions.py`：PermissionGuardLite，统一工具与路径权限检查。
  - `scoped_tools.py`：带作用域、lease、CAS 保护的 file_read/write/edit/grep/bash 包装器。
  - `dag.py`：DAG 校验（无环、依赖存在、具体文件写冲突、acceptance criteria、预算）。
  - `events.py`：EventEnvelope v1 与线程安全事件发射。
- 扩展 CLI：`paperclaw agent`（默认单 Agent）与 `paperclaw team --plan plan.json`（MultiAgent）。
- Worker 状态推导增强：模型 `done` 提议不能覆盖 scope/lease/cas 失败。

## 兼容性

- 单 Agent CLI 保持向后兼容；未指定子命令时默认进入 agent 路径。
- MultiAgent 包装器复用 v0.01/v0.02 AgentRuntime，Verify / Reflection gate 通过 `enable_verification_gate` 参数透传。

## 风险与现实观察

- 当前 DAG 写冲突只检测具体文件路径/expected_artifacts 重叠；共享目录由运行时 lease 保护。
- Reviewer 为规则实现，Fix Task 闭环标记 TODO，等待 v0.04+ 结合真实模型与更完整状态机。
- 测试在 Windows 上需 `--basetemp=.pytest_tmp` 绕过系统临时目录权限限制。

## 测试基线

- 全量命令：`python -m pytest tests -v --basetemp=.pytest_tmp`
- 结果：`83 passed, 1 skipped`
