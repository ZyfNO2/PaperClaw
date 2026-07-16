# PaperClaw v0.07 人工验收剩余清单

> 基线：`main@78b46b7e021b0da769345480fac09f3b03d41437`  
> 日期：2026-07-16  
> 目的：只列必须由用户在真实终端中补充的体验验收，不重复 pytest、Ruff 或 CI。

## 已由 Codex 使用真实 API 完成

| 场景 | 结果 | 关键证据 |
|---|---|---|
| Durable Trace smoke | PASS | OpenCode / `deepseek-v4-flash`；4 events；单一 `run.completed`；SQLite、JSONL 无 API key |
| Guarded Live Replay | PASS | 新 Run `run-0ac190de7ac6`；1 次真实模型调用；源 DB SHA-256 前后不变 |
| MultiAgent Coordinator | PASS | 2 个并行 Worker；2 次模型调用；Reviewer `approve`；9 个顺序事件；`all_tasks_completed` |
| MultiAgent View projection | PASS | `completed_count=2`、`review_verdict=approve`、terminal=true；goal、objective、结果 marker 未进入 Snapshot |

本轮没有重新运行 pytest 或 Ruff。最终 GitHub CI 结果沿用用户提供的
run `29493895061`：503 passed，Ruff PASS。

## 你需要完成的人工验收

### A. 单 Agent Trace 使用体验

1. 在 Windows Terminal 使用正常 TUI 和 OpenCode 完成一个真实任务。
2. 找到该 Run 的 `run_id`，依次执行：

```powershell
paperclaw trace inspect --database <db> --run-id <run_id>
paperclaw trace export --database <db> --run-id <run_id> --output trace.jsonl
paperclaw trace replay --database <db> --run-id <run_id> --strict
paperclaw trace eval --database <db> --run-id <run_id> --require-completed
```

3. 主观确认 Inspector/Eval 信息容易理解，错误提示能够指导下一步。
4. 打开 JSONL，确认没有 API key、Prompt 全文、hidden reasoning、完整文件正文、
   完整工具输出、stdout 或 stderr 正文。

### B. MultiAgent TUI 物理终端

准备一个至少包含两个独立 task 的 plan 和一次性 workspace，然后运行：

```powershell
python -m paperclaw.tui.team_runner `
  --plan .\team-plan.json `
  --workspace .\safe-workspace
```

逐项检查：

- [ ] 宽终端时左右 panel 正常显示；
- [ ] 缩窄至 87 列或更少时自动上下堆叠，无重叠、截断失控或崩溃；
- [ ] 两个 Worker 的状态随真实 Provider 事件更新；
- [ ] Reviewer verdict、fix round 和最终 stop reason 与实际结果一致；
- [ ] active run 按 `R` 不会启动第二个 team；
- [ ] active run 按 `Q` 不会强制退出；
- [ ] terminal 后按 `Q` 可以正常退出；
- [ ] 面板不显示 goal/objective、acceptance criteria、完整文件名、工具输出、
      review reasoning、异常正文或 API key；
- [ ] 整个过程没有重复运行、状态倒退、画面损坏或无法退出。

### C. 可选外部系统验收

只有你已经有安全的真实 collector 时才执行 `paperclaw trace push`，检查认证、
超时和服务端接收结果。没有 collector 时可以跳过；Codex 已完成真实 HTTPS
loopback POST 验收。

## 当前不要求你测试

- pytest、Ruff 和 GitHub Actions：已经完成，不重复。
- Global Verify 的 Provider 测试：它是确定性聚合器，不调用模型或网络。
- Global Verify 的 CLI/TUI 操作：当前尚未接入 team-plan CLI；TUI 只预留 aggregate
  展示字段。没有可用用户入口时，不应把它列为人工失败。
- Mistral-specific 429/thinking-only：本轮使用用户选定的 OpenCode Provider；属于
  Provider 兼容矩阵，不是本次人工 UI 验收条件。

## 完成判定

A、B 全部通过即可把 v0.07 标记为“真实用户验收通过”。C 为可选项。若失败，
请记录命令、终端宽度、截图、Run ID 和可脱敏的错误信息，不要记录 API key。
