# PaperClaw v0.09 MCP Transport Hardening SOP

> 状态：Implementation complete / CI pending  
> 分支：`test/v0.09-mcp-transport-hardening`  
> 基线：`main@872c4532fe00b3a3e8b72202fdd4c504594d8acc`  
> 范围：只补现有 MCP stdio transport 的边界、竞态与进程回收测试，不扩大产品能力。

## 覆盖

- oversized no-newline response 在 `max_message_bytes` 边界前后有界拒绝；
- stderr flood 不阻塞 stdout 协议通道；
- timeout 后 Session 保持 FAILED，迟到响应不能被复用；
- blocked read 期间 close 有界，request thread 可回收；
- pagination cursor loop fail-closed；
- 跨页 duplicate Tool 不提交部分 discovery；
- 深层但有界 JSON 不导致 reader thread 崩溃。

## 非目标

- reconnect；
- Resources / Prompts；
- 多 Server 路由；
- 第三方生产 Server interoperability；
- Permission、Context 或 Runtime 产品语义修改。

## Gate

- 定向测试全部通过；
- 全仓库非 live pytest 无回归；
- Ruff 高信号规则通过；
- 测试不把 Fake Server 表述为第三方互操作证明。
