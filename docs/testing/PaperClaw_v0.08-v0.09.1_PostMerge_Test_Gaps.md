# PaperClaw v0.08–v0.09.1 合并后补充测试文档

> 状态：`COMBINED BASELINE PASS / SUPPLEMENTAL HARDENING PENDING`  
> 目标基线：`main@872c4532fe00b3a3e8b72202fdd4c504594d8acc`  
> 验证分支：`test/v0.08-v0.09.1-postmerge-validation`  
> 验证 PR：`#22`  
> 日期：2026-07-17

## 1. 合并结果

`main` 从原基线开始按依赖顺序只增加三个 merge commit：

1. `a1b263862b23d0fa7e8caccce44a7e3033a5efc6` — v0.08 Context Orchestration；
2. `09f820e6134240841545ad6d86b88b0ee832f948` — v0.09 MCP Protocol Foundation；
3. `872c4532fe00b3a3e8b72202fdd4c504594d8acc` — v0.09.1 RAG Index Foundation。

本文档保留在独立 Draft PR，不进入 `main`，因此不会产生第 4 个主分支 commit。

## 2. 最终组合回归结果

验证对象是 PR #22 的 merge-ref：最终 `main@872c453` 加一份无运行时影响的 Markdown 文档。

```text
Validation branch head: e40db1a8ec2a2758df21ed53e02213a64809d87b
GitHub Actions run:     29516023356
Windows pytest:         561 passed
Failed:                 0
Errors:                 0
Skipped:                0
pytest exit status:     0
Ruff E9/F63/F7/F82:     PASS
Artifact ID:            8382785463
Artifact name:          pytest-results-29516023356
Artifact digest:        sha256:935e9fc58e16e6c28c9a8a6768a9483abf2ef7ae80d615ee4892e4e3085eaf8c
```

精确数量来自 `pytest_reportlog.jsonl` 中 `when == "call"` 的 `TestReport`，不是把 setup/call/teardown 三阶段重复计数，也不是只读取 workflow conclusion。

### 当前可以声明

- 三个功能分支已进入 `main`；
- 合并后的 Windows/Python 3.12 全量 suite 无回归；
- Ruff 高信号规则通过；
- Context、MCP、RAG 三个包可在同一代码树中共存；
- 当前状态为 `COMBINED BASELINE PASS`。

### 当前不能声明

- 真实第三方 MCP interoperability；
- MCP 已接 ToolRegistry、Permission、Trace 或 Context；
- RAG 已具备 BM25 查询、Citation 或 ContextSource；
- 三模块已形成用户可见端到端闭环；
- live Provider、真实网络检索或远程写操作已验证。

## 3. 已有覆盖摘要

### v0.08 Context Orchestration

已覆盖：

- contract、去重、冲突与预算分配；
- protected Context fail-closed；
- external instruction trust 隔离；
- Prompt fingerprint 与 content-free assembly Trace；
- opt-in Runtime executor、legacy parity、SQLite event persistence；
- deterministic demo、artifact 与 closeout。

主要未覆盖：真实 Provider、实际 tokenizer、属性测试、大规模候选、完整 MultiAgent policy、RAG/MCP source adapter。

### v0.09 MCP Protocol Foundation

已覆盖：

- stdio connect/initialize/discover/call/close；
- pagination 与 discovery 原子提交；
- schema normalization 与 hash；
- timeout、disconnect、invalid JSON、wrong ID、protocol mismatch、invalid result；
- environment secret 不进入 config fingerprint；
- deterministic fake Server subprocess。

主要未覆盖：第三方 Server、Windows 物理进程边界、stderr flood、oversized response、close/cancel race、Registry/Permission/Trace/Context 接入。

### v0.09.1 RAG Index Foundation

已覆盖：

- document/artifact/version/chunk/manifest identity；
- Markdown/plain-text parser 与 locator；
- heading-aware chunking、long-block split、overlap；
- SQLite/FTS5 add-update-delete；
- active-version semantics；
- manifest consistency 与 transaction rollback。

主要未覆盖：跨平台 path identity、进程中断、并发读写、损坏恢复、规模测试、BM25 read API、ContextSource 与 Citation。

## 4. P0：当前实现应立即补充的测试

这些测试不要求新增产品能力。失败通常代表现有实现缺陷或合并后回归。

