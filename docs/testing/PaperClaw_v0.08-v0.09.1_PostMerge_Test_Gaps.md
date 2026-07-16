# PaperClaw v0.08–v0.09.1 合并后补充测试计划

> 文档状态：`POST-MERGE TEST GAP REVIEW / INITIAL`  
> 目标基线：`main@872c4532fe00b3a3e8b72202fdd4c504594d8acc`  
> 生成日期：2026-07-17  
> 范围：v0.08 Context Orchestration、v0.09 MCP Protocol Foundation Phase A、v0.09.1 RAG Index Foundation Phase A

## 1. 合并事实

`main` 按依赖顺序只新增以下三个 merge commit：

1. `a1b263862b23d0fa7e8caccce44a7e3033a5efc6` — v0.08 Context Orchestration；
2. `09f820e6134240841545ad6d86b88b0ee832f948` — v0.09 MCP Protocol Foundation；
3. `872c4532fe00b3a3e8b72202fdd4c504594d8acc` — v0.09.1 RAG Index Foundation。

本测试文档位于独立测试分支，不进入上述三个 `main` merge commit，也不改变主分支提交数量。

## 2. 当前已经验证的内容

### 2.1 v0.08 独立分支证据

- Windows/Python 3.12 repository suite：`524 passed`；
- Ruff `E9,F63,F7,F82`：PASS；
- 已覆盖 Context contract、去重、冲突、预算、Prompt trust 分区、Runtime executor、SQLite assembly event、demo 与 closeout；
- Provider 和外部 Retrieval 使用 deterministic fake，不属于 live external validation。

### 2.2 v0.09 独立分支证据

- Windows/Python 3.12 repository suite：`521 passed`；
- Ruff `E9,F63,F7,F82`：PASS；
- 已覆盖 stdio lifecycle、initialize/discover/call/close、分页 discovery、schema normalization、timeout、disconnect、invalid JSON、wrong response ID、protocol mismatch 与 invalid result；
- Server 为本地 deterministic fake，未验证第三方 MCP interoperability。

### 2.3 v0.09.1 独立分支证据

- Windows/Python 3.12 repository suite：`526 passed`；
- Ruff `E9,F63,F7,F82`：PASS；
- 已覆盖 document/version/chunk identity、Markdown/plain-text parsing、chunk boundaries/overlap、SQLite/FTS5 add-update-delete、manifest consistency 与 transaction rollback；
- 尚无 BM25 read-side retrieval API，也未接 ContextOrchestrator。

### 2.4 合并后组合回归

- 验证载体：本文件所在 Draft PR 的 merge-ref CI；
- 测试对象：最终 `main@872c453` 加一份无运行时影响的 Markdown 文档；
- 初始状态：`PENDING`；
- 完成后必须补录 workflow run、pytest 精确数量、exit status、Ruff 状态和 artifact digest。

## 3. 判定规则

本文将测试缺口分成两类：

### A. 已实现能力的补测

代码路径已经存在，只是当前覆盖不足。这类测试可立即增加，测试失败通常表示现有实现缺陷或跨分支集成回归。

### B. 后续 Phase 的验收测试

依赖的 adapter、read API、Permission、Trace 或 capability selection 尚未实现。这类测试先冻结接口、fixture 与 acceptance criteria，不应现在写成必然失败的 production test，也不能把“未实现”误报为回归。

## 4. P0：合并后必须补充的自动化测试

| ID | 类型 | 测试目标 | 前置条件 | 核心断言 |
|---|---|---|---|---|
| INT-001 | A | 三模块 import/package smoke | 当前 main | `paperclaw.context`、`paperclaw.mcp`、`paperclaw.retrieval` 可在全新解释器中同时导入；公共导出不覆盖同名符号 |
| INT-002 | A | 全仓库最终 main 回归 | 当前 main | Windows pytest 0 failed、0 errors、0 unexpected skipped；Ruff PASS |
| INT-003 | A | legacy runtime parity | v0.08 opt-in executor | 引入 MCP/RAG 包后，`AgentRuntimeExecutor` 仍不产生 Context/MCP/RAG 事件，输出和调用计数保持旧语义 |
| INT-004 | A | SQLite 文件隔离 | Session SQLite + RAG SQLite | 两个 Repository 指向不同数据库时 schema、transaction、close 顺序互不影响；读取一方不会改变另一方 SHA-256 |
| INT-005 | A | 同目录并存 | 两个数据库位于同一临时目录 | WAL/journal/temporary file 不发生命名碰撞；并行只读操作稳定 |
| INT-006 | A | deterministic repeatability | Windows + Linux | 同一 Context fixture、MCP schema、RAG source 在独立进程重复运行，fingerprint/hash/ID 完全一致 |
| INT-007 | A | secret sweep | 组合 Run + MCP config + RAG metadata | API key、MCP environment value、原始 Prompt、RAG 文档正文不进入结构化错误、Context assembly event 或普通日志 |
| INT-008 | A | completion hook regression | 三套 SOP/artifacts 同时存在 | hook 只选择正确当前 SOP，不因 v0.09 与 v0.09.1 目录命名产生误判或遗漏 |

