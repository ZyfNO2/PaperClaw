# PaperClaw v0.01 实现摘要

实现了基于 PocketFlow `Node / Flow / shared / action routing` 的最小 ReAct Coding Agent。PocketFlow 核心固定自上游提交 `43ef382bb0c9dae8167528618bb40f5a3f9a28a5`，PaperClaw 业务代码独立位于 `src/paperclaw`。

关键取舍：使用标准库 dataclass 和显式 validator；五个工具通过统一 Registry 调度；文件路径以最终解析路径校验；PowerShell 命令固定 cwd、环境 allowlist、超时与输出上限；模型 adapter 采用 OpenAI-compatible HTTP 协议。

与 SOP 的偏差：当前环境未提供模型凭据，未执行真实模型 smoke；`ruff` 未安装，因此只完成 pytest 验证。完整 Permission Engine 明确延后。
