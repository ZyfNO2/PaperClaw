# PaperClaw v0.06：Claw TUI MVP SOP

> 版本：v0.06
> 状态：**实现与修复 CI 完成；等待剩余真实 Windows Terminal 与数据库验收**
> 更新：2026-07-15
> Main integration：`3804f72bbf0217c904c01dfabbcd046e3d930ca8`
> Repair branch：`fix/v0.06-acceptance-cancel-race`
> Repair PR：Draft PR #4
> Repair implementation/test HEAD：`8e27bdcf908c9fbc81a726cd1dfb9fa82c13eb82`
> Repair CI：run `29417443436` / #71 — SUCCESS
> 前置：v0.05 QueryEngine MVP

## 1. 当前结论

v0.06 已作为同步 `QueryEngine` 的可选 Textual 薄客户端实现。PR #2 已合并，Draft PR #4 的取消竞态修复已通过 Windows 全量回归，但合并与 CI 均不等于真实验收 GO。

```text
Implementation: DONE
Original source-head Windows CI: PASS
Repair PR Windows CI: PASS — 383 passed
Physical wide terminal/task/Inspector: PASS with historical evidence
Physical narrow resize: PENDING
Physical post-fix TUI cancel: PENDING
Safe real/sanitized DB Doctor: PENDING
Overall: WAITING REAL TERMINAL ACCEPTANCE
```

## 2. 冻结范围

### 已实现

- [x] Textual optional extra 与 `paperclaw tui` 入口；
- [x] full-screen App；
- [x] `ChatLog`、`PromptInput`、`RunStatus`、`ToolTimeline`；
- [x] sanitized `VerificationInspector`；
- [x] Worker thread 包装同步 `QueryEngine.submit()`；
- [x] 单 active run 与重复提交拒绝；
- [x] `/help`、`/new`、`/cancel`、`/quit`；
- [x] cooperative stop 边界提示；
- [x] UI-local `run_id + sequence` reducer；
- [x] stale、duplicate、跨 run 与 terminal 后事件拒绝；
- [x] 结构化终态与调用计数显示；
- [x] missing Textual、no TTY、`--no-tui` fallback；
- [x] 窄终端单列布局实现与 headless 测试；
- [x] hidden reasoning 不进入 TUI；
- [x] TUI 架构边界静态测试；
- [x] Provider、Tool validate 和 Tool execute adapter 取消竞态边界；
- [x] 非 adapter runtime/session/persistence fault 保持 `runtime_failed`。

### 明确不在 v0.06 MVP

- token streaming；
- Shell stdout/stderr streaming 与后台任务；
- Permission Dialog；
- Session Picker / reconnect；
- Context、Trace、Cost 独立面板；
- MultiAgent DAG / Worker 面板；
- Web API / Web UI；
- 强制终止同步 provider call 或进程树。

## 3. 架构边界

```text
Textual App
├── ChatLog
├── ToolTimeline
├── VerificationInspector
├── RunStatus
└── PromptInput
        ↓
Worker thread
        ↓
QueryEngine
        ↓ structured events / RunResult
TUIEventBridge → EventReducer → widgets
```

关键规则：

1. `Textual` 保持 optional dependency；
2. TUI 不执行 Tool、不访问 SQLite、不拼 Prompt；
3. raw verification `checks` / `observed` 在 Bridge 边界删除；
4. `/cancel` 只调用 `QueryEngine.request_stop()`，不承诺强制中断；
5. 只有已在执行的 adapter call 可在 stop 后异常时转为 cooperative stop；
6. unrelated AgentRuntime/Session/Repository/persistence fault 不得被 stop token 隐藏。

## 4. 取消竞态契约

允许转换为 cooperative stop 的边界：

- Provider `complete()` 已开始后，stop 被接受，随后 Provider 抛异常；
- Tool `validate()` 已开始后，stop 被接受，随后发生非业务验证异常；
- Tool `execute()` 已开始后，stop 被接受，随后 Tool 抛异常。

转换前必须保留对应的 sanitized failure event。最终必须只有一个 run terminal event。

不允许转换：

- AgentRuntime 自身异常；
- Session open/finish 异常；
- Repository/SQLite 异常；
- 与正在执行的 Provider/Tool 无关的并发 fault。

## 5. Gate 矩阵

| 编号 | 场景 | 状态 | 证据 / 下一动作 |
|---|---|---|---|
| M06-01 | TUI launch | PASS, historical physical | 宽屏截图 |
| M06-02 | submit / UI non-blocking | PASS | Worker thread headless test |
| M06-03 | event order | PASS | stale / duplicate / post-terminal reducer tests |
| M06-04 | terminal result | PASS | completed / stopped tests |
| M06-05 | duplicate submit | PASS | blocking-engine test |
| M06-06A | Provider exception-after-stop | PASS | deterministic adapter test |
| M06-06B | Tool execute exception-after-stop | PASS | Draft PR #4 run #71 |
| M06-06C | unrelated runtime fault after stop | PASS | remains `runtime_failed` |
| M06-06D | physical post-fix `/cancel` | PENDING MANUAL | real Windows Terminal capture required |
| M06-07 | unknown event | PASS | payload suppressed, no crash |
| M06-08 | no Textual | PASS | fallback test |
| M06-09 | no TTY | PASS | CLI fallback tests |
| M06-10 | architecture boundary | PASS | AST import-boundary test |
| M06-11A | wide terminal | PASS, historical physical | `windows_terminal_wide.png` |
| M06-11B | narrow terminal below 80 cols | PENDING MANUAL | physical screenshot required |
| M06-12 | CLI regression | PASS | repair run #71, 383 passed |
| M06-13 | safe real/sanitized DB Doctor | PENDING MANUAL | quick/full redacted JSON |

## 6. 测试证据

### Repair PR #4

- implementation/test HEAD：`8e27bdcf908c9fbc81a726cd1dfb9fa82c13eb82`；
- GitHub Actions：run `29417443436` / #71；
- Windows pytest：383 passed，0 failed，0 skipped；
- Ruff high-signal gate：PASS；
- artifact：`pytest-results-29417443436`；
- 新增 Tool execute race fixture 已进入全量回归。

### Historical evidence

- PR #2 source HEAD run #45：382 passed；
- SQLite migrated-fixture Doctor quick/full：PASS smoke；
- Live Provider create/run/verify：PASS；
- Live Provider normal safe-boundary cancel：PASS，但不复现原物理 TUI failure signature；
- 物理宽屏 TUI task 与 Inspector：PASS with historical evidence。

## 7. 剩余真实验收

- [ ] Windows Terminal 小于 80 列不 crash、不损坏输入；
- [ ] 修复后物理 TUI `/cancel` 显示 stop request 并在 safe boundary 进入唯一终态；
- [ ] 对安全真实副本或脱敏数据库运行 Doctor quick/full；
- [ ] 所有证据脱敏；
- [ ] 最终 evidence review。

## 8. GO / NO-GO

当前判定：`WAITING REAL TERMINAL ACCEPTANCE`。

只有剩余三项人工 Gate 关闭并完成证据审查后，才可把 v0.06 改为 GO。不得因为 PR #2 已合并或 Draft PR #4 CI 全绿而跳过真实验收。
