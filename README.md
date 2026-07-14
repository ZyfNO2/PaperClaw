# PaperClaw

PaperClaw 是一个面向 Coding / Research 场景的轻量 Agent Runtime。v0.01 以 PocketFlow 的 `Node / Flow / action routing` 为控制内核，实现了最小、可测试的 ReAct 编码循环。

## v0.01 已实现

- 单动作 `Reasoning → Acting → Observation` 循环；
- `file_read`、`file_write`、`file_edit`、`grep`、`bash` 五个工具；
- 工作区路径边界、唯一精确替换、覆写显式授权；
- 命令 cwd、超时、输出截断和最小 denylist；
- 非法 JSON、未知 action、工具错误和 `max_steps` 有界退出；
- OpenAI-compatible 模型 adapter 和 CLI；
- FakeModel 离线集成测试。

未实现：完整 Permission Engine、Session/Memory、Trace 持久化、Context Compaction、RAG、TUI、多 Agent。

## 安装与测试

```powershell
python -m pip install -e ".[dev]"
python -m pytest -q --basetemp=tmp/pytest
```

## 运行

在仓库根目录放置 `.env` 后，CLI 会自动读取它：

```powershell
paperclaw "创建 hello.py，使其输出 PaperClaw v0.01 OK，并运行验证" --workspace . --max-steps 8
```

如需在测试/调试时观察每轮 `thinking / tool / result / done` 事件，显式开启：

```powershell
paperclaw "创建 hello.py，使其输出 PaperClaw v0.01 OK，并运行验证" --workspace . --max-steps 8 --verbose-events
```

也可以显式使用模块入口：

```powershell
$env:PYTHONPATH='src'
python -m paperclaw.cli "创建 hello.py，使其输出 PaperClaw v0.01 OK，并运行验证" --workspace tmp/real_smoke --max-steps 8
```

CLI 只负责参数、`.env` 自动加载和输出。默认仅输出最终 JSON；`--verbose-events` 用于测试和调试时观察过程事件。工具执行与循环逻辑位于 `src/paperclaw`。v0.01 的 Bash 安全策略只是完整 Permission Engine 之前的最小边界，不应用于不可信、多租户或高权限环境。

## 上游

PocketFlow 核心来源与固定提交见 [UPSTREAM.md](UPSTREAM.md)，许可证见 [LICENSE](LICENSE)。
