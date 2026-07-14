# PaperClaw v0.06：Claw CLI / TUI 交互层 SOP 草案

> 状态：SOP 草案，待 v0.05 完成后冻结  
> 前置：v0.05 Harness Engineering 通过验收  
> 目标：为 PaperClaw 增加面向用户的 TUI 交互层，同时保持 Runtime 与 UI 解耦

> 执行前参考：[`PaperClaw_参考项目与可复用模块索引.md`](../../docs/reference/PaperClaw_参考项目与可复用模块索引.md) 中 v0.06 清单，重点阅读 AutoResearchClaw CLI / WebSocket / dashboard 交互契约和 PaperAgent 当前 Workbench / Trace 组件。

## 目录

- [交互定位、布局与组件](#1-交互层定位)
- [命令、权限与任务交互](#4-slash-commands)
- [演示、验收与 Web 边界](#8-最小演示)
- [技术选型、遗漏与风险](#11-技术选型草案)
- [实施阶段、Gate 与交付](#14-初步实施阶段)

## 1. 交互层定位

第一版 Claw 交互层采用 Textual TUI：

- 适合 Coding Agent 与 Runtime 调试；
- 可以实时显示 Tool、Permission、Context 和 Trace；
- 开发成本低于完整 Web；
- 面试演示更能突出 Agent Runtime，而不是前端页面。

TUI 是 Runtime Event 的消费者和 Command 的发送者，不拥有 Agent 业务逻辑。

## 2. 候选布局

```text
┌ PaperClaw ─ Session / Mode / Model ─────────────┐
│ Chat                                            │
│                                                 │
├ Tools / Agents / Tasks ─────────────────────────┤
│ tool status, worker status, verification        │
├ Context / Permission / Trace ───────────────────┤
│ token budget, snapshots, pending decisions      │
├─────────────────────────────────────────────────┤
│ > input or /command                             │
└─────────────────────────────────────────────────┘
```

## 3. 核心组件候选

```text
ChatPanel
PromptInput
ToolTimeline
AgentTaskPanel
ContextInspector
PermissionDialog
VerificationPanel
TracePanel
SessionPicker
StatusBar
```

## 4. Slash Commands

第一版候选：

```text
/new
/resume
/cancel
/mode
/context
/compact
/agents
/tasks
/tools
/permissions
/verify
/trace
/cost
/export
/quit
```

Slash Command 调用 Harness Command API，不直接访问数据库或工具实现。

## 5. Permission 交互

```text
Tool: BashTool
Command: pytest
Class: test
Risk: low
Reason: 验证修改

[Allow once] [Allow session] [Deny] [Edit]
```

高风险命令还应显示：

- 作用路径；
- 命令拆分结果；
- 是否 sandbox；
- Agent / Task；
- 预计运行方式；
- 历史拒绝。

## 6. Shell Task 交互

长测试和构建需要：

- 前台流式输出；
- 转后台；
- 查看后台列表；
- 取消；
- 完成通知；
- 结果回流当前 Run；
- 退出 TUI 后的明确处理策略。

## 7. MultiAgent 可视化

展示：

```text
Coordinator      planning
Worker A         editing src/a.py
Worker B         running tests
Reviewer         waiting
```

用户能查看 Task DAG、作用域、依赖、Worker Result 和 Reviewer Finding，但不直接看到或依赖隐藏 Chain-of-Thought。

## 8. 最小演示

1. 用户提交编码任务；
2. Chat 流式显示；
3. Tool Timeline 显示读、改、测试；
4. Bash 高风险动作弹 Permission Dialog；
5. Verify Panel 显示 Claim 和 Evidence；
6. MultiAgent Panel 显示 Worker 分工；
7. 用户取消一个 Run；
8. 重启 TUI 并恢复 Session。

## 9. 草稿验收方向

- TUI 不直接导入具体 Tool 实现；
- 所有界面状态来自 Runtime Event / Snapshot；
- 用户动作通过 Command API 返回 Harness；
- 流式刷新不阻塞 Agent Loop；
- Permission 等待可取消；
- 长输出可折叠、截断和引用；
- Session Resume 后状态一致；
- Windows Terminal 下稳定运行；
- 无颜色环境和窄终端有降级布局。

## 10. 后续 Web 边界

TUI 主要服务 Coding Agent、Runtime 调试和校招演示。SeededResearch 的 PDF、Evidence Graph、方法族、实验矩阵和报告管理更适合后续 Web UI。

长期形态：

```text
PaperClaw Harness
  ├── CLI
  ├── Textual TUI
  ├── Web API
  ├── Research Web UI
  └── Offline Eval Runner
```

等 v0.05 Runtime Event、Permission 和 Session API 稳定后，再编写 v0.06 正式 SOP。

## 11. 技术选型草案

| 能力 | 推荐选型 | 原因 / 限制 |
|---|---|---|
| TUI | Textual | Python 原生、Event/Widget/Worker 完整 |
| 富文本 | Rich / Textual Markdown | 复用生态，不自写 ANSI renderer |
| CLI | `argparse` 保持兼容 | 当前无依赖；TUI 作为 optional extra |
| UI 状态 | Runtime Event reducer + immutable snapshot | UI 不直接读 Tool / DB |
| 后台工作 | Textual Worker + Harness async task | 防止阻塞消息循环 |
| 样式 | 外部 `.tcss` | 逻辑与样式分离 |

Textual 官方说明 inline mode 当前不支持 Windows，因此 v0.06 默认全屏 application mode；不得把 inline mode 作为 Windows 验收路径。

## 12. 用户尚未覆盖的关键问题

- **非交互环境**：CI、重定向和无 TTY 环境必须自动回退普通 CLI。
- **可访问性**：无颜色、低对比度、键盘导航、屏幕宽度和中文宽字符。
- **事件风暴**：token delta 和 Shell stream 不能每字重绘全屏。
- **权限等待死锁**：用户关闭窗口或切 Session 时 pending request 必须取消或持久化。
- **后台任务归属**：切换 conversation 后仍要知道任务属于哪个 Run。
- **恢复后的 UI 一致性**：不能只恢复聊天文本而丢失 Task、Permission、Verify 和 Agent 状态。
- **日志与聊天分离**：默认界面不应把高频内部日志混入 Assistant 消息。
- **剪贴板与 Secret**：复制 Trace 时默认脱敏。
- **Windows Terminal 差异**：PowerShell、cmd、WSL、ConPTY、Unicode 和 resize 均需 fixture。

## 13. 风险推演与预案

| 场景 | 后果 | 预案 |
|---|---|---|
| Runtime Event 到达乱序 | 面板状态倒退 | 按 run_id + sequence reducer；检测 gap 后请求 snapshot |
| Shell 输出过快 | UI 卡顿 | 30–100ms batch；保留尾部；完整输出存 Trace 引用 |
| Permission Dialog 被关闭 | Run 永久等待 | 明确 close=deny_once 或 cancel；状态持久化 |
| Textual Worker 异常 | UI 无反馈 | worker.failed 转 Runtime/UI error panel，不吞异常 |
| 窄终端布局崩溃 | 无法演示 | 单列 fallback；隐藏 inspector；`/trace` 单独 screen |
| TUI 崩溃但 Agent 仍运行 | 用户失去控制 | 默认同进程取消；未来 daemon 模式需明确 reconnect token |
| MultiAgent 信息过载 | 用户看不懂 | 默认只显示 Coordinator + active task；详情按需展开 |
| Windows inline 不支持 | 启动失败 | 只提供 full-screen；普通 CLI 作为可靠 fallback |

## 14. 初步实施阶段

1. 保持现有 CLI 回归；
2. Event reducer 和 UI snapshot；
3. Chat / Prompt / Status 基础屏；
4. Tool / Verify / Agent / Context inspector；
5. Permission Dialog；
6. Shell Task stream / cancel；
7. Session picker / resume；
8. Windows Terminal、resize、无颜色、无 TTY 验收。

## 15. GO / 降级 / NO-GO

- `GO`：TUI 不阻塞 Runtime，Permission 可控，Session 状态完整，普通 CLI 保持可用。
- `降级`：先交付 Chat + Tool Timeline + Permission；Context/Eval 图形面板后置。
- `NO-GO`：TUI 直接调用工具、无 TTY 时无法运行、关闭权限弹窗导致永久挂起、UI 崩溃后后台副作用失控。

## 16. 预期交付

```text
artifacts/v0_06/
├── interaction_contract.md
├── tui_layout.md
├── windows_terminal_matrix.md
├── permission_ux_report.md
├── event_stress_report.md
└── demo_script.md
```
