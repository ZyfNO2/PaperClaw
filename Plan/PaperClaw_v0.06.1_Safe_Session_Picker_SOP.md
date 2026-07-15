# PaperClaw v0.06.1 Safe Session Picker SOP

> 状态：实现与自动化验收完成，等待真实终端验收
> 基线：`main@3804f72bbf0217c904c01dfabbcd046e3d930ca8`
> 分支：`feat/v0.06.1-safe-session-picker`
> Draft PR：`#3`

## 1. 用户故事

用户为 TUI 指定一个现有 PaperClaw SQLite 数据库后，可以：

1. 只列出已安全关闭的 conversation；
2. 查看只读消息 preview；
3. 选择一个 conversation reopen；
4. 下一次提交在同一 `conversation_id` 下创建新 Run。

旧 Run 必须保持 ended，不得追加事件、消息或修改终止状态。

## 2. 明确边界

本切片中的 reopen 是“重新打开 conversation”，不是恢复已结束 Run。

不包含：

- crash reconciliation；
- active process reconnect；
- checkpoint replay；
- arbitrary resume；
- daemon；
- 将历史消息自动注入模型 prompt；
- MultiAgent View；
- Global Verify。

## 3. Safe closed contract

conversation 只有同时满足以下条件才可显示：

- 至少存在一个 Run；
- latest Run 的 `ended_at` 非空；
- 不存在 `ended_at IS NULL` 的 Run。

list、preview、reopen selection 使用只读 SQLite 连接：

- `mode=ro`；
- `PRAGMA query_only = ON`；
- 不运行 migration；
- 不创建数据库；
- reopen selection 本身不写数据库。

TUI 启动时由现有 `SQLiteRepository` 负责显式 `--database` 的 migration 与后续新 Run 持久化。

## 4. Command API

`paperclaw.session_commands.SessionCommandAPI` 暴露：

- `list(limit=20)`；
- `preview(conversation_id, message_limit=8)`；
- `reopen(conversation_id, message_limit=8)`。

`reopen` 必须重新验证 safe-closed 条件，并只返回经过验证的 `conversation_id` 与 preview。

持久化装配由同一应用层模块中的 `PersistentSessionRuntime` 承担。TUI 目录不得直接导入 `paperclaw.context`、Repository 或 `sqlite3`。

## 5. TUI contract

启动：

```powershell
paperclaw tui --workspace . --database paperclaw.db
```

`--database` 的父目录必须已经存在。

命令：

- `/sessions`：列出 safe-closed conversations；
- `/preview <index|conversation_id>`：显示只读 preview；
- `/open <index|conversation_id>`：reopen conversation；
- `/new`：回到全新 conversation。

Run active 时，list / preview / open 都必须拒绝执行。

## 6. 实施清单

- [x] 只读 SafeSessionPicker；
- [x] UI 无关 SessionCommandAPI；
- [x] TUI `/sessions`；
- [x] TUI `/preview`；
- [x] TUI `/open`；
- [x] `--database` 接线；
- [x] 旧 Run 不变、新提交创建 fresh Run 的离线测试；
- [x] active Run 排除与 reopen revalidation 测试；
- [x] headless Textual 命令流测试；
- [x] TUI 架构门禁；
- [x] GitHub Actions Windows 全量 pytest：388 passed；
- [x] Ruff E9/F63/F7/F82 gate；
- [ ] Windows Terminal 真实 list → preview → open → submit 验收；
- [ ] Live Provider 确认新 Run 写入同一 conversation。

## 7. 自动化验收

GitHub Actions run `29417208949`：

- Windows Server 2025 / Python 3.12；
- `388 passed`；
- `0 failed`；
- `0 skipped`；
- Ruff high-signal checks：PASS。

建议复验命令：

```powershell
python -m pytest -q tests/unit/test_session_picker.py tests/unit/test_tui_session_picker.py tests/unit/test_tui_runner.py tests/unit/test_tui_architecture.py --basetemp=tmp/pytest-picker
python -m pytest -q -m "not real_llm" --basetemp=tmp/pytest
python -m ruff check src/paperclaw tests --select E9,F63,F7,F82 --ignore F821
```

自动化测试只能证明 SQLite contract、Command API、headless TUI 控制流和 fresh-Run 持久化；不能代替真实终端交互与 Live Provider 验收。

## 8. 真实验收

1. 准备至少一个已安全关闭 conversation 的数据库；
2. 使用 `paperclaw tui --database <path>` 启动；
3. 执行 `/sessions`；
4. 执行 `/preview 1`；
5. 执行 `/open 1`；
6. 提交一个真实任务；
7. 查询 SQLite，确认旧 Run 仍 ended，新 Run 使用同一 `conversation_id`；
8. 截图或保存脱敏日志。

通过条件：无 active conversation 被列出；preview 可读；open 后 UI 恢复历史消息；新提交创建新 Run；旧 Run 没有被修改。
