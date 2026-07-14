# PaperClaw v0.06：Claw TUI MVP SOP 草案

> 状态：**MVP 草案，待执行前冻结**
> 更新：2026-07-15
> 前置：使用现有同步、单会话 QueryEngine，不反向扩大 v0.05
> 目标：用户能在一个轻量 TUI 中提交任务、观察关键运行事件、请求停止并看到结构化结果，同时保留可靠 CLI fallback。

## 目录

- [1. 拆分结论](#1-拆分结论)
- [2. MVP 用户故事](#2-mvp-用户故事)
- [3. 技术路径与选择](#3-技术路径与选择)
- [4. MVP 范围](#4-mvp-范围)
- [5. 最小架构与交互](#5-最小架构与交互)
- [6. 实施阶段](#6-实施阶段)
- [7. 测试与 Gate](#7-测试与-gate)
- [8. 演示与交付](#8-演示与交付)
- [9. 后续增强边界](#9-后续增强边界)
- [10. 风险预案](#10-风险预案)
- [11. 既有实现参考](#11-既有实现参考)

---

## 1. 拆分结论

旧草案一次要求十个组件、十五个 Slash Commands，并同时覆盖 Chat、Permission Dialog、Shell streaming、MultiAgent 可视化、Context / Verify / Trace inspector、Session Resume 和完整终端兼容矩阵。

这些能力依赖不同的 Runtime enhancement，不能作为一个 TUI MVP 同时实施。v0.06 现在只证明：

> TUI 是 QueryEngine 的薄客户端；它能提交任务、消费已有事件、显示终态，并在不可用时安全回退 CLI。

---

## 2. MVP 用户故事

```text
用户运行 paperclaw tui
→ 输入“创建 hello.py，运行并验证”
→ TUI 通过 QueryEngine.submit() 创建 Run
→ 状态栏显示 running
→ 时间线显示 model / tool / verification 关键事件
→ Run 完成后显示 output、status、stop_reason
→ 用户可开始新任务或退出
```

补充路径：

- 用户输入 `/cancel`，QueryEngine 在下一个安全边界 cooperative stop；
- Textual 未安装、无 TTY 或显式 `--no-tui` 时，普通 CLI 仍可运行；
- Permission deny 只作为事件展示，不在 MVP 中新增交互式授权。

---

## 3. 技术路径与选择

| 路径 | 做法 | 优点 | 风险 |
|---|---|---|---|
| A：完整 Runtime Dashboard | 一次实现权限、后台任务、MultiAgent、Context 和 Trace 面板 | 功能丰富 | 强依赖未实现的 async / permission / event 能力 |
| B：薄 TUI Client | 只包装 QueryEngine 与已有 EventHandler | 可演示、低耦合、易回退 | 暂不具备完整 Claude Code 交互 |

采用方案 B。

| 能力 | MVP 选择 | 边界 |
|---|---|---|
| TUI | Textual optional extra | Windows 使用 full-screen，不依赖 inline mode |
| 富文本 | Textual / Rich 内置能力 | 不自写 ANSI renderer |
| Runtime 调用 | Textual Worker thread 包装同步 `QueryEngine.submit()` | 不把 v0.05 改造成 async |
| UI 状态 | `run_id + sequence` 的最小 reducer | 不创建通用 EventBus |
| CLI | 保留现有 `argparse` 路径 | TUI 故障不阻断核心 Agent |
| 样式 | 一份最小 `.tcss` | 不在 MVP 建设计系统 |

---

## 4. MVP 范围

### 4.1 必做

- `paperclaw tui` 或等价独立入口；
- Textual 为 optional dependency；
- 一个 full-screen Application；
- `ChatLog`：显示用户输入与最终 Agent 输出；
- `PromptInput`：提交任务和 Slash Command；
- `RunStatus`：run_id、status、stop_reason、调用计数；
- `ToolTimeline`：显示关键生命周期事件，不显示隐藏 Chain-of-Thought；
- Textual Worker 中调用同步 QueryEngine；
- `/new`、`/cancel`、`/quit`、`/help`；
- terminal event 唯一、事件 sequence 不倒退；
- Textual 缺失 / 无 TTY 时给出清晰 CLI fallback；
- Windows Terminal 基础 smoke；
- 窄终端下退化为单列而不 crash。

### 4.2 不作为 v0.06 Gate

- token streaming；
- Shell stdout / stderr 实时流；
- background Shell 和任务通知；
- 强制终止模型请求或进程树；
- Permission Dialog、allow once / session；
- Session Picker、历史 Session 列表与 reconnect；
- Context、Verify、Trace、Cost 独立面板；
- MultiAgent DAG / Worker 面板；
- `/resume`、`/compact`、`/agents`、`/trace`、`/export` 等高级命令；
- Web API / Web UI；
- daemon mode；
- 完整无障碍、剪贴板脱敏和终端兼容矩阵；
- 性能压力与事件风暴治理。

上述内容进入 v0.06.1 候选池，不得反向扩大 MVP。

---

## 5. 最小架构与交互

### 5.1 组件关系

```text
Textual App
├── ChatLog
├── ToolTimeline
├── RunStatus
└── PromptInput
        ↓ command
TUI Controller / Adapter
        ↓
QueryEngine
        ↓ event_handler
UI Message Queue
        ↓
run_id + sequence reducer
```

硬边界：

- Widget 不导入具体 Tool；
- TUI 不直接读写 SQLite；
- TUI 不拼 Agent Prompt；
- TUI 不判断 Permission；
- TUI 不修改 RunResult；
- 所有 Runtime 状态来自 QueryEngine event / result。

### 5.2 同步 QueryEngine 适配

`QueryEngine.submit()` 当前是同步调用。MVP 使用一个 Textual Worker thread 执行它，UI 主循环只消费消息：

```text
Prompt submit
→ disable duplicate submit
→ start worker thread
→ QueryEngine event_handler posts UI message
→ reducer rejects stale sequence
→ terminal RunResult re-enables input
```

MVP 只允许一个 active run。第二次 submit 必须被 UI 拒绝并解释原因。

### 5.3 Slash Commands

```text
/help    显示四个 MVP 命令
/new     清空当前展示并创建新 conversation / engine
/cancel  调用 QueryEngine.request_stop(active_run_id)
/quit    无 active run 时退出；有 active run 时先确认
```

`/cancel` 只能承诺 cooperative stop。界面必须明确“正在运行的同步模型或 Shell 可能要到安全边界才停止”。

### 5.4 Timeline 事件

MVP 只渲染：

```text
run.started
model.started / model.completed / model.failed
tool.started / tool.completed / tool.failed
verification.completed
permission.denied
run.stop_requested
run.completed / run.failed / run.stopped
```

未知事件显示为简短 generic row 或忽略并记录 debug log，不能导致 TUI crash。

---

## 6. 实施阶段

### Phase A：TUI Skeleton 与 Runtime Adapter

- [ ] 增加 optional Textual dependency 与独立 TUI entry；
- [ ] 建立 App、ChatLog、PromptInput、RunStatus、ToolTimeline；
- [ ] 用 Worker thread 包装同步 QueryEngine；
- [ ] 建立 UI message 与 `run_id + sequence` reducer；
- [ ] 保持现有 CLI 行为不变。

### Phase B：最小交互闭环

- [ ] 支持任务提交与单 active run；
- [ ] 渲染关键 model / tool / verification / terminal events；
- [ ] 实现 `/help`、`/new`、`/cancel`、`/quit`；
- [ ] 展示 RunResult、stop_reason 和调用计数；
- [ ] 实现 Textual 缺失与无 TTY fallback。

### Phase C：验证与留档

- [ ] 完成 Textual headless/widget tests；
- [ ] 完成 Windows Terminal 和窄终端 smoke；
- [ ] 完成正常任务、cancel、失败和 fallback 演示；
- [ ] 确认 TUI 不直接依赖 Tool / SQLite；
- [ ] 输出最小 artifacts 并完成 Review。

三个 Phase 之外的新 Widget 或 Runtime 能力全部进入候选池。

---

## 7. 测试与 Gate

| 编号 | 场景 | 通过标准 |
|---|---|---|
| M06-01 | TUI launch | full-screen App 可启动，基础组件存在 |
| M06-02 | submit | 只调用一次 QueryEngine，UI 主循环不阻塞 |
| M06-03 | event order | stale / duplicate sequence 不回滚界面状态 |
| M06-04 | terminal result | completed / failed / stopped 正确显示 |
| M06-05 | duplicate submit | active run 存在时拒绝第二次提交 |
| M06-06 | cooperative cancel | `/cancel` 发送 stop request 并解释边界 |
| M06-07 | unknown event | 不 crash，不伪造已知状态 |
| M06-08 | no Textual | 给出安装提示或回退 CLI，核心命令仍可用 |
| M06-09 | no TTY | 自动回退或明确拒绝，不进入损坏界面 |
| M06-10 | architecture boundary | TUI 不导入具体 Tool、Repository 或数据库表 |
| M06-11 | terminal smoke | Windows Terminal 与窄宽度不 crash |
| M06-12 | CLI regression | 原 `paperclaw agent` 路径保持通过 |

### GO

- M06-01–M06-12 全部通过；
- 一条真实任务可以从输入走到结构化终态；
- UI 不阻塞 QueryEngine 执行；
- CLI fallback 可用；
- 未引入 Permission、ShellTask、MultiAgent 或 Trace 新 Runtime；
- 文档不宣称 token streaming、强制取消或 Session reconnect。

### NO-GO

- TUI 直接执行 Tool 或写数据库；
- UI 线程因同步 QueryEngine 冻结；
- event sequence 倒退导致终态被覆盖；
- Textual 不可用时核心 CLI 也无法运行；
- `/cancel` 被描述为已经终止模型或进程树；
- 为完成 UI 顺手重构 v0.05 QueryEngine。

---

## 8. 演示与交付

### 最小演示

```text
启动 TUI
→ 提交创建文件任务
→ 观察 run / tool / verify 事件
→ 查看 completed RunResult
→ 新建任务并请求 cooperative cancel
→ 退出 TUI
→ 用普通 CLI 再运行一次 smoke
```

### 交付物

```text
artifacts/v0_06/
├── mvp_test_report.md
├── mvp_demo_trace.json
├── tui_boundary.md
├── known_limitations.md
└── implementation_summary.md
```

不生成尚未实现的 Permission UX、Shell stream、MultiAgent 或完整 terminal matrix 报告。

---

## 9. 后续增强边界

后续候选统一进入：

[`PaperClaw_v0.06.1_Claw交互增强候选池.md`](PaperClaw_v0.06.1_Claw交互增强候选池.md)

候选池没有默认实施顺序。一次只能提取一个用户故事重新写成小型 SOP。

---

## 10. 风险预案

| 风险 | 预案 |
|---|---|
| 同步 submit 冻结界面 | Worker thread + UI message，不重写 Runtime async |
| UI 事件乱序 | run_id + sequence reducer |
| 退出时 active run 未知 | 明确提示 cooperative stop 边界，不假装已杀进程 |
| Textual 成为硬依赖 | optional extra + CLI fallback |
| Widget 数继续膨胀 | MVP 固定四个可视组件 |
| 把高频日志当聊天 | Timeline 只显示关键生命周期事件 |
| Windows inline 不可用 | full-screen App；不把 inline 作为验收路径 |
| hidden Chain-of-Thought 泄漏 | 只显示 structured event、reason summary 和 tool metadata |

---

## 11. 既有实现参考

| 参考项目 | 必读路径 | 借鉴目标 | 禁止照搬 |
|---|---|---|---|
| PaperClaw | `src/paperclaw/harness/query_engine.py` | 同步 submit、event_handler、cooperative stop | 让 Widget 绕过 QueryEngine |
| PaperClaw | `src/paperclaw/cli.py` | CLI fallback 与事件展示词汇 | 把 CLI print 逻辑直接塞进 Widget |
| PaperClaw | `src/paperclaw/agent/events.py` | 现有 Agent 事件类型 | 新建冲突的第二套语义 |
| AutoResearchClaw | `researchclaw/hitl/adapters/cli_adapter.py` | progress / action 的轻量交互 | 复制科研 stage 常量 |
| AutoResearchClaw | `researchclaw/server/websocket/events.py` | event-to-UI 边界 | 在 MVP 引入 WebSocket server |
| AutoResearchClaw | `frontend-legacy/src/components/ChatPanel.js` | Chat 与状态分离思路 | 复制 legacy React UI |
| PaperAgent | 当前 Workbench / Trace 组件 | 事件分组与 stale state 经验 | 复制旧 DOM、全量面板或 LangGraph 状态 |

执行前记录参考仓库 commit / worktree。Implementation Summary 必须说明复用的既有 QueryEngine / CLI 契约，以及主动延期的 UI 能力。
