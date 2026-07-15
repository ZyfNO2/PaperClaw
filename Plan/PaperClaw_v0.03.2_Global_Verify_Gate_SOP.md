# PaperClaw v0.03.2 Global Verify Gate SOP

> 状态：实现完成；实现 HEAD Windows CI 与 Ruff 已通过；等待最终文档 HEAD CI
> 基线：`main@725e8a81425efa987f59a6f66ce0021fe7978261`
> 分支：`feat/v0.03.2-global-verify-gate`
> Draft PR：`#14`
> 实现验证：run `29450607810` / 403 passed / Ruff PASS
> 冲突策略：不修改 `cli.py`、`tui/`、`trace/`、Provider、Replay、Eval 或 v0.07.x 文件。

## 1. 用户故事

MultiAgent 中每个 Worker 的本地 Verify 都可能通过，但跨任务共享契约仍可能不一致。例如 API Worker 与 Client Worker 都完成各自任务，却生成了不同的 schema digest。

本切片提供显式 Project Claim 合同，在现有 Coordinator 完成后执行确定性全局校验：

```text
Coordinator local tasks + Reviewer
              ↓
       ProjectClaim evidence
              ↓
     deterministic GlobalVerifier
              ↓
passed → 保留原成功状态
failed/incomplete → effective BLOCKED
```

## 2. 实现范围

- `ProjectClaim`：claim id、描述、贡献任务、evidence key、聚合规则；
- `ALL_PRESENT`：每个贡献任务必须发布结构化 evidence；
- `ALL_EQUAL`：每个贡献任务 evidence 的 canonical JSON 值必须一致；
- `GlobalVerifier`：不调用模型、不运行工具、不读取任意文件；
- `GlobalVerifyCoordinator`：组合现有 Coordinator，不修改其实现；
- 本地团队未完成时跳过 Global Verify，并保留原 stop reason；
- 本地团队成功但 Global Verify failed/incomplete 时，effective stop reason 为 `BLOCKED`；
- 追加 sanitized `global_verification.completed` EventEnvelope v1；
- 不在 event 中写入 evidence 原值。

## 3. 明确非目标

- LLM-as-a-Judge；
- 自动推断 Project Claim；
- 任意 Python predicate；
- 自动读取仓库文件或运行命令；
- 修改现有 Coordinator 默认路径；
- CLI/TUI 接线；
- durable mailbox、RAG、Permission Engine；
- v0.07 Trace schema 改动。

## 4. 验收矩阵

- [x] 两个本地成功 Worker 的 shared evidence 不一致时，团队结果变为 BLOCKED；
- [x] shared evidence 一致时，保留 `ALL_TASKS_COMPLETED`；
- [x] required evidence 缺失时返回 INCOMPLETE 并阻断；
- [x] contributor 未完成时 claim 失败；
- [x] claim 引用未知 task 时 fail closed；
- [x] 团队未完成时跳过全局校验且不覆盖原 stop reason；
- [x] 事件只包含计数、状态和 effective stop reason；
- [x] GitHub Actions Windows 全量 pytest：403 passed，0 failed，0 skipped；
- [x] Ruff high-signal gate：PASS；
- [ ] Handoff/SOP 最终文档 HEAD CI。

## 5. 接线方式

```python
from paperclaw.multiagent.global_verify import (
    GlobalClaimRule,
    GlobalVerifyCoordinator,
    ProjectClaim,
)

verified = GlobalVerifyCoordinator(existing_coordinator)
result = verified.run(
    goal,
    tasks,
    claims=[
        ProjectClaim(
            claim_id="shared-schema",
            description="API and client schema agree",
            contributor_task_ids=("api", "client"),
            evidence_key="schema_digest",
            rule=GlobalClaimRule.ALL_EQUAL,
        )
    ],
    evidence_by_task={
        "api": {"schema_digest": api_digest},
        "client": {"schema_digest": client_digest},
    },
)
```

## 6. 后续边界

后续只有在真实使用证明 evidence 生产过程稳定后，才考虑：

- 将 Project Claim 加入 team plan JSON；
- 在 CLI 中增加 opt-in 参数；
- 将 aggregate result 接入 MultiAgent View；
- 基于 v0.07 Trace 持久化 Global Verify 事实。
