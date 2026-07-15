# v0.06 本机真实验收记录

> 日期：2026-07-15
> Branch：`feat/v0.06-tui-mvp`
> 被测 HEAD：`0ef5b0b337cd2166598cca9996b02bed584cc7c5`

## 结论

| 验收项 | 结果 | 边界 |
|---|---|---|
| SQLite Doctor fixture `quick_check` | PASS (smoke) | 只读检查 pytest 生成的 v0.04 迁移后样本 |
| SQLite Doctor fixture `integrity_check` | PASS (smoke) | 不代表真实/脱敏用户数据库或业务语义正确 |
| Live Provider create/run/verify | PASS | 通过 QueryEngine E2E；不是物理 TUI 输入 |
| Windows Terminal full-screen / resize | PENDING MANUAL | 自动化规范禁止代替用户操控终端应用 |
| TUI 内 live `/cancel` | PENDING MANUAL | 必须在真实交互窗口观察 safe-boundary 行为 |
| Verification Inspector 实机可读性 | PENDING MANUAL | headless 测试已过，物理终端截图待补 |

## 环境（已脱敏）

- Windows：Microsoft Windows 11 专业版，build `26200`；
- Windows Terminal：`1.24.11321.0`；
- Python：`3.13.5`；
- Textual：`7.5.0`；
- Provider 配置：本地 `.env` 三个必需项均存在；未记录 key、base URL 或 model 值。

## SQLite Doctor fixture smoke

目标是仓库测试运行生成的 v0.04 migrated database 样本副本：

```text
tmp/pytest_run2/test_v0_04_mvp_demo0/demo.db
```

执行结果：

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

Doctor 使用只读连接，没有修复、迁移或修改目标数据库。该结果只关闭 migrated-fixture smoke，不关闭“真实或脱敏数据库副本”验收。

## Live Provider

命令：

```powershell
$base = Join-Path (Get-Location) '.tmp-real-provider-acceptance'
python -m pytest tests/e2e/test_v0_05_real_llm.py::test_real_llm_create_run_verify -v -m real_llm --durations=1 --basetemp $base
```

结果：

```text
1 passed in 31.12s
test call: 31.06s
```

已验证：

- 真实模型创建 `hello.py`；
- 文件包含测试要求的精确输出字符串；
- `RunResult.status == completed`；
- `model_calls > 0` 且 `tool_calls > 0`；
- 唯一 terminal event 为 `run.completed`。

首次执行使用 pytest 默认临时目录时遇到 `WinError 5`，发生在 setup 阶段且未调用 Provider；改用仓库内独立 `--basetemp` 后通过。临时目录已清理。

## 剩余人工 Gate

仍需完成两类人工 Gate：

1. 在 Windows Terminal 完成宽/窄 resize、Inspector 截图、TUI 内 live task，以及运行期间 `/cancel`；
2. 对一个非唯一生产副本或脱敏数据库副本运行 Doctor quick/full checks。

完成后将脱敏截图、最终 RunResult 和 Doctor JSON 放入本目录，并据此更新 SOP checkbox；在此之前 v0.06 保持 `WAITING REAL TERMINAL ACCEPTANCE`。
