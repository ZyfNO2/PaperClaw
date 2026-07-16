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

### A. 单 Agent Trace 使用体验 —— 已完成 ✅

执行 Run：`run-7677999f51d5`（OpenCode / `deepseek-v4-flash`）

```powershell
paperclaw trace inspect --database tmp/v0_07_mistral_trace_smoke/paperclaw.db --run-id run-7677999f51d5
paperclaw trace export --database tmp/v0_07_mistral_trace_smoke/paperclaw.db --run-id run-7677999f51d5 --output tmp/v0_07_manual_acceptance/trace.jsonl
paperclaw trace replay --database tmp/v0_07_mistral_trace_smoke/paperclaw.db --run-id run-7677999f51d5 --strict
paperclaw trace eval --database tmp/v0_07_mistral_trace_smoke/paperclaw.db --run-id run-7677999f51d5 --require-completed
```

- [x] Inspector/Eval 信息清晰，错误提示可指导下一步
- [x] JSONL 中无 API key、完整 prompt、hidden reasoning、完整文件正文、完整工具输出或 stdout/stderr 正文

### B. MultiAgent TUI 物理终端 —— 已完成 ✅

执行 Run：`team-b2701a28c650`（OpenCode / `deepseek-v4-flash`，plan 位于 `tmp/v0_07_manual_acceptance/team-plan.json`）

```powershell
python -m paperclaw.tui.team_runner `
  --plan .\tmp\v0_07_manual_acceptance\team-plan.json `
  --workspace .\tmp\v0_07_manual_acceptance\safe-workspace
```

逐项检查：

- [x] 宽终端时左右 panel 正常显示；
- [x] 缩窄至 87 列或更少时自动上下堆叠，无重叠、截断失控或崩溃；
- [x] 两个 Worker 的状态随真实 Provider 事件更新；
- [x] Reviewer verdict、fix round 和最终 stop reason 与实际结果一致；
- [x] active run 按 `R` 不会启动第二个 team；
- [x] active run 按 `Q` 不会强制退出（提示 `Cannot quit while the Coordinator is active`）；
- [x] terminal 后按 `Q` 可以正常退出；
- [x] 面板不显示 goal/objective、acceptance criteria、完整文件名、工具输出、
      review reasoning、异常正文或 API key；
- [x] 整个过程没有重复运行、状态倒退、画面损坏或无法退出。

### C. 可选外部系统验收 —— 已完成 ✅

使用本地临时 HTTPS collector（自签名证书，脚本位于 `tmp/local_https_collector.py`）：

```powershell
python tmp/local_https_collector.py --cert-dir tmp/collector-certs
$env:SSL_CERT_FILE = (Resolve-Path tmp/collector-certs/localhost.crt).Path
$env:PAPERCLAW_EXPORT_TOKEN = "test-token-acceptance"
paperclaw trace push `
  --database tmp/v0_07_mistral_trace_smoke/paperclaw.db `
  --run-id run-7677999f51d5 `
  --endpoint https://localhost:<port>/v1/traces `
  --allow-host localhost `
  --enable-external-export
```

验收结果：

- [x] HTTPS POST 成功，服务端返回 200
- [x] `Authorization: Bearer <token>` 认证头正确携带
- [x] 4 个事件完整接收：`run.started` → `model.started` → `model.completed` → `run.completed`
- [x] payload 中无 API key、完整 prompt、工具输出等敏感信息

## 当前不要求你测试

- pytest、Ruff 和 GitHub Actions：已经完成，不重复。
- Global Verify 的 Provider 测试：它是确定性聚合器，不调用模型或网络。
- Global Verify 的 CLI/TUI 操作：当前尚未接入 team-plan CLI；TUI 只预留 aggregate
  展示字段。没有可用用户入口时，不应把它列为人工失败。
- Mistral-specific 429/thinking-only：本轮使用用户选定的 OpenCode Provider；属于
  Provider 兼容矩阵，不是本次人工 UI 验收条件。

## 完成判定

- [x] A. 单 Agent Trace 使用体验 —— 通过
- [x] B. MultiAgent TUI 物理终端 —— 通过
- [x] C. 可选外部系统验收 —— 通过

**结论：v0.07 真实用户验收通过。**

验收日期：2026-07-16
验收执行者：用户 + ALLMIND
