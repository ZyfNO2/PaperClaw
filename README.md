# PaperClaw

PaperClaw 是一个面向 Coding / Research 场景的轻量 Agent Runtime。当前实现重点是用 PocketFlow 风格控制流搭建一个可测试、可解释、可逐步扩展的编码 Agent，而不是直接堆一个重工作流框架。

当前仓库已完成：

- v0.01：最小 ReAct 编码 Agent；
- v0.02：Verify / Reflection Gate 基线。

尚未实现的设计项仍保持在 `Plan/` 和 `docs/desgin/` 中，不应视为已交付能力。

## 当前能力

### v0.01：最小 ReAct Loop

- 单步 `Reasoning -> Act -> Observation` 循环；
- 工具：`file_read`、`file_write`、`file_edit`、`grep`、`bash`；
- 工作区路径边界、显式覆盖写入、唯一精确替换；
- 命令超时、输出截断、基础 denylist；
- 非法 JSON、未知 action、工具错误、`max_steps` 有界退出；
- OpenAI-compatible 模型适配器；
- CLI 与 FakeModel 离线回归测试。

### v0.02：Verify / Reflection Gate

- `done` 从直接结束改为 `DoneProposal`；
- feature flag 控制的 Verify / Reflection Gate：`--enable-verification-gate`；
- VerificationPlan / VerificationEvidence / VerificationResult 契约；
- 文件存在、最新内容、验证命令时序检查；
- pytest / 相关命令摘要保留 `exit_code`、时长、截断标记与可解析统计；
- Reflection 只能消费已有 Evidence，不能伪造 Evidence 或删除 failed claims；
- 重复失败 signature 检测与 Reflection 轮数上限；
- 内存态结构化 trace，可导出 Verify / Reflection 事件。

## 安装与测试

```powershell
python -m pip install -e ".[dev]"
python -m pytest -q --basetemp=tmp/pytest
```

当前基线测试结果：

- `43 passed, 1 skipped`

## 运行

CLI 会自动读取仓库根目录 `.env` 中的：

- `PAPERCLAW_API_KEY`
- `PAPERCLAW_BASE_URL`
- `PAPERCLAW_MODEL`
- `PAPERCLAW_TIMEOUT_SECONDS`（可选）

最小运行示例：

```powershell
paperclaw "创建 hello.py，使其输出 PaperClaw v0.01 OK，并运行验证" --workspace . --max-steps 8
```

启用 v0.02 Gate：

```powershell
paperclaw "修复当前目录代码并运行验证" --workspace . --max-steps 10 --enable-verification-gate
```

如需在测试 / 调试时观察过程日志，可显式开启：

```powershell
paperclaw "修复当前目录代码并运行验证" --workspace . --max-steps 10 --enable-verification-gate --verbose-events
```

`--verbose-events` 只用于测试 / 调试观测；默认运行仍只输出最终 JSON。

## 重要限制

- 当前 `bash` 安全策略只是 v0.01 的最小边界，不是完整 Permission Engine；
- v0.02 Verify 仍主要依赖本地可确定性检查，尚未接入完整 Session / Memory / 持久 Trace；
- MultiAgent、Context、Permission Engine、Eval、RAG 仍在后续 SOP 中。

## 上游

PocketFlow 来源与固定提交见 [UPSTREAM.md](./UPSTREAM.md)，许可证见 [LICENSE](./LICENSE)。