| ID | 模块 | 测试目标 | 核心断言 |
|---|---|---|---|
| INT-001 | Combined | 三包 import/package smoke | 全新解释器同时导入 `paperclaw.context/mcp/retrieval`，公共导出无覆盖 |
| INT-002 | Combined | legacy runtime parity | MCP/RAG 合入后 legacy executor 输出、事件、调用计数不变 |
| INT-003 | Combined | 双 SQLite 隔离 | Session DB 与 RAG DB schema、transaction、close、只读 SHA-256 互不影响 |
| INT-004 | Combined | cross-process determinism | Context fingerprint、MCP schema hash、RAG IDs 在独立进程一致 |
| INT-005 | Combined | secret sweep | key、MCP env value、Prompt、RAG 正文不进入结构化错误和普通日志 |
| INT-006 | Combined | completion hook | v0.08、v0.09、v0.09.1 SOP/artifact 同时存在时版本识别正确 |
| CTX-001 | Context | candidate permutation property | 输入顺序变化不改变 selection、conflict、fingerprint、section 顺序 |
| CTX-002 | Context | arbitrary budget boundary | rendered Prompt 永不超过 available budget；protected overflow fail-closed |
| CTX-003 | Context | Python hash seed | tie-break 与 fingerprint 不依赖 `PYTHONHASHSEED` |
| CTX-004 | Context | 10k candidates | 有界完成，Trace 大小受控且不保存正文 |
| MCP-001 | MCP | oversized no-newline response | `max_message_bytes` 前后有界拒绝，无无界内存分配 |
| MCP-002 | MCP | stderr flood | stderr 不阻塞 stdout；timeout/close 后无泄露线程或进程 |
| MCP-003 | MCP | timeout/late-response race | session 保持 FAILED，迟到 response 不被后续请求消费 |
| MCP-004 | MCP | close while blocked | close 有界，child process 被回收 |
| MCP-005 | MCP | pagination loop/duplicate tool | fail-closed，未提交部分 discovery 结果 |
| MCP-006 | MCP | deep/large JSON | 深度和大小攻击不导致 recursion crash 或资源失控 |
| RAG-001 | RAG | Windows canonical URI | drive、大小写、空格、CJK 文件名 identity 稳定 |
| RAG-002 | RAG | cross-platform rebuild | Windows/Linux 与不同 hash seed 下 chunk/corpus hash 一致 |
| RAG-003 | RAG | malformed fence/heading | parser 不崩溃，locator 有界，heading trust 不误提升 |
| RAG-004 | RAG | CJK no-space long block | split 持续前进，无空 chunk、无限循环或重复 overlap |
| RAG-005 | RAG | interrupted transaction | add/update/delete 全提交或全回滚，FTS 与 active counts 一致 |
| RAG-006 | RAG | concurrent read/write | reader 只看事务前或事务后快照，不见部分 FTS 更新 |
| RAG-007 | RAG | corruption/tamper | integrity/manifest fail-closed，不返回伪有效 corpus |
| RAG-008 | RAG | rebuild equality | active source 重建后 counts、manifest、corpus hash 一致 |

### P0 Gate

- 当前完成：最终组合全量回归、Ruff、artifact 精确计数；
- 待补：上表 24 个显式 hardening case；
- 在这些用例完成前，状态保持 `COMBINED BASELINE PASS`，不提升为“完整集成验收完成”。

## 5. P1：真实环境与规模测试

| ID | 模块 | 场景 | 验收标准 |
|---|---|---|---|
| CTX-LIVE-001 | Context | OpenAI-compatible/Mistral live call | Provider 实际消费 trust-separated Prompt；Trace 不保存 Prompt 正文 |
| MCP-LIVE-001 | MCP | Windows 物理 stdio | initialize/call/timeout/close/child cleanup 与 CI 语义一致 |
| MCP-LIVE-002 | MCP | 第三方只读 Server A | discovery 与调用成功；Server 失败不破坏 PaperClaw 进程 |
| MCP-LIVE-003 | MCP | 第三方复杂 schema Server B | supported schema 正常化，unsupported schema 明确拒绝 |
| RAG-PERF-001 | RAG | 1k/10k 文档 ingest | 记录 latency、DB size、peak memory，并冻结可复现阈值 |
| RAG-PORT-001 | RAG | FTS5 unavailable | 启动时明确 fail-closed，不静默生成残缺 registry |

真实测试必须独立于默认 CI，固定 Server/Provider/version、凭据来源、网络条件、成本和机器信息。

## 6. 后续 Phase 才能执行的测试

