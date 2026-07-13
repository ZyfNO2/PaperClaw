# PaperClaw v0.03 冲突测试报告

## 测试环境

- 命令：`python -m pytest -q --basetemp=tmp/pytest`
- 结果：`83 passed, 1 skipped`

## 覆盖场景

| 编号 | 场景 | 结果 |
|---|---|---|
| M-01 | 两个独立只读任务并行完成 | PASS |
| M-02 | 两个 Worker 写不同文件并合并成功 | PASS |
| M-03 | 两个任务写同一文件被 DAG 拒绝 | PASS |
| M-04 | Task DAG 有环被 validator 拒绝 | PASS |
| M-05 | Worker 越权路径返回 scope_violation | PASS |
| M-06 | Worker 协作式取消事件传播 | PASS |
| M-08 | Team 模式默认启用 Verify Gate | PASS |
| M-11 | 简单任务保持单 Agent 路径 | PASS |
| M-13 | Worker 提交越权 Bash 被拒绝 | PASS |
| M-14 | expected_hash CAS 冲突检测与 team trace 路由 | PASS |

## 关键防线验证

1. **DAG 写冲突检测**：两个任务的可写路径指向同一具体文件 `src/shared.py` 时被拒绝；共享目录 `src` 不触发冲突。
2. **运行时 Lease 保护**：FileLease 保证同一文件同一时刻只有一个写入者；`ALREADY_OWNS` 允许同一任务重复获取。
3. **PermissionGuardLite**：越界路径、未授权工具、危险 Bash 命令均被拒绝。
4. **Worker 状态推导**：模型 `done` 提议不能覆盖 scope/lease/cas 失败；Trace 事件在最终状态降级后发出。
5. **Verify Gate 默认启用**：CLI agent / team 默认 `--enable-verification-gate=True`，且 Coordinator 将该标志传递给 Worker。
6. **协作式取消**：`AgentRuntime` 在决策边界检查 `cancel_event`；Coordinator 在关闭阶段对未终止线程调用 `worker.cancel()`。

## 未覆盖（已知限制）

- M-07 父任务取消级联传播：仅实现 Worker 级取消信号，未实现从父任务到子任务的取消级联。
- M-09/M-10 Reviewer Fix Task 闭环：当前 Reviewer 为规则实现，REQUEST_CHANGES 分支标记为 TODO，未创建 Fix Task 或重新 review。
- M-15 unknown_outcome：未触发超时未知结果路径。
- D7 外部编辑、junction/symlink、TOCTOU：未覆盖。
- `TeamBudget.max_total_steps` / `max_total_model_calls` 未在团队层聚合执行。
- Trace 未统一记录 `provider` / `contract_id` / `model`。
