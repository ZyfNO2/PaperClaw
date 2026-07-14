# 已知限制

- Bash denylist 不是完整 Permission Engine，无法替代 OS sandbox。
- Windows Bash 超时通过 `taskkill /T /F` 终止进程树并有 canary 测试；跨平台进程树治理延后。
- 模型 JSON repair 仅支持完整 JSON 或单个 fenced JSON，不做宽松猜测。
- v0.01 没有 Session、Memory、持久 Trace、Context Compaction、RAG、TUI 或多 Agent。
- 文件写入尚非原子写入。
- 虽然真实模型 smoke 已通过，但 `bash` 仍可绕过 `file_write` 的 overwrite 约束直接改写文件；这再次说明 denylist 不是完整 Permission Engine。
- `--verbose-events` 仅是测试/调试观测层，不是持久 Trace 系统，也不提供可回放、可筛选或权限分级的运行审计能力。
