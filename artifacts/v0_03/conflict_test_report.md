# PaperClaw v0.03 冲突测试报告

## 测试环境

- 命令：`python -m pytest tests/unit/test_multiagent_*.py --basetemp=.pytest_tmp`
- 结果：29 passed

## 覆盖场景

| 编号 | 场景 | 结果 |
|---|---|---|
| M-01 | 两个独立只读任务并行完成 | PASS |
| M-02 | 两个 Worker 写不同文件并合并成功 | PASS |
| M-03 | 两个任务写同一文件被 DAG 拒绝 | PASS |
| M-04 | Task DAG 有环被 validator 拒绝 | PASS |
| M-05 | Worker 越权路径返回 scope_violation | PASS |
| M-11 | 简单任务保持单 Agent 路径 | PASS |
| M-13 | Worker 提交越权 Bash 被拒绝 | PASS |

## 关键防线验证

1. **DAG 写冲突检测**：两个任务的可写路径指向同一具体文件 `src/shared.py` 时被拒绝；共享目录 `src` 不触发冲突。
2. **运行时 Lease 保护**：FileLease 保证同一文件同一时刻只有一个写入者；`ALREADY_OWNS` 允许同一任务重复获取。
3. **PermissionGuardLite**：越界路径、未授权工具、危险 Bash 命令均被拒绝。
4. **Worker 状态推导**：模型 `done` 提议不能覆盖 scope/lease/cas 失败。

## 未覆盖（已知限制）

- M-06 Worker 超时取消、M-07 父任务取消、M-08 局部通过全局失败、M-09/M-10 Reviewer Fix Task 闭环：当前 Reviewer 为规则实现，Fix Task 循环标记为 TODO。
- M-14 expected_hash CAS：已有实现，但尚未覆盖 junction/symlink 与外部并发编辑场景。
- M-15 unknown_outcome：未触发超时未知结果路径。
