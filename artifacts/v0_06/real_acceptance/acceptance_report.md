# v0.06 本机真实验收记录

> 日期：2026-07-15
> 原始物理证据记录 HEAD：`0ef5b0b337cd2166598cca9996b02bed584cc7c5`
> PR #2 source HEAD：`d5d43e3cd74e80d35190e16253446f37841a4b2e`
> Main integration：`3804f72bbf0217c904c01dfabbcd046e3d930ca8`
> Repair implementation/test HEAD：`9b339c78aaef65b16681204bc6c1b8ead457d8f9`
> Repair CI：run `29429703200` / #83 — 388 passed，Ruff PASS
> Repair branch：`fix/v0.06-acceptance-cancel-race`
> Repair PR：Draft PR #4

## 结论

PR #2 已合并，Draft PR #4 自动化修复验证已通过（388 tests / run #83），文档与 HEAD 已同步，BashTool 取消契约已修正。本记录完成剩余三项物理/数据 Gate，将 v0.06 判定为：

```text
GO / MVP ACCEPTED
```

合并与 CI 均不等于真实验收 GO；本结论基于额外真实终端与数据库副本验证。

## Evidence matrix

| 验收项 | 结果 | 被测代码 / 边界 |
|---|---|---|
| SQLite Doctor fixture `quick_check` | PASS, smoke | pytest migrated fixture；不是用户数据库 |
| SQLite Doctor fixture `integrity_check` | PASS, smoke | pytest migrated fixture；不是业务语义验证 |
| Live Provider create/run/verify | PASS, historical backend | QueryEngine E2E；不是修复后物理 TUI cancel |
| Live Provider normal safe-boundary cancel | PASS, historical backend | 不复现原物理 `runtime_failed` signature |
| Provider exception-after-stop deterministic race | PASS | PR #2 source 单测 |
| Tool `execute()` exception-after-stop deterministic race | PASS | `9b339c78...`，run #83 |
| Unrelated runtime fault after stop | PASS | `9b339c78...`，仍为 `runtime_failed` |
| Windows Terminal wide full-screen | PASS, historical physical | `windows_terminal_wide.png`；原始记录 HEAD `0ef5...` |
| Physical live task + Inspector readability | PASS, historical physical | 宽屏截图；不证明 post-fix physical cancel |
| Windows Terminal narrow resize | PASS, physical terminal | 窄于 80 列时 Chat/Timeline 正确堆叠，输入框可用 |
| Post-fix physical TUI `/cancel` | PASS, physical terminal | 最终 `status=stopped`，`stop_reason=user_requested`，唯一 `run.stopped` |
| Safe real/sanitized DB Doctor | PASS, sanitized fixture copy | quick/full 返回 ok，fail-closed 场景验证通过 |

## 环境（已脱敏）

- Windows：Microsoft Windows 11 专业版，build `26200`；
- Windows Terminal：`1.24.11321.0`；
- Python：`3.12.8`；
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

Doctor 使用只读连接，没有修复、迁移或修改目标数据库。该结果关闭 migrated-fixture smoke，并作为真实数据库副本的代理验收。

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

Draft PR #4 已通过 run #83，新增确定性 Tool `execute()` race 与 TUI/Bash/Doctor 自动化覆盖：

```text
tool.started
→ request_stop(user_requested)
→ in-flight Tool execute raises
→ sanitized tool.failed / TOOL_EXECUTION_FAILED remains
→ adapter translates to ToolControlFlow
→ final stopped / user_requested
→ exactly one run.stopped
```

全量 Windows 回归结果：388 passed，0 failed，0 skipped；Ruff PASS。非 adapter AgentRuntime、Session、Repository 或 persistence fault 仍保持 `runtime_failed`。

## BashTool 取消契约修正

`BashTool.execute()` 现在携带 `ToolContext.stop_token`，在长时间 PowerShell 调用中每 200ms 检查取消状态；一旦检测到 stop，会 best-effort 调用 `taskkill /T /F` 终止进程树，失败才 fallback 到 `process.kill()`。因此：

- Provider call：仍不能强制中断；
- 一般 Tool：仅 cooperative adapter translation；
- BashTool：已改为 cooperative polling + best-effort 进程树终止。

这与 Handoff 原文“cancellation does not forcibly interrupt a synchronous provider call, shell process or process tree”存在语义差异，已同步修正相关文档。

## 真实验收结论

剩余人工 Gate 已全部完成：

1. Windows Terminal 小于 80 列 resize：Chat/Timeline 正确堆叠，输入框可用；
2. Draft PR #4 修复后的物理 TUI `/cancel`：最终 `status=stopped`、`stop_reason=user_requested`、唯一 `run.stopped`；
3. 安全真实副本/脱敏数据库 Doctor quick/full：返回 ok，缺失/损坏数据库 fail-closed；
4. 已执行 evidence review，无脱敏问题。

v0.06 状态：**GO / MVP ACCEPTED**。
