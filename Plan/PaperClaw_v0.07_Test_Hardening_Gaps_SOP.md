# PaperClaw v0.07 Test Hardening Gaps — Cloud Development SOP

> 状态：**OFFLINE GO / Draft PR #17 / final-head CI pending**
> 基线：`main@ec1ecbeaf37c0e6ea85a07c12446b3d8f9b8e409`
> 分支：`test/v0.07-hardening-gaps`
> 前置：PR #5–#11 与 #13 已合并

## 1. 背景

PR #13 已完成 Provider failure matrix、Trace corruption/determinism、Exporter 边界、Eval threshold、10k Inspector 和 Live Replay isolation 的第一轮 hardening。

本任务只补 PR #13 未交付的四个独立缺口，不重复已有测试：

1. Golden Eval dataset；
2. 本地 mock collector server；
3. property-based Trace fuzzing；
4. full runtime-to-trace integration scenario。

当前开放的 PR #14–#16 只涉及 MultiAgent Global Verify、View Adapter 和 TUI panel。本分支直接基于当前 `main`，不依赖这些分支，也不修改其文件。

## 2. Work Package

### WP1 — Golden Eval Dataset

交付：

- [x] `tests/fixtures/eval_golden/manifest.json`；
- [x] completed success；
- [x] provider retry threshold failure；
- [x] tool failure / failed terminal；
- [x] partial trace；
- [x] manifest-driven regression test。

验收：

- fixture 文件集合与 manifest 一致；
- `overall_passed`、`failed_checks`、terminal 和选定 metrics 固定；
- threshold 边界变化必须显式更新 golden expectation。

### WP2 — Property-Based Trace Fuzzing

交付：

- [x] Hypothesis dev dependency；
- [x] 随机合法 model/tool lifecycle；
- [x] `validate → inspect → replay → eval` 确定性；
- [x] 随机 secret redaction；
- [x] 随机 sequence monotonicity。

验收：

- 至少 100 个合法 lifecycle examples；
- 至少 100 个 secret examples；
- 至少 150 个 sequence examples；
- 无未预期异常；
- 非递增 sequence 必须 fail closed。

### WP3 — Local Mock Collector

生产 endpoint 仍必须通过 HTTPS、host allowlist 和非 IP literal 校验。测试 transport 仅在测试进程内将已验证的 request 路由至本地 `ThreadingHTTPServer`。

覆盖：

- [x] 200 + request ID；
- [x] bearer token 仅在 header；
- [x] Trace payload 二次脱敏；
- [x] 400 / 401 / 429 / 500；
- [x] timeout；
- [x] connection failure；
- [x] collector response body 不进入错误信息。

### WP4 — Full Integration Scenario

执行链：

```text
FakeModel
  → AgentRuntimeExecutor
  → real file_write
  → QueryEngine
  → SessionService / SQLite
  → SQLiteTraceReader
  → Inspector
  → Recorded Replay
  → Eval
  → JSONL export/load
```

验收：

- [x] Run completed；
- [x] 文件写入成功；
- [x] model/tool call 数正确；
- [x] replay faithful；
- [x] Eval PASS；
- [x] JSONL round-trip 相等；
- [x] SQLite 读取前后 SHA256 不变；
- [x] task、文件正文和路径不进入 Trace JSONL。

## 3. 非目标

- 不增加新的 runtime feature；
- 不修改 Provider retry policy；
- 不修改 Trace schema；
- 不执行真实 Mistral；
- 不连接真实 external collector；
- 不执行 live replay；
- 不修改 PR #14–#16 的 MultiAgent 文件；
- 不合并任何 PR。

## 4. CI Gate

```powershell
python -m pip install -e ".[dev]"
python -m pytest -q -m "not real_llm" --basetemp=tmp/pytest
python -m ruff check src/paperclaw tests --select E9,F63,F7,F82 --ignore F821
```

必须记录：

- Windows pytest pass/fail/skip 精确数量；
- Ruff 结果；
- workflow run ID；
- artifact ID 与 digest；
- 所有修复过的真实回归。

## 5. 首轮验收事实

GitHub Actions run `29453571098` / #149：

- Windows pytest：485 passed / 0 failed / 0 skipped；
- pytest exitstatus：0；
- Ruff E9/F63/F7/F82：PASS；
- artifact ID：`8358539315`；
- digest：`sha256:c9227a78fe502de82d97f6d363bc9971ff5f09aed1410caf67e5c4ffb539b658`。

精确数量来自 `pytest_reportlog.jsonl` 独立解析。

## 6. 停止条件

仅在以下条件停止：

- final head CI 全绿并完成 Handoff；
- GitHub 权限或执行环境阻止继续；
- 发现需要修改生产合同且无法在 test-only hardening 范围内安全解决。
