# PaperClaw v0.02 测试报告

## 自动化测试

- 全量命令：`python -m pytest -q --basetemp=tmp/pytest_full_v002`
- 结果：`44 passed, 1 skipped`

### 覆盖重点

- Verify 对无关成功命令的拒绝
- Verify 对“修改后未重验”的拒绝
- pytest 失败/成功摘要提取
- Reflection 的 repair / blocked / accept 路由
- Reflection 对未知 evidence / 缺失 failed claims 的拒绝
- v0.01 兼容路径在 Gate 关闭时仍通过

## 真实模型受控演示

- 工作区：`tmp/real_v002_demo`
- 目标：先读测试，再跑失败 pytest，再修复，再重跑 pytest，通过 Gate 完成
- 结果：`completed_verified`
- trace：`artifacts/v0_02/verify_reflection_trace.json`
- 完整状态：`artifacts/v0_02/real_demo_state.json`

### 真实演示观察

- 模型确实走到了“失败 -> 修复 -> 重验 -> accept”闭环；
- 模型中途出现过一次无效 `file_edit` 参数尝试，但没有破坏运行边界；
- 后续正确完成修复并通过 Gate，说明 v0.02 已具备最小自纠错闭环。
