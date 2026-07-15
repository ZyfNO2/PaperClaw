# PaperClaw v0.03–v0.06 Post-MVP 选做切片 Handoff

## 状态

**PARTIAL COMPLETE / WAITING REAL TERMINAL ACCEPTANCE**

26 个候选包或延期行已完成审计。两个可以在当前前置能力上独立落地的小切片已经实现：SQLite 只读 Doctor 与 sanitized Verification Inspector。

PR #2 已合并到 `main`，但合并不等于 v0.06 acceptance GO。Draft PR #4 已补齐 Tool `execute()` 取消竞态覆盖缺口并通过自动化 CI。

## 仓库状态

- Repository：`ZyfNO2/PaperClaw`
- Base：`main`
- PR #2 source HEAD：`d5d43e3cd74e80d35190e16253446f37841a4b2e`
- Main integration commit：`3804f72bbf0217c904c01dfabbcd046e3d930ca8`
- Repair branch：`fix/v0.06-acceptance-cancel-race`
- Repair PR：Draft PR #4
- Repair implementation/test HEAD：`9b339c78aaef65b16681204bc6c1b8ead457d8f9`
- Repair CI：run `29429703200` / #83 — SUCCESS
- Windows pytest：388 passed，0 failed，0 skipped
- Ruff：PASS

## 已完成内容

### SQLite Doctor

- `paperclaw doctor --database ... [--full]`；
- SQLite quick/integrity check；
- foreign-key check；
- schema version report；
- read-only/query-only connection；
- missing/corrupt fail-closed；
- 不创建、不迁移、不修复目标数据库。

### Verification Inspector

- TUI 中单一 Verify aggregate 面板；
- 展示 status、passed/failed/uncovered 与 `verified_after_last_write`；
- Bridge 删除 raw `checks` 和 `observed`；
- 不扩展 QueryEngine contract；
- 不实现 Context/Trace/Cost panel。

### Cancellation correction

Draft PR #4 已通过确定性测试证明：

```text
tool.started
→ request_stop(user_requested)
→ in-flight Tool execute raises
→ sanitized tool.failed remains
→ adapter translates to cooperative control flow
→ stopped / user_requested
→ exactly one run.stopped
```

该修复不改变以下规则：AgentRuntime、Session、Repository、SQLite 或 persistence fault 仍保持 `runtime_failed`。`BashTool` 现在会轮询 `ToolContext.stop_token` 并在取消时 best-effort 终止 PowerShell 进程树，但这不改变 provider call 与一般 Tool 的 cooperative 语义。

## 自动化证据

### PR #2 source HEAD

- SHA：`d5d43e3cd74e80d35190e16253446f37841a4b2e`；
- GitHub Actions：run #45；
- Windows pytest：382 call-phase tests passed；
- Ruff：PASS。

### Draft PR #4

- SHA：`9b339c78aaef65b16681204bc6c1b8ead457d8f9`；
- GitHub Actions：run `29429703200` / #83；
- Windows pytest：388 passed，0 failed，0 skipped；
- Ruff：PASS；
- artifact：`pytest-results-29429703200`。

## 真实验收状态

| Gate | 状态 | 边界 |
|---|---|---|
| SQLite migrated-fixture Doctor | PASS, smoke | 不等于真实/脱敏用户数据库 |
| Live Provider create/run/verify | PASS, historical | backend E2E；不是修复后 physical cancel |
| Live Provider normal safe-boundary cancel | PASS, historical | 不复现原 physical `runtime_failed` signature |
| Windows Terminal wide launch/task/Inspector | PASS, historical | 原始 evidence HEAD 记录为 `0ef5...` |
| Windows Terminal narrow resize | PENDING MANUAL | 需小于 80 列截图 |
| Post-fix physical TUI `/cancel` | PENDING MANUAL | 需修复后截图与唯一 terminal event |
| Safe real/sanitized DB Doctor | PENDING MANUAL | 需 quick/full redacted JSON |

详细证据见：

- `artifacts/v0_06/real_acceptance/acceptance_report.md`
- `artifacts/v0_06/acceptance_correction.md`
- `docs/handoff/PaperClaw_v0.06_TUI_MVP_HANDOFF.md`

## 仍未启动的候选方向

- Global Verify；
- MultiAgent View；
- safe-closed Session Picker；
- async/token streaming；
- ShellTask/process-tree cancellation；
- Permission UX；
- EventBus；
- durable mailbox；
- arbitrary crash recovery。

这些方向仍需各自 fixture、runtime contract 与用户收益证据，不得因为前序 PR 已合并而自动启动。

## 下一位开发者接手

```powershell
git fetch origin
git switch fix/v0.06-acceptance-cancel-race
python -m pip install -e ".[dev,tui]"
python -m pytest -q --basetemp=tmp/pytest -m "not real_llm"
python -m ruff check src/paperclaw tests --select E9,F63,F7,F82 --ignore F821
```

自动化 Gate 已通过。下一步只处理窄屏、post-fix physical `/cancel` 与 safe database Doctor。所有要求证据一致且脱敏后，才可将 v0.06 改为 GO。
