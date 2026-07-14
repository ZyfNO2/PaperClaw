# PaperClaw v0.05.1：Harness Post-MVP 增强候选池

> 状态：Backlog，不是执行 SOP
> 更新：2026-07-14
> 规则：一次只提取一个候选包；不得把本文件全部转成当期验收清单

## 目录

- [1. 使用规则](#1-使用规则)
- [2. H1 Async 与 Streaming](#2-h1-async-与-streaming)
- [3. H2 ShellTask 与强制取消](#3-h2-shelltask-与强制取消)
- [4. H3 Permission 交互与授权缓存](#4-h3-permission-交互与授权缓存)
- [5. H4 ModelGateway 与 Retry](#5-h4-modelgateway-与-retry)
- [6. H5 Event Distribution](#6-h5-event-distribution)
- [7. 与其他版本的边界](#7-与其他版本的边界)
- [8. 风险预案](#8-风险预案)

---

## 1. 使用规则

只有满足以下条件的候选包才能升级为 SOP：

- 有一个 v0.05 MVP 无法满足的真实用户故事；
- 有可复现失败 Trace；
- 能独立演示；
- 不要求同时完成另外两个候选包；
- 最多三个实施 Phase；
- 有清晰降级路径。

优先级由真实阻塞决定，不按 H1–H5 顺序默认执行。

---

## 2. H1 Async 与 Streaming

候选能力：

- async ModelAdapter；
- streaming delta；
- async QueryEngine；
- cooperative cancellation token；
- model timeout。

启动触发器：TUI 确实需要实时 token 或同步模型调用造成可观测卡顿。

不同时实现 background Shell 和多 Provider fallback。

---

## 3. H2 ShellTask 与强制取消

候选能力：

- foreground / background ShellTask；
- stdout / stderr stream；
- timeout；
- Windows process-tree cleanup；
- task notify。

启动触发器：真实测试或构建超过前台等待边界，或 stop 后子进程残留可复现。

首个切片只支持当前平台 PowerShell。不要同时假装统一 POSIX Bash。

---

## 4. H3 Permission 交互与授权缓存

候选能力：

- allow once / deny once；
- allow session / deny session；
- PermissionRequest；
- decision fingerprint；
- TOCTOU recheck；
- TUI approval。

启动触发器：v0.06 TUI 需要真实授权对话，且现有 allow/deny 无法表达用户决策。

OS sandbox 不属于本包。

---

## 5. H4 ModelGateway 与 Retry

候选能力：

- Provider protocol；
- normalized usage；
- capability flags；
- 429 / timeout retry；
- fallback provider；
- structured output normalization。

启动触发器：第二个 Provider 真正接入，或当前 Provider 失败已成为主要不稳定来源。

一次只接一个新 Provider；不能先设计完整 provider matrix。

---

## 6. H5 Event Distribution

候选能力：

- 多消费者 EventBus；
- bounded queue；
- delta coalescing；
- subscriber isolation；
- exporter failure isolation。

启动触发器：TUI、TraceStore 和 exporter 同时消费事件后出现阻塞或内存增长。

如果单一 EventSink 足够，不实现 EventBus。

---

## 7. 与其他版本的边界

| 能力 | 所属版本 |
|---|---|
| 本地 TraceStore / Replay / LangSmith / Eval | v0.07 |
| Retrieval Query / RAG | v0.08 |
| TUI 布局与交互 | v0.06 |
| OS sandbox / packaging / release security | v0.10 |
| arbitrary crash recovery | v0.04 Post-MVP 候选 |

不得因为实现 Harness enhancement 就提前吞并这些版本。

---

## 8. 风险预案

| 风险 | 预案 |
|---|---|
| async 改造扩散全仓 | adapter 边界先行，只改一条调用链 |
| cancel 名义存在但进程仍运行 | 区分 cooperative / model / process cancellation |
| session permission 过宽 | fingerprint 绑定 tool、scope、risk 和参数摘要 |
| retry 重复副作用 | 模型调用 retry 与 Tool retry 分离 |
| EventBus 无真实消费者 | 保留 EventSink，不升级 |

参考入口仍使用 [`PaperClaw_参考项目与可复用模块索引.md`](../../docs/reference/PaperClaw_参考项目与可复用模块索引.md)。候选升级时必须补充具体文件、测试、commit 和禁止照搬项。
