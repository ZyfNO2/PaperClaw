# PaperClaw Claude Code 入口

> 根 `AGENTS.md` 是唯一项目规则源。本文件只说明 Claude Code 环境如何进入项目，不复制架构、测试或旧 PaperAgent 规则。

## 开始任务前

1. 阅读 `AGENTS.md`。
2. 运行 `git status --short` 和 `git log --oneline -15`。
3. 根据任务读取当前 SOP、相关代码、测试和 `artifacts/v0_XX/`。
4. 编写或执行新 SOP 前读取 `docs/reference/PaperClaw_参考项目与可复用模块索引.md`。
5. 区分 planned、implemented、offline validated、live validated 和 release accepted。

## 当前入口

- 已完成 v0.04：`Plan/drafts/PaperClaw_v0.04_ContextSessionSQLite_SOP草案.md`；
- 已完成 v0.05：`Plan/PaperClaw_v0.05_HarnessQueryEngine_MVP_SOP.md`；
- 当前 v0.06 草案：`Plan/drafts/PaperClaw_v0.06_Claw交互层_SOP草案.md`；
- v0.06 增强候选：`Plan/drafts/PaperClaw_v0.06.1_Claw交互增强候选池.md`。

增强候选不是默认执行任务。没有用户授权，不自动进入下一版本。

## Claude Code Hook

`.claude/settings.json` 在 Stop 时运行：

```powershell
python .claude/hooks/sop_completion_check.py
```

该 Hook 只检查当前 PaperClaw SOP 的 checkbox 和 `artifacts/v0_XX/` 交接物，不修改代码、不联网，也不替代真实测试。

如果 Hook 与当前 SOP 文件名或交接清单不一致，先修 Hook 的项目适配，再使用其结论；不得回退到 PaperAgent `Re*` 命名。

## 常用验证

```powershell
python -m pytest -q --basetemp=tmp/pytest
python .claude/hooks/sop_completion_check.py
git diff --check
```

只运行与当前范围相称的测试。具体测试、提交、Review、文档同步和安全边界全部遵循 `AGENTS.md`。
