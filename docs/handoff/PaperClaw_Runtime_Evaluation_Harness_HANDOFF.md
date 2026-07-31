# Runtime Evaluation Harness Handoff

## 仓库与基线

- 仓库：`https://github.com/ZyfNO2/PaperClaw`
- 基础分支：`origin/main`
- 开发分支：`codex/evaluation-harness`
- 基础 Commit：`5891d87ec2a68f434fe8f728ba9be0999932c325`
- PaperClaw：`0.38.0`

## 数据流

```text
Case v1 -> strict loader -> recorded/durable adapter -> existing TraceReader
        -> workflow/tool/reliability/gate/trace rules
        -> existing aggregate/research/retrieval references -> unified artifacts
```

首批 dataset 包含 15 个 offline control-flow Case，覆盖 Coordinator/Worker/Reviewer、一次返工、
Tool schema observation、Extension policy recheck、permission denial、retry recovery、Trace、
Secret boundary、research provenance structural check、expected Gate 与 read-only false positive。

## 验收边界

- 已实现：offline recorded adapter、existing SQLite durable Trace adapter、规则指标、Failure
  evidence、JSON/Markdown report、CLI、15 Case 与自动测试。
- `NOT_VERIFIED`：无人工 claim-support label 时的语义事实正确性。
- `PENDING`：real_llm、distributed Redis/PostgreSQL、真实外部 Tool、真实人工批准。
- HumanGate 没有生产审批领域对象；本次只定义 Trace-side 最小评估词汇，不自动批准。
- Local/live/distributed adapter 是对已执行 durable Trace 的评估，不负责启动 Provider 或服务。

## 接手验证

```powershell
python -m pytest -q --basetemp artifacts/test-tmp tests/unit/eval/test_runtime_harness.py
python -m paperclaw.eval.benchmark_cli --dataset examples/evaluation/runtime-cases.jsonl --workspace . --mode offline --output artifacts/evaluations/offline-demo
python -m pytest -q --basetemp artifacts/test-tmp -m "not real_llm and not distributed"
python -m ruff check src/paperclaw tests --select E9,F63,F7,F82 --ignore F821
python -m build
python .claude/hooks/sop_completion_check.py
```

## 最终验证记录

- 定向 Harness + 旧 Aggregate/Golden：`38 passed in 0.89s`；
- 完整非真实服务回归：`1051 passed, 23 skipped, 12 deselected`；
- Ruff correctness：通过；
- wheel/sdist：`paperclaw-0.38.0` 构建通过；
- 安装后 entrypoint smoke：`paperclaw-eval-run --help` 通过；
- Offline demo：15 Case，14 PASS + 1 WAITING_APPROVAL；
- 独立 Review：三轮，最终无 blocker；
- SOP completion hook：读取旧 v0.10 draft，13 个未勾选项、缺少 `artifacts/v0_10` handoff；
  这不属于本次 Harness SOP，不能据此声明 v0.10 release GO。

未执行：`real_llm`（需要 Provider Secret）、`distributed`（需要 Redis/PostgreSQL）、
真实外部 Tool、真实人工批准。它们不影响本次 offline control-flow acceptance，但状态分别为
`PENDING` / `NOT_VERIFIED`。

最终状态：本次 Evaluation Harness 的 offline MVP 为 `release_accepted`；真实服务路径等待
对应环境验证。最终 Commit SHA 以本分支 HEAD 为准。
