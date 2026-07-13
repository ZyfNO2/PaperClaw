# PaperClaw v0.03 冲突测试报告

## 测试环境

- 命令：`$env:TEMP="g:\PaperClaw\tmp\pytest_temp"; $env:TMP="g:\PaperClaw\tmp\pytest_temp"; python -m pytest -q`
- 结果：`101 passed, 1 skipped`

## 覆盖场景

| 编号 | 场景 | 结果 |
|---|---|---|
| M-01 | 两个独立只读任务并行完成 | PASS |
| M-02 | 两个 Worker 写不同文件并合并成功 | PASS |
| M-03 | 两个任务写同一文件被 DAG 拒绝 | PASS |
| M-04 | Task DAG 有环被 validator 拒绝 | PASS |
| M-05 | Worker 越权路径返回 scope_violation | PASS |
| M-06 | Worker 协作式取消事件传播 | PASS |
| M-07 | 父任务取消级联到子任务 | PASS |
| M-08 | Team 模式默认启用 Verify Gate（仅配置传递） | PARTIAL |
| M-09 | Reviewer blocker/high 创建 Fix Task | PASS |
| M-10 | Reviewer 多轮不通过达到上限后返回 reflection_limit | PASS |
| M-11 | 简单任务保持单 Agent 路径 | PASS |
| M-12 | 普通模型文本不会自动变成 AgentMessage | PASS |
| M-13 | Worker 提交越权 Bash 被拒绝 | PASS |
| M-14 | expected_hash CAS 冲突检测 + 强制 CAS（无 hash 写已有文件被拒绝） | PASS |
| M-15 | Bash 超时标记为 unknown_outcome | PASS |

## P0 阻断项修复验证

| P0 项 | 修复内容 | 验证结果 |
|---|---|---|
| 顺序 DAG 漏任务 | 单 Agent 路径按拓扑顺序执行全部任务；依赖失败阻塞下游 | PASS |
| 强制 CAS | 已存在文件的 write/edit 必须携带 expected_hash；新文件用空字符串 sentinel；缺失返回 cas_missing | PASS |
| 团队 model-call 预算 | 并行调度时悲观预留 model-call 上限（= max_steps）；超额任务被取消 | PASS |
| Task timeout | AgentTask.timeout_seconds 传入 AgentRuntime；DecideActionNode 在步骤间检查 wall-clock 超时 | PASS |
| 绝对 wall-time deadline | run_deadline 在 _run_parallel 入口计算，所有 fix-review 轮次共享；不再每轮重置 | PASS |
| 取消安全 | cancel() 不释放 lease，杀死注册子进程；Worker.run() 自然退出后释放；线程未终止返回 unknown_outcome | PASS |

## 关键防线验证

1. **DAG 写冲突检测**：两个任务的可写路径指向同一具体文件 `src/shared.py` 时被拒绝；共享目录 `src` 不触发冲突。
2. **运行时 Lease 保护**：FileLease 保证同一文件同一时刻只有一个写入者；`ALREADY_OWNS` 允许同一任务重复获取。
3. **PermissionGuardLite**：越界路径、未授权工具、危险 Bash 命令均被拒绝；symlink/junction 指向工作区外时同样被拒绝。
4. **Worker 状态推导**：模型 `done` 提议不能覆盖 scope/lease/cas/cas_missing/timeout 失败；Trace 事件在最终状态降级后发出。
5. **Verify Gate 默认启用**：CLI agent / team 默认 `--enable-verification-gate=True`，且 Coordinator 将该标志传递给 Worker。
6. **协作式取消 + 进程树终止**：`cancel()` 设置事件 + 杀死注册子进程；`_cancel_active_worker` 等待 10s，未终止返回 `unknown_outcome`；lease 由 `Worker.run()` 在线程自然退出后释放。
7. **Reviewer 闭环**：blocker/high 自动转为 Fix Task，Fix-Review 轮数受 `TeamBudget.max_fix_rounds` 限制，达到上限后返回 `reflection_limit`。
8. **团队预算聚合 + model-call 预留**：子任务 step / model_call 计数汇总到团队总预算；并行调度时悲观预留 model-call 上限，防止并发 Worker 瞬时突破限制。
9. **强制 CAS**：已存在文件的 `file_write` / `file_edit` 必须携带 `expected_hash`，缺失时返回 `cas_missing` 且文件不被覆盖；新文件使用空字符串 sentinel。
10. **Task 级 timeout**：`AgentTask.timeout_seconds` 传入 AgentRuntime，在步骤间检查 wall-clock 超时；超时后 `stop_reason = "timeout"`，Worker 返回 FAILED。
11. **绝对 wall-time deadline**：`run_deadline` 在 `_run_parallel` 入口计算，所有 fix-review 轮次共享同一绝对截止时间。

## 已知限制

- Reviewer 当前为规则实现，未接入 LLM；复杂语义判断需要后续版本结合真实模型。
- Global Verify 尚未作为独立阶段实现；M-08 当前仅验证配置传递。
- TOCTOU 测试当前为路径重验证 mock；真实 symlink/junction 切换竞态窗口尚未完全消除。
- 消息协议为数据类和事件词表，尚未形成完整 mailbox/recipient 路由通道。