以下依赖尚未实现，当前不应写成必然失败的 production test。

### 6.1 RAG → Context

| ID | 前置能力 | 核心断言 |
|---|---|---|
| X-RAG-CTX-001 | BM25 read adapter + ContextSource | candidate 保留 document/version/chunk/locator/hash，trust 固定 external/untrusted |
| X-RAG-CTX-002 | ContextSource | 文档内 instruction 只进 `UNTRUSTED DATA`，不能覆盖 L0/L1 |
| X-RAG-CTX-003 | active/stale filter | deactivated chunk 不进入候选，Trace 有 exclusion reason |
| X-RAG-CTX-004 | retrieval quota | RAG overflow 不挤出 protected Context |
| X-RAG-CTX-005 | Citation pipeline | answer 可回溯 source/version/chunk/locator/hash |

### 6.2 MCP → Tool/Context

| ID | 前置能力 | 核心断言 |
|---|---|---|
| X-MCP-TOOL-001 | Tool adapter | MCP Tool 必经 Registry → validation → Permission → execute → Trace |
| X-MCP-TOOL-002 | Runtime integration | timeout/disconnect 有界失败，本地 Tool 仍可用 |
| X-MCP-TOOL-003 | redaction/Trace | output 先 redact 再 truncate，secret 与 instruction 不泄露 |
| X-MCP-CTX-001 | capability selection | 只注入 Top-K descriptor，Server instructions 永不成为 system instruction |
| X-MCP-WRITE-001 | approval + idempotency | remote write 无显式授权时 fail-closed，不自动重试 |

### 6.3 三者同时启用

| ID | 场景 | 核心断言 |
|---|---|---|
| X-ALL-001 | 文档 + MCP Tool 同一任务 | Context/Tool budget、stop token、Trace sequence 均有界 |
| X-ALL-002 | RAG 与 MCP instruction 冲突 | 两者均为 external data，不能覆盖 confirmed constraints |
| X-ALL-003 | MCP outage + healthy RAG | RAG 和 local Tool 继续工作，故障不污染 capability state |
| X-ALL-004 | corrupt RAG + healthy MCP | index fail-closed；MCP/local Tool 可继续；terminal reason 精确 |
| X-ALL-005 | deterministic repeated run | fixture 下 Prompt fingerprint、source IDs、descriptor hash 可重复 |

## 7. 推荐实施顺序

### Test PR A：离线组合硬化

优先实现：

- `INT-001`–`INT-006`；
- `CTX-001`–`CTX-004`；
- `MCP-001`–`MCP-006`；
- `RAG-001`–`RAG-008`。

这批测试不扩大产品范围，可以直接从当前 `main` 开发。

### Test PR B：真实环境验收

实现 `CTX-LIVE-*`、`MCP-LIVE-*`、`RAG-PERF-*`、`RAG-PORT-*`，使用独立 workflow/manual SOP。

### Feature PR 随附验收

- v0.09 Phase B：`X-MCP-TOOL-*`；
- v0.09 Phase C：`X-MCP-CTX-*` 与 `X-ALL-*`；
- v0.09.1 Phase B：`X-RAG-CTX-*` 与 graded retrieval metrics。

## 8. 禁止作为完成证据的伪测试

- 只断言文件/class/import 存在；
- Mock 掉 transaction 后声称 SQLite crash-safe；
- Fake MCP Server 测试声称第三方 interoperability；
- 固定答案 RAG 测试不验证 source/chunk provenance；
- 只检查 Prompt 出现文本，不检查 trust section、预算和 Permission；
- 把尚未实现的 Phase B/C 功能记为当前 regression；
- 只看 workflow 绿色，不解析 pytest report artifact；
- 把 setup/call/teardown 的 1683 个 TestReport 误报为 1683 项测试。

## 9. 最终结论

```text
Merge:                 PASS — exactly 3 main merge commits
Combined Windows CI:   PASS — 561 passed, 0 failed/errors/skipped
Ruff:                  PASS
Current decision:      COMBINED BASELINE PASS
Immediate hardening:   PENDING — 24 explicit P0 cases
Live interoperability: NOT EXECUTED
Phase B/C E2E:         NOT IMPLEMENTED / NOT CLAIMED
```

三个基础模块可以共同存在于 `main`，没有发现组合级编译、导入或现有回归测试失败。下一步不应继续堆功能，而应先执行 Test PR A 中的离线组合硬化用例。
