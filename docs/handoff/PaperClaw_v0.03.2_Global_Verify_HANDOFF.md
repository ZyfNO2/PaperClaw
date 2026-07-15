# PaperClaw v0.03.2 Global Verify Gate Handoff

## 状态

`IMPLEMENTATION GO / DRAFT PR / WAITING FINAL HEAD CI`

Global Verify 首切片已经实现并在实现 HEAD `22615d3c4af7b3a42dcd421291a2382c3dd9363a` 上通过完整 Windows 离线回归。本文档提交后仍需以最终分支 HEAD 的 CI 为最终证据。

## 仓库与分支

- Repository: `ZyfNO2/PaperClaw`
- Base: `main@725e8a81425efa987f59a6f66ce0021fe7978261`
- Branch: `feat/v0.03.2-global-verify-gate`
- Draft PR: `#14`

## 已完成内容

- 新增显式 `ProjectClaim` 合同；
- 新增 `ALL_PRESENT` 与 `ALL_EQUAL` 两种确定性跨任务聚合规则；
- 新增无模型、无工具、无文件系统副作用的 `GlobalVerifier`；
- 新增组合式 `GlobalVerifyCoordinator`，不修改既有 Coordinator；
- 本地团队成功但全局 claim 失败或 evidence 不完整时，将 effective stop reason 改为 `BLOCKED`；
- 本地团队未完成时跳过全局校验，并保留原 stop reason；
- 新增 sanitized `global_verification.completed` 事件，仅记录状态、计数与 effective stop reason；
- 新增“所有 Worker 本地通过但共享 schema 不一致”的确定性失败 fixture；
- 新增 contract、missing evidence、unknown task、early-stop 等测试。

## 修改和新增的主要文件

- `src/paperclaw/multiagent/global_verify.py`
- `tests/unit/test_global_verify.py`
- `Plan/PaperClaw_v0.03.2_Global_Verify_Gate_SOP.md`
- `docs/handoff/PaperClaw_v0.03.2_Global_Verify_HANDOFF.md`

所有文件均为新增文件。没有修改 v0.07–v0.07.6 堆叠分支涉及的 CLI、Trace、Provider、Replay、Eval、Exporter 或 Harness 路径。

## 关键架构决定

1. 使用 composition 包装现有 Coordinator，而不是侵入其默认执行路径。
2. Project Claim 必须由调用方显式提供；本切片不让模型自行决定验收条件。
3. Evidence 使用 canonical JSON 比较，但原始 evidence 不进入 team event。
4. `FAILED` 和 required evidence 的 `INCOMPLETE` 都阻断团队全局完成。
5. 团队本身未成功时不执行 Global Verify，避免覆盖更早的真实失败原因。

## 已执行测试和 CI

实现 HEAD：`22615d3c4af7b3a42dcd421291a2382c3dd9363a`

GitHub Actions run `29450607810` / run #122：

- Environment: Windows Server 2025 / Python 3.12；
- pytest call phase: **403 passed, 0 failed, 0 skipped**；
- pytest exit status: `0`；
- Ruff E9/F63/F7/F82 gate: **PASS**；
- artifact: `pytest-results-29450607810`；
- artifact digest: `sha256:954de27b2567c3432fcc6eac7b0bab945d996fa42c50589253263cd70dffb914`。

测试数量来自 artifact 中 `pytest_reportlog.jsonl` 的 call-phase 记录，不是从 PR 文本推断。

## 未执行或未通过的真实测试

- 不需要真实 Provider 测试：该模块不调用模型或网络服务。
- 不需要真实工具/文件系统 E2E：该模块只消费已有 `WorkerResult` 和调用方提供的结构化 evidence。
- 尚未做 CLI/team-plan JSON 接线，因为这会触碰正在合并的 v0.07.x 热点路径，且 evidence 生产合同仍需真实使用验证。

## 当前已知限制

- Evidence 当前由调用方单独提供，尚未成为 `WorkerResult` 的冻结字段。
- 只支持 `ALL_PRESENT` 与 `ALL_EQUAL`；不接受任意可执行 predicate。
- Global Verify event 尚未进入 v0.07 durable Trace projection。
- Draft PR 基于 v0.07.x 合并前的 `main`，合并前应更新 base 并重新运行最终 CI。

## 尚未完成事项

- 等待本文档与 SOP 状态更新后的最终 HEAD CI；
- v0.07.x 全部合并后更新 PR base；
- 在没有内容冲突的前提下复跑全量 Windows pytest 与 Ruff；
- 后续单独评估 team-plan JSON / CLI opt-in 接线，不应与本 PR 混合。

## 下一位开发者接手步骤

1. 确认 PR #14 仍为 Draft；
2. 等 v0.07–v0.07.6 合并到 `main`；
3. 将分支更新到最新 `main`，不得覆写 v0.07.x 实现；
4. 检查 diff 仍只包含本 Handoff 所列新增文件；
5. 运行下列验证命令；
6. 只有最终 HEAD CI 通过后，才考虑将 Draft 标为 Ready。

## 建议验证命令

```powershell
python -m pytest -q tests/unit/test_global_verify.py --basetemp=tmp/pytest-global-verify
python -m pytest -q -m "not real_llm" --basetemp=tmp/pytest
python -m ruff check src/paperclaw tests --select E9,F63,F7,F82 --ignore F821
```

## 最终判定

当前切片实现状态：`GO`。

PR 状态：`DRAFT / WAITING FINAL HEAD CI AND POST-v0.07.x BASE UPDATE`。
