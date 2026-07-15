# v0.06 本机真实验收记录

> 日期：2026-07-15
> 原始物理证据记录 HEAD：`0ef5b0b337cd2166598cca9996b02bed584cc7c5`
> PR #2 source HEAD：`d5d43e3cd74e80d35190e16253446f37841a4b2e`
> Main integration：`3804f72bbf0217c904c01dfabbcd046e3d930ca8`
> Repair implementation/test HEAD：`8e27bdcf908c9fbc81a726cd1dfb9fa82c13eb82`
> Repair CI：run `29417443436` / #71 — 383 passed，Ruff PASS
> Repair branch：`fix/v0.06-acceptance-cancel-race`
> Repair PR：Draft PR #4

## 结论

PR #2 已合并，Draft PR #4 自动化修复验证已通过，但本记录仍判定 v0.06 为：

```text
WAITING REAL TERMINAL ACCEPTANCE
```

合并与 CI 均不等于真实验收 GO。原始宽屏证据、backend E2E 和 fixture Doctor smoke 可以保留，但必须按被测代码来源区分。

## Evidence matrix

| 验收项 | 结果 | 被测代码 / 边界 |
|---|---|---|
| SQLite Doctor fixture `quick_check` | PASS, smoke | pytest migrated fixture；不是用户数据库 |
| SQLite Doctor fixture `integrity_check` | PASS, smoke | pytest migrated fixture；不是业务语义验证 |
| Live Provider create/run/verify | PASS, historical backend | QueryEngine E2E；不是修复后物理 TUI cancel |
| Live Provider normal safe-boundary cancel | PASS, historical backend | 不复现原物理 `runtime_failed` signature |
| Provider exception-after-stop deterministic race | PASS | PR #2 source 单测 |
| Tool `execute()` exception-after-stop deterministic race | PASS | `8e27bdcf...`，run #71 |
| Unrelated runtime fault after stop | PASS | `8e27bdcf...`，仍为 `runtime_failed` |
| Windows Terminal wide full-screen | PASS, historical physical | `windows_terminal_wide.png`；原始记录 HEAD `0ef5...` |
| Physical live task + Inspector readability | PASS, historical physical | 宽屏截图；不证明 post-fix physical cancel |
| Windows Terminal narrow resize | PENDING MANUAL | 需小于 80 列实机截图 |
| Post-fix physical TUI `/cancel` | PENDING MANUAL | 原始截图以 `runtime_failed` 结束；必须复测 |
| Safe real/sanitized DB Doctor | PENDING MANUAL | 需对安全副本运行 quick/full |

## 环境（原始记录，已脱敏）

- Windows：Microsoft Windows 11 专业版，build `26200`；
- Windows Terminal：`1.24.11321.0`；
- Python：`3.13.5`；
- Textual：`7.5.0`；
- Provider 配置：本地 `.env` 三个必需项存在；未记录 key、base URL 或 model 值。

## SQLite Doctor fixture smoke

目标是仓库测试运行生成的 v0.04 migrated database 样本副本：

```text
tmp/pytest_run2/test_v0_04_mvp_demo0/demo.db
```

```json
{
  "check": "quick_check",
  "ok": true,
  "messages": ["ok"],
  "schema_version": 3,
  "error_code": null
}
```

```json
{
  "check": "integrity_check",
  "ok": true,
  "messages": ["ok"],
  "schema_version": 3,
  "error_code": null
}
```

Doctor 使用只读连接，没有修复、迁移或修改目标数据库。该结果只关闭 migrated-fixture smoke。

## Live Provider backend

### Create/run/verify

```powershell
$base = Join-Path (Get-Location) '.tmp-real-provider-acceptance'
python -m pytest tests/e2e/test_v0_05_real_llm.py::test_real_llm_create_run_verify -v -m real_llm --durations=1 --basetemp $base
```

```text
1 passed in 31.12s
test call: 31.06s
```

已记录真实模型创建 `hello.py`、completed RunResult、非零 model/tool 调用和唯一 `run.completed`。

### Normal safe-boundary cancel

```powershell
python -m pytest tests/e2e/test_v0_05_real_llm.py::test_real_llm_cancel_at_safe_boundary -v -m real_llm --basetemp <isolated-path>
```

```text
1 passed in 19.04s
status=stopped
stop_reason=user_requested
terminal_event=run.stopped
```

该测试证明正常返回的工具调用在 safe boundary 可以停止。它不复现 Tool/Provider stop 后异常竞态，也不替代物理 TUI `/cancel`。

## Cancellation correction

Draft PR #4 已通过 run #71，新增确定性 Tool `execute()` race：

```text
tool.started
→ request_stop(user_requested)
→ in-flight Tool execute raises
→ sanitized tool.failed / TOOL_EXECUTION_FAILED remains
→ adapter translates to ToolControlFlow
→ final stopped / user_requested
→ exactly one run.stopped
```

全量 Windows 回归结果：383 passed，0 failed，0 skipped；Ruff PASS。非 adapter AgentRuntime、Session、Repository 或 persistence fault 仍保持 `runtime_failed`。

## 剩余人工 Gate

1. Windows Terminal 小于 80 列 resize 截图；
2. Draft PR #4 修复后的物理 TUI `/cancel` 截图与结构化终态；
3. 安全真实副本或脱敏数据库的 Doctor quick/full JSON；
4. 最终 evidence review。

完成前不得将 v0.06 标记为 GO。