### P0 Gate

`INT-001` 至 `INT-008` 全部通过后，才能把状态写为 `POST-MERGE OFFLINE GO`。其中 `INT-002` 由本 Draft PR CI 立即执行；其余应在独立测试 PR 中补齐。

## 5. v0.08 Context Orchestration 补测

### 5.1 可立即补充

| ID | 优先级 | 场景 | 预期 |
|---|---|---|---|
| CTX-001 | P0 | property-based candidate permutation | 输入顺序变化不改变 selection、conflict resolution、fingerprint 和 Prompt section 顺序 |
| CTX-002 | P0 | property-based budget boundary | 任意候选组合都满足 rendered Prompt 不超过 available budget；protected overflow 必须 fail-closed |
| CTX-003 | P0 | Unicode/CJK token underestimation | char/4 估算偏差不得造成内部预算负数、无限循环或静默删除 protected item |
| CTX-004 | P1 | duplicate content across trust levels | external candidate 不得通过内容相同覆盖 trusted/system candidate；Trace 保留确定性排除原因 |
| CTX-005 | P1 | conflict tie-break stability | priority、trust、freshness 完全相同时，稳定 tie-break 不依赖 Python hash seed |
| CTX-006 | P1 | large candidate set | 10k candidates 下有界完成，Trace 大小受控，不保留正文 |
| CTX-007 | P1 | persistence failure | `context.assembly.completed` 持久化失败应按既有 Runtime 错误边界处理，不把未持久化 assembly 伪装成成功 |
| CTX-008 | P2 | actual tokenizer comparison | 使用至少一个 production tokenizer 对 char/4 偏差做统计并冻结安全 margin |

### 5.2 需要真实环境

| ID | 优先级 | 场景 | 预期 |
|---|---|---|---|
| CTX-LIVE-001 | P1 | OpenAI-compatible/Mistral live call | Provider 实际收到 trust-separated Prompt；最终回答可完成；Trace 不保存 Prompt 正文 |
| CTX-LIVE-002 | P2 | physical TUI/CLI opt-in route | 用户可明确选择 Context executor，legacy route 仍可用；当前没有默认 CLI flag 时记录为产品缺口而非测试失败 |

### 5.3 后续 Phase 才能执行

- full MultiAgent Context policy；
- long-term Memory source；
- Context Inspector UI；
- RAG/MCP capability selection。

## 6. v0.09 MCP Protocol Foundation 补测

### 6.1 可立即补充

| ID | 优先级 | 场景 | 预期 |
|---|---|---|---|
| MCP-001 | P0 | oversized single-line response | 超过 `max_message_bytes` 时有界拒绝，进程内存不随无换行 payload 无界增长 |
| MCP-002 | P0 | stderr flood while stdout idle | stderr 不阻塞协议 stdout reader；timeout 后进程可关闭且无泄露线程 |
| MCP-003 | P0 | cancellation/response race | timeout cancellation 与迟到 response 同时发生时 session 保持 FAILED，迟到消息不能被下一请求消费 |
| MCP-004 | P0 | close during blocked request | close 有界返回，子进程被回收，不残留 zombie/Windows child process |
| MCP-005 | P1 | duplicate tool names across pages | discovery 原子失败，原有已发现集合不被部分覆盖 |
| MCP-006 | P1 | repeated/looping pagination cursor | 在安全页数上限前 fail-closed，错误 taxonomy 稳定 |
| MCP-007 | P1 | UTF-8 edge cases | emoji、CJK、组合字符和非法 UTF-8 均有确定性结果；非法编码不泄露原始字节 |
| MCP-008 | P1 | JSON number/depth limits | 极深 object、超大整数、非有限数值不能导致 recursion crash 或不受控资源消耗 |
| MCP-009 | P1 | environment secret failure path | command 启动失败、timeout、invalid response 的错误对象均不含 environment value |
| MCP-010 | P2 | Windows physical stdio interoperability | PowerShell/Windows Terminal 下启动、关闭、timeout 和 child cleanup 行为与 CI 一致 |

### 6.2 第三方 interoperability

