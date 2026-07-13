# PaperClaw v0.03 测试报告

## 自动化测试

- 全量命令：`python -m pytest -q --basetemp=tmp/pytest`
- 结果：`101 passed, 1 skipped`

### MultiAgent 新增测试

| 文件 | 用例数 | 覆盖重点 |
|---|---|---|
| test_multiagent_contracts.py | 6 | 数据契约序列化、枚举值 |
| test_multiagent_dag.py | 7 | DAG 校验、循环检测、写冲突、ordered chain |
| test_multiagent_lease.py | 5 | lease 获取/冲突/释放、越界拒绝 |
| test_multiagent_permissions.py | 5 | 工具白名单、路径逃逸、Bash 危险命令、symlink/junction 逃逸 |
| test_multiagent_scoped_tools.py | 9 | 幂等写入、FileSnapshot、CAS 冲突、外部编辑、TOCTOU 重验证、强制 CAS（无 hash 写已有文件被拒绝、新文件 sentinel）、file_edit 强制 CAS |
| test_multiagent_coordinator.py | 17 | 单 Agent 回退、顺序 DAG 执行、依赖失败阻塞下游、并行读/写、DAG 拒绝、scope violation、运行时 lease 冲突、取消级联、Fix-Review 闭环、团队预算聚合、model-call reservation、Task timeout、绝对 wall-time deadline、取消不提前释放 lease |

### 关键通过场景

- M-01：两个独立只读任务并行完成
- M-02：两个 Worker 写不同文件并合并成功
- M-03：两个任务写同一文件被 DAG 拒绝
- M-04：Task DAG 有环被 validator 拒绝
- M-05：Worker 越权路径返回 scope_violation
- M-06：Worker 协作式取消事件传播
- M-07：父任务取消级联到子任务
- M-08：Team 模式默认启用 Verify Gate
- M-09：Reviewer blocker/high 创建 Fix Task
- M-10：Reviewer 多轮不通过达到上限后返回 reflection_limit
- M-11：简单任务保持单 Agent 路径
- M-12：普通模型文本不会自动变成 AgentMessage
- M-13：Worker 提交越权 Bash 被拒绝
- M-14：Worker 写前文件被外部修改触发 expected_hash CAS 冲突；无 expected_hash 写已有文件被拒绝
- M-15：Bash 超时标记为 unknown_outcome，不自动重试

### P0 阻断项修复验证

| P0 项 | 验证方式 | 结果 |
|---|---|---|
| 顺序 DAG 漏任务 | test_single_agent_path_executes_dependent_chain + test_single_agent_path_blocks_downstream_on_failure | PASS |
| 强制 CAS | test_write_existing_file_without_expected_hash_rejected + test_write_new_file_allows_empty_sentinel + test_file_edit_without_expected_hash_rejected | PASS |
| 团队 model-call 预算 | test_team_model_call_budget_reservation_blocks_parallel_overshoot | PASS |
| Task timeout | test_task_timeout_enforced | PASS |
| 绝对 wall-time deadline | test_absolute_wall_time_deadline_shared_across_rounds | PASS |
| 取消安全（lease 不提前释放） | test_cancel_does_not_release_lease_immediately | PASS |

## 离线演示

- 工作区：`artifacts/v0_03/demo_workspace`
- 目标：两个 Worker 并行写 `src/a.py` 与 `src/b.py`
- 结果：`all_tasks_completed`
- trace：`artifacts/v0_03/collaboration_trace.json`

## 已知限制

- Reviewer 当前为规则实现，未接入 LLM；复杂语义判断需要后续版本结合真实模型。
- Global Verify 尚未作为独立阶段实现；M-08 当前仅验证配置传递。
- TOCTOU 测试当前为路径重验证 mock；真实 symlink/junction 切换竞态窗口尚未完全消除。
- 消息协议为数据类和事件词表，尚未形成完整 mailbox/recipient 路由通道。
