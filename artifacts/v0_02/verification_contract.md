# PaperClaw v0.02 Verification Contract

## 完成协议

1. 模型只能提出 `DoneProposal`
2. Runtime 基于历史构建 `VerificationPlan`
3. Verify 生成客观 `VerificationEvidence`
4. Reflection 只能消费 Evidence，不得改写 Evidence
5. 只有 Verify 通过且 Reflection `accept` 时，才能 `completed_verified`

## 当前 Claim / Check 基线

- 文件存在：`file_exists`
- 最新内容存在：`file_contains`
- 全量写入文件 hash 一致：`file_hash`
- 相关验证命令在最后一次写操作之后执行：`history`

## 命令摘要

当前会保留：

- `command`
- `command_class`
- `cwd`
- `exit_code`
- `timed_out`
- `duration_ms`
- `started_at`
- `finished_at`
- `truncated`
- pytest 可解析统计：`passed_count` / `failed_count` / `skipped_count` / `duration_seconds` / `failed_test_names`

## Reflection 约束

- 不能引用未知 `evidence_id`
- 不能在 Verify 非 `passed` 时输出 `accept`
- 不能删减当前 `failed_claim_ids`
- 不能直接修改工具历史、VerificationPlan 或 VerificationEvidence