至少选择两个明确版本的真实 MCP Server：

1. 一个只读、无副作用、本地 stdio Server；
2. 一个工具 schema 包含 optional、enum、array、nested object 的 Server。

验收：

- initialize version negotiation 成功；
- discovery 结果与 Server 声明一致；
- supported schema 正常归一化；
- unsupported schema 明确拒绝；
- timeout/disconnect 不影响 PaperClaw 进程；
- 不执行远程写操作。

### 6.3 后续 Phase B/C 才能执行

| ID | 场景 | 等待能力 |
|---|---|---|
| MCP-B-001 | Descriptor → Tool adapter | ToolRegistry adapter |
| MCP-B-002 | 参数二次校验 | schema argument validator |
| MCP-B-003 | Permission bypass rate = 0 | Permission/approval integration |
| MCP-B-004 | Run budget/stop propagation | Agent Runtime integration |
| MCP-B-005 | redact → truncate → Trace | Trace integration |
| MCP-C-001 | Top-K capability selection | capability index + v0.08 Context source |
| MCP-C-002 | local Tool unaffected by Server outage | unified execution path |

## 7. v0.09.1 RAG Index Foundation 补测

### 7.1 Parser/chunking

| ID | 优先级 | 场景 | 预期 |
|---|---|---|---|
| RAG-001 | P0 | Windows path/canonical URI | drive letter、大小写、空格、非 ASCII 文件名生成稳定 document identity |
| RAG-002 | P0 | cross-process determinism | 不同 `PYTHONHASHSEED`、Windows/Linux 下 chunk IDs、source hash、corpus hash 一致 |
| RAG-003 | P0 | malformed/unterminated fence | parser 不崩溃，locator 有界且后续 heading 不被错误提升为 trusted metadata |
| RAG-004 | P1 | empty/whitespace/very long line | 结果确定、无空 chunk、单 chunk 不越过 hard bound |
| RAG-005 | P1 | CJK/no-space paragraph | long-block split 可前进，不产生零长度或无限重复 overlap |
| RAG-006 | P1 | heading depth jumps/duplicates | heading path 与 locator 稳定，重复标题不造成 chunk ID 碰撞 |
| RAG-007 | P2 | CommonMark differential fixture | 与选定 CommonMark parser 的差异被记录并固定为已知边界 |

### 7.2 SQLite/FTS5 integrity

| ID | 优先级 | 场景 | 预期 |
|---|---|---|---|
| RAG-008 | P0 | process interruption during transaction | add/update/delete 要么全部提交，要么全部回滚；active counts 与 FTS rows 一致 |
| RAG-009 | P0 | database corruption/tamper | manifest/integrity check fail-closed，不返回看似有效的 active corpus |
| RAG-010 | P0 | concurrent read + write | reader 只看到事务前或事务后快照，不看到部分 FTS 更新 |
| RAG-011 | P1 | duplicate add race | 唯一约束与错误分类稳定，不产生两个 active version |
| RAG-012 | P1 | soft-deactivated provenance | update/delete 后旧 version/chunk 可追溯但绝不出现在 active FTS query scope |
| RAG-013 | P1 | FTS5 unavailable | 安装/启动时明确 fail-closed，错误说明平台能力缺失，不静默退化为无索引表 |
| RAG-014 | P1 | rebuild equality | 从 active source 重建后 manifest、counts、corpus hash 与原索引一致 |
| RAG-015 | P2 | scale benchmark | 1k/10k documents 下记录 ingest latency、DB size、peak memory；设置非生产级但可复现阈值 |

### 7.3 后续 Phase B 才能执行

- BM25 query/ranking correctness；
- active/stale/duplicate filtering；
- graded retrieval fixtures（Recall@K、MRR、nDCG）；
- read-side adapter 不修改 registry SHA-256；
- incremental indexing/rebuild workflow；
- citation provenance round trip；
- dense retrieval、RRF、reranker、PDF/OCR。

## 8. 三模块交叉集成测试

这些是当前最重要、但单独 PR CI 无法覆盖的测试。

### 8.1 RAG → Context

| ID | 阶段 | 场景 | 核心断言 |
|---|---|---|---|
| X-RAG-CTX-001 | Phase B | active Chunk 转 `ContextCandidate` | `source_ref` 保留 document/version/chunk/locator/hash；trust 固定为 external/untrusted |
| X-RAG-CTX-002 | Phase B | 文档正文包含系统指令 | 指令只进入 `UNTRUSTED DATA`，不能改变 L0/L1、Permission 或 protected policy |
| X-RAG-CTX-003 | Phase B | stale/deactivated chunk | 不进入候选集合；Trace 给出可解释 exclusion reason |
| X-RAG-CTX-004 | Phase B | retrieval quota overflow | protected Context 不被挤出；RAG candidate 按配额确定性截断 |
| X-RAG-CTX-005 | Phase B | citation provenance | selected candidate 到 answer citation 可回溯 source/version/chunk/locator/hash |

