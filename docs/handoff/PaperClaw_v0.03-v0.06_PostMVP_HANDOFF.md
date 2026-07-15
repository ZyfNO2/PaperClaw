# PaperClaw v0.03–v0.06 Post-MVP 选做切片 Handoff

## 状态

**PARTIAL COMPLETE / WAITING REAL TERMINAL ACCEPTANCE**

26 个候选包或延期行已完成审计。两个可以在当前前置能力上独立落地的小切片已实现并通过自动化 CI；其余项目保持条件性或 backlog，没有伪造 Runtime 前置能力。

## 仓库与分支

- Repository：`ZyfNO2/PaperClaw`
- Branch：`feat/v0.06-tui-mvp`
- Base：`main`
- Draft PR：`#2`
- 实现提交：
  - `6f42a06d2c00d6d9c43974d2ac62f6881b8505a1` — SQLite Doctor
  - `973139a6e7c2e5544c6b4f3b2285fbf64f2ed930` — Verification Inspector

## 已完成内容

### SQLite Doctor

- 新增只读数据库健康检查模块；
- 新增 `paperclaw doctor --database ... [--full]`；
- quick/integrity check、foreign-key check、schema version；
- read-only/query-only 打开方式；
- missing/corrupt fail-closed；
- 确定性测试和 CLI 测试。

### Verification Inspector

- 在现有 TUI timeline 区增加单一 Verify 面板；
- 只显示结构化 aggregate；
- Bridge 在 UI 前删除 raw checks/observed；
- 保持 monotonic reducer 与现有 QueryEngine 契约；
- headless Textual、sanitization 和 reset 测试。

## 主要文件

- `src/paperclaw/context/health.py`
- `src/paperclaw/cli.py`
- `src/paperclaw/tui/bridge.py`
- `src/paperclaw/tui/widgets.py`
- `src/paperclaw/tui/app.py`
- `src/paperclaw/tui/paperclaw.tcss`
- `tests/unit/test_context_health.py`
- `tests/unit/test_verification_inspector.py`
- `tests/unit/test_tui_bridge.py`
- `tests/unit/test_tui_app.py`
- `Plan/PaperClaw_v0.03-v0.06_PostMVP_Option_Audit.md`
- `artifacts/post_mvp_v003_v006/`

## 关键架构决定

1. Doctor 独立于 Repository runtime lifecycle，不通过 `SQLiteRepository(..., migrate=True)` 打开目标库，避免诊断本身改变现场。
2. Doctor 只报告事实，不自动 backup、repair、rollback 或 purge。
3. Verification Inspector 消费现有结构化 Verify event，不反向增加 QueryEngine 字段或第二套状态机。
4. raw check observed output 在 Bridge 边界删除，而不是依赖 Widget 自觉隐藏。
5. 没有实现 async、ShellTask、Permission、EventBus、durable mailbox 或 Global Verify；这些能力仍需要各自启动证据。

## 测试与 CI

代码提交 `973139a6e7c2e5544c6b4f3b2285fbf64f2ed930`：

- GitHub Actions run #42 / `29363818831`：SUCCESS；
- Windows pytest：380 passed，0 failed，0 skipped；
- Ruff high-signal checks：PASS；
- artifact：`pytest-results-29363818831`。

## 真实验收补充（2026-07-15）

### A. SQLite Doctor — PASS

在 v0.04 migrated database 样本上执行 `quick_check` 与 `integrity_check`，两者均返回 `ok=true`、`messages=["ok"]`、schema version 3。检查使用只读连接，没有 migration、repair 或数据修改。

### B. Live Provider backend — PASS

`test_real_llm_create_run_verify` 使用本地 Provider 配置通过：`1 passed in 31.12s`。已确认真实 model/tool 调用、文件创建、completed RunResult 和唯一 `run.completed` 终态。

完整脱敏证据见 `artifacts/v0_06/real_acceptance/acceptance_report.md`。

## 仍未执行的真实 UI 测试

### Windows Terminal + Live Provider

```powershell
python -m pip install -e ".[dev,tui]"
paperclaw tui --workspace .
```

提交会触发 Verify Gate 的文件创建/运行任务，确认：

- Inspector 显示 passed/failed/uncovered 数量；
- `verified_after_last_write` 与实际验证顺序一致；
- summary 可读且没有原始命令完整输出；
- 窄终端 resize 不 crash；
- `/cancel` 仍只承诺 safe-boundary cooperative stop。

请返回脱敏后的截图、终端日志和 TUI RunResult。Doctor JSON 与 backend live-provider 证据已经留档，无需重复执行。

## 已知限制

- Doctor 不执行 backup、restore、migration rollback、retention 或自动修复；
- SQLite `integrity_check` 成功不等于业务语义正确；
- Inspector 只显示最终 VerificationResult，不逐条流式显示 checks；
- Inspector 不等于 project-level Global Verify；
- TUI 仍是单 QueryEngine active run，不支持 MultiAgent View；
- v0.06 的真实 Windows Terminal / Live Provider Gate 仍未关闭。

## 下一位开发者接手步骤

```powershell
git fetch origin
git switch feat/v0.06-tui-mvp
python -m pip install -e ".[dev,tui]"
python -m pytest -q --basetemp=tmp/pytest -m "not real_llm"
python -m ruff check src/paperclaw tests --select E9,F63,F7,F82 --ignore F821
```

随后完成上述两组真实测试。只有证据齐备后，才更新 PR 描述和对应状态；不要把本 Handoff 当作 v0.03–v0.06 所有 Post-MVP 能力已经完成。
