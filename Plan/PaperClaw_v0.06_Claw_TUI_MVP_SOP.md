# PaperClaw v0.06：Claw TUI MVP SOP

> 版本：v0.06
> 状态：**实现与离线 CI 已完成；等待真实 Windows Terminal / Live Provider 交互验收**
> 更新：2026-07-15
> 分支：`feat/v0.06-tui-mvp`
> Draft PR：`#2`
> 前置：v0.05 QueryEngine MVP

## 1. 版本结论

v0.06 已实现为现有同步 `QueryEngine` 的可选 Textual 薄客户端。TUI 不执行 Tool、不访问 SQLite、不拼 Prompt，也不改变 v0.05 的同步或 cooperative-stop 契约。

当前判定为：

```text
Implementation: DONE
Focused offline tests: PASS
Full Windows CI: PASS
Real Windows Terminal smoke: PENDING
Live provider interactive task/cancel: PENDING
Overall: WAITING REAL TEST
```

## 2. MVP 用户故事

```text
paperclaw tui
→ 用户提交任务
→ Textual Worker thread 调用同步 QueryEngine.submit()
→ ChatLog 显示用户输入与最终 output
→ ToolTimeline 显示结构化 model/tool/verification/run 事件
→ RunStatus 显示 run_id、状态、停止原因与调用计数
→ /cancel 请求 cooperative stop
→ Textual 缺失、无 TTY 或 --no-tui 时回退既有 CLI
```

## 3. 冻结范围

### 已实现

- [x] Textual optional extra 与 `paperclaw tui` 入口；
- [x] full-screen App；
- [x] `ChatLog`、`PromptInput`、`RunStatus`、`ToolTimeline`；
- [x] Worker thread 包装同步 `QueryEngine.submit()`；
- [x] 单 active run 与重复提交拒绝；
- [x] `/help`、`/new`、`/cancel`、`/quit`；
- [x] cooperative stop 边界提示；
- [x] UI-local `run_id + sequence` reducer；
- [x] stale、duplicate、跨 run 与 terminal 后事件拒绝；
- [x] 结构化终态与调用计数显示；
- [x] Textual 缺失、无 TTY、`--no-tui` fallback；
- [x] 窄终端单列布局；
- [x] 隐藏 reasoning 不进入 TUI；
- [x] TUI 架构边界静态测试；
- [x] CLI 回归进入全量测试。

### 明确延期到 v0.06.1

- token streaming；
- Shell stdout/stderr streaming 与后台任务；
- Permission Dialog；
- Session Picker / reconnect；
- Context、Verify、Trace、Cost 独立面板；
- MultiAgent DAG / Worker 面板；
- Web API / Web UI；
- 强制终止同步 provider call 或进程树。

## 4. 架构

```text
Textual App
├── ChatLog
├── ToolTimeline
├── RunStatus
└── PromptInput
        ↓
Worker thread
        ↓
QueryEngine
        ↓ structured events / RunResult
TUIEventBridge → EventReducer → widgets
```

关键决定：

1. `Textual` 是 optional dependency，`paperclaw agent` 不导入 Textual；
2. `TUIEventBridge` 只把既有 `verification_completed` 映射为 `verification.completed`，其余 legacy reasoning 事件丢弃；
3. bridge 使用 UI-local 单调 sequence，并保留原 QueryEngine sequence 为 `query_sequence`；
4. reducer 独立于 Textual，可确定性测试乱序、重复、未知事件和终态保护；
5. `/cancel` 只调用 `QueryEngine.request_stop()`，不宣称强制中断模型或进程。

## 5. 实施结果

### Phase A：Skeleton 与 Runtime Adapter — DONE

- [x] optional dependency；
- [x] TUI entrypoint；
- [x] 四个 MVP widgets；
- [x] Worker thread；
- [x] bridge 与 reducer；
- [x] CLI 原入口保持不变。

### Phase B：最小交互闭环 — DONE

- [x] submit 与单 active run；
- [x] model/tool/verification/terminal timeline；
- [x] 四条 Slash Commands；
- [x] RunResult、stop_reason 与调用计数；
- [x] missing Textual / no TTY / explicit fallback。

### Phase C：验证与留档 — PARTIAL

- [x] Textual headless/widget tests；
- [x] stale/duplicate/terminal reducer tests；
- [x] cooperative cancel 与 duplicate submit tests；
- [x] missing Textual / no TTY / CLI fallback tests；
- [x] architecture-boundary test；
- [x] Windows GitHub Actions full regression；
- [x] Ruff high-signal gate；
- [x] artifacts 与 Handoff；
- [ ] 真实 Windows Terminal full-screen / resize smoke；
- [ ] 真实 Provider 任务从输入到结构化终态；
- [ ] 真实运行期间 `/cancel` safe-boundary 行为观察。

## 6. Gate 矩阵

| 编号 | 场景 | 状态 | 证据 |
|---|---|---|---|
| M06-01 | TUI launch | PASS | Textual headless App，四个组件存在 |
| M06-02 | submit / UI non-blocking | PASS | Worker thread headless test |
| M06-03 | event order | PASS | stale / duplicate / post-terminal reducer tests |
| M06-04 | terminal result | PASS | completed 与 stopped headless tests |
| M06-05 | duplicate submit | PASS | blocking-engine headless test |
| M06-06 | cooperative cancel | PASS (offline) | `/cancel` → `request_stop`; real provider pending |
| M06-07 | unknown event | PASS | unknown payload 不渲染、不 crash |
| M06-08 | no Textual | PASS | optional dependency fallback test |
| M06-09 | no TTY | PASS | CLI fallback / usage error tests |
| M06-10 | architecture boundary | PASS | AST import-boundary test |
| M06-11 | terminal smoke | PARTIAL | Windows CI + narrow headless PASS；真实终端 pending |
| M06-12 | CLI regression | PASS | full Windows pytest suite |

## 7. 测试结论

- Focused local fixture：`10 passed`；
- GitHub Actions CI run：`29361795132`；
- Windows pytest：`376 passed`，`0 failed`，`0 skipped`；
- Ruff：PASS；
- 真实终端与 Live Provider：未执行，不得描述为真实 E2E。

## 8. GO / NO-GO

当前不是最终 GO，而是 `WAITING REAL TEST`。

转为 GO 的条件：

- [ ] Windows Terminal 中 `paperclaw tui` 正常启动；
- [ ] 100+ 列双栏与小于 80 列单列均不 crash；
- [ ] Live Provider 完成一条 create/run/verify 任务；
- [ ] 运行期间 `/cancel` 显示 stop request，最终在安全边界得到 terminal result；
- [ ] 将真实日志、截图与环境信息补入 `artifacts/v0_06/`，且完成脱敏。