### 8.2 MCP → Context/Tool

| ID | 阶段 | 场景 | 核心断言 |
|---|---|---|---|
| X-MCP-CTX-001 | Phase C | Tool descriptor 作为 capability candidate | 只注入 Top-K descriptor，Server instructions 永不成为 system instruction |
| X-MCP-TOOL-001 | Phase B | MCP Tool 经统一执行链 | 必须经过 Registry → validation → Permission → execute → Trace |
| X-MCP-TOOL-002 | Phase B | Server timeout/disconnect | 当前 Run 有界失败；本地 Tool registry 和后续本地调用保持可用 |
| X-MCP-TOOL-003 | Phase B | malicious output | 先 redact 再 truncate；Prompt/Trace 不泄露 secret 或未经隔离的 instruction |
| X-MCP-TOOL-004 | Phase B | remote write request | 没有显式授权与幂等策略时 fail-closed，不自动重试 |

### 8.3 RAG + MCP + Context 同时启用

| ID | 阶段 | 场景 | 核心断言 |
|---|---|---|---|
| X-ALL-001 | Phase C | 一个任务同时需要本地文档和 MCP Tool | Context budget、Tool budget、stop token 与 Trace sequence 均有界且可解释 |
| X-ALL-002 | Phase C | RAG 文档与 MCP instruction 冲突 | 两者均为 external data，不能覆盖 system/project/user confirmed constraints |
| X-ALL-003 | Phase C | MCP outage + healthy RAG | RAG/legacy local Tool 路径继续工作；Server failure 不污染 capability cache |
| X-ALL-004 | Phase C | corrupt RAG index + healthy MCP | index fail-closed；MCP/local Tool 可继续；Run terminal reason 精确分类 |
| X-ALL-005 | Phase C | repeated identical run | normalized Prompt fingerprint、selected source IDs、Tool descriptor hash 在固定 fixture 下可重复 |

## 9. 推荐实施顺序

### Test PR A：当前实现的组合硬化

包含：

- `INT-001`–`INT-008`；
- `CTX-001`–`CTX-007`；
- `MCP-001`–`MCP-009`；
- `RAG-001`–`RAG-014`。

这批测试不要求新增产品能力，可以立即实施。

### Test PR B：真实环境验收

包含：

- `CTX-LIVE-001`；
- `MCP-010`；
- 两个真实第三方 MCP Server interoperability；
- RAG scale benchmark。

真实测试必须与默认 CI 分离，显式标记环境、版本、凭据与成本。

### Feature PR 后附验收

- v0.09 Phase B 完成时附带 `MCP-B-*` 与 `X-MCP-TOOL-*`；
- v0.09 Phase C 完成时附带 `MCP-C-*`、`X-MCP-CTX-*` 与 `X-ALL-*`；
- v0.09.1 Phase B 完成时附带 `RAG read-side` 与 `X-RAG-CTX-*`。

## 10. 不应添加的伪测试

以下不能作为完成证据：

- 只断言 class/file/import 存在，不验证行为；
- Mock 掉 transaction 后声称 SQLite crash-safe；
- Fake MCP Server 测试声称第三方 interoperability；
- 用固定期望答案验证 RAG，而不验证 source/chunk provenance；
- 只检查 Prompt 中出现 Tool/RAG 文本，不检查 trust section、预算与 Permission；
- 把尚未实现的 Phase B/C feature 标记为当前 regression failure；
- 只看 workflow conclusion，不解析 pytest report artifact 的精确结果。

## 11. 最终验收模板

完成组合测试后，记录：

```text
Baseline main SHA:
Validation branch SHA:
GitHub Actions run:
Windows/Python version:
pytest passed / failed / errors / skipped:
pytest exit status:
Ruff result:
Artifact ID/name/digest:
P0 tests passed:
Live tests executed/not executed:
Known blockers:
Decision: POST-MERGE OFFLINE GO / NO-GO
```

## 12. 当前结论

三个功能分支已按顺序进入 `main`，各自独立 CI 均为绿色。但在最终 merge-ref CI 与 `INT-001`–`INT-008` 完成前，只能声明：

`MERGED / INDIVIDUALLY OFFLINE-VALIDATED / COMBINED VALIDATION IN PROGRESS`
