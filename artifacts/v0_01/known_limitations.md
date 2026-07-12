# 已知限制

- `bash` denylist 不是完整 Permission Engine，无法替代真正的执行层权限隔离。
- Windows 下超时清理依赖 `taskkill /T /F`，跨平台进程树治理仍未实现。
- 当前模型输出契约仍偏“文字描述 + JSON”，工具参数 schema 没有细化到 prompt 内逐字段示例，因此真实模型偶尔会先试错一次参数名。
- v0.02 Verify 只做本地确定性 Gate，尚未接入持久化 Trace、Session / Memory、Context Compaction、RAG 或 Eval。
- 真实模型演示中，模型仍可能通过 `bash` 修改文件，这再次说明 v0.01/v0.02 的安全边界只是 MVP 级别，不适合高权限或不可信环境。
- `--verbose-events` 只是调试观测层，不是完整可检索、可回放、可授权分级的审计系统。
- MultiAgent、Lease、全局 Reviewer、持久事件存储仍属于 v0.03 及后续版本范围。
