# PaperClaw v0.03 测试报告

## 自动化测试

- 全量命令：`python -m pytest -q --basetemp=tmp/pytest`
- 结果：`78 passed, 1 skipped`

### MultiAgent 新增测试

| 文件 | 用例数 | 覆盖重点 |
|---|---|---|
| test_multiagent_contracts.py | 6 | 数据契约序列化、枚举值 |
| test_multiagent_dag.py | 7 | DAG 校验、循环检测、写冲突、ordered chain |
| test_multiagent_lease.py | 5 | lease 获取/冲突/释放、越界拒绝 |
| test_multiagent_permissions.py | 5 | 工具白名单、路径逃逸、Bash 危险命令 |
| test_multiagent_scoped_tools.py | 4 | 幂等写入、FileSnapshot、CAS 冲突 |
| test_multiagent_coordinator.py | 7 | 单 Agent 回退、并行读/写、DAG 拒绝、scope violation、运行时 lease 冲突 |

### 关键通过场景

- M-01：两个独立只读任务并行完成
- M-02：两个 Worker 写不同文件并合并成功
- M-03：两个任务写同一文件被 DAG 拒绝
- M-04：Task DAG 有环被 validator 拒绝
- M-05：Worker 越权路径返回 scope_violation
- M-11：简单任务保持单 Agent 路径
- M-13：Worker 提交越权 Bash 被拒绝
- M-14：Worker 写前文件被外部修改触发 expected_hash CAS 冲突

## 离线演示

- 工作区：`artifacts/v0_03/demo_workspace`
- 目标：两个 Worker 并行写 `src/a.py` 与 `src/b.py`
- 结果：`all_tasks_completed`
- trace：`artifacts/v0_03/collaboration_trace.json`

## 已知未覆盖

- Worker 超时与取消传播（M-06 / M-07）
- 局部通过但全局失败（M-08）
- Reviewer Fix Task 闭环（M-09 / M-10）
- expected_hash CAS 在 junction/symlink 与外部并发编辑场景（M-14）
- unknown_outcome 标记（M-15）
