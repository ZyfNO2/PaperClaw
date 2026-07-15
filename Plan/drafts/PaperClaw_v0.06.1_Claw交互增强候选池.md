# PaperClaw v0.06.1：Claw Post-MVP 交互增强候选池

> 状态：Backlog，不是执行 SOP
> 更新：2026-07-15
> 规则：不得整体执行；一次只提取一个具有真实用户故事的候选包

## 目录

- [1. 使用规则](#1-使用规则)
- [2. U1 Permission UX](#2-u1-permission-ux)
- [3. U2 Shell Task UX](#3-u2-shell-task-ux)
- [4. U3 Inspector Panels](#4-u3-inspector-panels)
- [5. U4 MultiAgent View](#5-u4-multiagent-view)
- [6. U5 Session Picker 与 Resume](#6-u5-session-picker-与-resume)
- [7. U6 UX Hardening](#7-u6-ux-hardening)
- [8. 禁止合并与版本边界](#8-禁止合并与版本边界)
- [9. 风险预案](#9-风险预案)

---

## 1. 使用规则

候选包升级为 SOP 前必须满足：

- v0.06 MVP 已有真实使用反馈或失败 Trace；
- 能用一句用户故事说明价值；
- Runtime 前置能力已经存在；
- 最多三个实施 Phase；
- 可独立 GO / NO-GO；
- 不要求同时完成另外两个 UI 子系统。

---

## 2. U1 Permission UX

候选能力：Permission Dialog、allow once / session、deny、参数编辑、pending request 取消。

前置：v0.05.1 PermissionRequest、decision fingerprint 与执行前 TOCTOU recheck 已实现。没有 Runtime Permission contract 时，不允许先做假弹窗。

---

## 3. U2 Shell Task UX

候选能力：stdout / stderr stream、后台任务、取消、完成通知、task list。

前置：v0.05.1 ShellTaskManager、process ownership 和 cancellation semantics 已实现。首个切片只做前台 stream，不同时做 daemon/background。

---

## 4. U3 Inspector Panels

候选能力：Context、Verification、Trace、Cost Inspector。

一次只选择一个面板：

- Context Inspector 依赖稳定 ContextSnapshot；
- Verify Panel 依赖结构化 claim / evidence；
- Trace Panel 依赖 v0.07 TraceStore；
- Cost Panel 依赖 normalized usage。

不能先画空面板再倒逼 Runtime 增加字段。

---

## 5. U4 MultiAgent View

候选能力：Coordinator、active tasks、Worker Result、Reviewer Finding 和 DAG。

启动条件：MultiAgent 已证明相对单 Agent 有真实收益，且 event contract 不依赖隐藏 Chain-of-Thought。默认只展示 active task 和结构化结果。

---

## 6. U5 Session Picker 与 Resume

候选能力：Session list、resume preview、checkpoint 状态、recovery_required、reconnect。

首个切片只做“选择已安全关闭的 Session 并 reopen”。Crash reconciliation、active process reconnect 和 daemon 不属于同一版本。

---

## 7. U6 UX Hardening

候选能力：

- 无颜色与高对比度；
- 中文宽字符与 resize；
- clipboard redaction；
- event batching；
- key binding customization；
- terminal compatibility matrix；
- snapshot recovery after event gap。

根据真实兼容问题逐项提取，不建立一次性全终端认证工程。

---

## 8. 禁止合并与版本边界

禁止在一个小版本中同时实现：

- Permission UX + Shell background；
- MultiAgent View + Session reconnect；
- 四个 Inspector Panel；
- Web UI + TUI redesign；
- Runtime async 重构 + TUI streaming。

Trace / Eval 属于 v0.07；Web / Research UI 另行规划；OS sandbox 与发布安全属于 v0.10。

---

## 9. 风险预案

| 风险 | 预案 |
|---|---|
| UI 倒逼未成熟 Runtime | 先验证 contract，再做 Widget |
| 候选池变默认 Roadmap | 没有真实失败不升级 SOP |
| 面板越来越多 | 一次只增加一个可独立验收面板 |
| TUI 与 CLI 行为分叉 | 所有命令仍走 QueryEngine / Command API |
| UI 展示敏感数据 | structured redaction 后再渲染 |

参考入口：[`PaperClaw_参考项目与可复用模块索引.md`](../../docs/reference/PaperClaw_参考项目与可复用模块索引.md)。候选升级时必须补充具体代码、测试、commit 和禁止照搬项。
