# PaperClaw v0.07：Durable Trace Foundation MVP SOP

> 版本：v0.07
> 状态：**MVP OFFLINE GO / MISTRAL LIVE BLOCKED / Draft PR #5**
> 基线：`main@725e8a81425efa987f59a6f66ce0021fe7978261`
> 分支：`feat/v0.07-trace-foundation-mvp`
> 原则：先冻结极小 Trace 合同，再让 Inspector、Replay、Eval 与外部 exporter 作为独立消费者演进。

## 1. 用户故事

一次持久化 PaperClaw Run 结束后，用户可以通过 `run_id` 从现有 SQLite 数据库导出一份：

- 顺序可信；
- schema version 明确；
- JSON-safe；
- 默认脱敏；
- 可重新读取并校验；
- 不执行任何模型、工具或恢复动作；

的 JSONL Trace。

## 2. 架构结论

v0.07 不创建第二套 Trace 数据库。现有 `session_events` 继续作为唯一 durable fact source：

```text
QueryEngine / AgentRuntimeExecutor
              ↓
       SessionService/EventSink
              ↓
      SQLite session_events
              ↓
 TraceEventV1 read-side projection
              ↓
   JSONL / future read-only plugins
```

Runtime 不依赖 Replay、Eval、TUI Inspector、OpenTelemetry、Langfuse 或任何通用 PluginManager。

## 3. MVP 范围

### 3.1 必须交付

- [x] `TraceEvent` v1 冻结合同；
- [x] 单 Run sequence 严格递增校验；
- [x] 单 canonical terminal event 校验；
- [x] `SessionEvent → TraceEvent` 只读投影；
- [x] 旧 `flow.stopped` 投影为 `run.completed/run.failed/run.stopped`；
- [x] 原始 `source_event_type` 保留在 projected payload；
- [x] `RepositoryTraceReader`；
- [x] `SQLiteTraceReader` 使用 `mode=ro` 与 `PRAGMA query_only=ON`；
- [x] 原子、确定性 JSONL export；
- [x] JSONL load + integrity validation；
- [x] 统一 payload JSON-safety 与敏感字段脱敏；
- [x] provider key 在事件持久化前脱敏；
- [x] model event 记录 provider、model、duration_ms；
- [x] durable `run.started`；
- [x] `paperclaw trace export` CLI；
- [x] 单元、SQLite round-trip、CLI、Runtime wiring 与 secret-boundary 测试；
- [x] Windows 全量离线 pytest 通过；
- [x] Ruff high-signal gate 通过；
- [x] Mistral live smoke 完成或形成可复现的外部阻塞证据；
- [x] artifacts 与 Handoff 收口。

### 3.2 明确非目标

- Replay 执行器；
- live re-execution；
- Eval scorer；
- TUI/Web Trace Inspector；
- OpenTelemetry、Langfuse、Phoenix exporter；
- 通用插件安装、发现、权限和版本协商；
- Provider 429 retry、Retry-After、指数退避；
- thinking-only / empty-content 兼容策略；
- token/cost 估算；
- Prompt、完整文件、完整工具输出或隐藏 reasoning 的 durable 保存；
- 数据库 schema 迁移。

## 4. TraceEvent v1

稳定字段：

```text
schema_version
event_id
sequence
occurred_at
conversation_id
run_id
event_type
component
status
span_id / parent_span_id
duration_ms
provider / model
error_code
payload
```

规则：

1. `sequence` 是唯一权威顺序，不按 wall-clock 重排；
2. 一个 Trace 不得混合 Run 或 Conversation；
3. canonical terminal 最多一个，之后不得再有事件；
4. `require_terminal=True` 时必须存在 terminal；
5. schema 不兼容时 fail closed；
6. payload 必须可由标准 JSON 编码器安全编码。

## 5. Canonical terminal projection

SQLite 中保留现有 `flow.stopped`，读取时投影：

| stop_reason | Trace event | status |
|---|---|---|
| `done`, `completed_verified` | `run.completed` | `completed` |
| `runtime_failed`, `executor_failed`, `*_failed` | `run.failed` | `failed` |
| budget / blocked / cancel / timeout / other stop | `run.stopped` | 对应 structured status |

此映射只发生在 read side，不重写历史数据库事件。

## 6. 脱敏合同

必须在写入 event storage 前处理，并在 export 时再次执行防御性处理：

- API key；
- Authorization / cookies；
- password / secret / access token；
- Bearer token；
- 本地用户 home path；
- bytes 仅保留 length + SHA256；
- 超长字符串仅保留 bounded preview + length + SHA256；
- 非有限浮点、Path、日期、dataclass 与集合转为 JSON-safe 表示。

不允许 Trace 保存：

- Prompt 全文；
- 模型隐藏 reasoning；
- 完整环境变量；
- 完整文件内容；
- 未截断的 Shell 输出。

## 7. CLI

```powershell
paperclaw trace export `
  --database paperclaw.db `
  --run-id <run-id> `
  --output trace.jsonl
```

默认要求 Run 已有 terminal event。仅诊断未完成 Run 时显式使用：

```powershell
--allow-partial
```

CLI 必须：

- 不迁移数据库；
- 不创建数据库；
- 不修改 Run；
- 不执行 Provider 或 Tool；
- 输出结构化 summary 或结构化 error；
- 输出文件父目录不存在时失败，而不是隐式创建。

## 8. 验收矩阵

| Gate | 场景 | 结果 |
|---|---|---|
| T07-01 | contract validation | PASS |
| T07-02 | redaction | PASS |
| T07-03 | SQLite projection | PASS |
| T07-04 | canonical terminal | PASS |
| T07-05 | JSONL round-trip | PASS |
| T07-06 | read-only CLI | PASS |
| T07-07 | Runtime wiring | PASS |
| T07-08 | provider metadata | PASS（离线显式 metadata fixture） |
| T07-09 | secret boundary | PASS |
| T07-10 | full regression | PASS：405 passed / Ruff PASS |
| T07-11 | Mistral smoke | BLOCKED：DNS name resolution，未到 HTTP 层 |

## 9. 后续插件路线

### v0.07.1 Provider Reliability

- 429 / Retry-After；
- 指数退避与最大重试预算；
- retriable error taxonomy；
- thinking-only / empty-content normalization；
- request ID、usage、finish_reason 归一化。

### v0.07.2 Trace Inspector

先 CLI，只读展示 timeline、错误链、模型/工具调用和耗时；TUI panel 后置。

### v0.07.3 Recorded Replay

只重放记录结果与控制流，不调用 Provider、不执行 Tool、不产生副作用。

### v0.07.4 Eval

从 terminal success、verification、reflection rounds、tool failures、retry count、duration 等结构化 scorer 开始。

### 更后续

- live re-execution；
- OpenTelemetry / Langfuse / Phoenix exporter；
- 有至少两个真实第三方插件后再评估正式 Plugin SDK。

## 10. 停止条件

本轮完成 T07-01–T07-10 后，尝试 T07-11。若执行环境无法解析 Provider 域名或无法访问外部网络：

1. 保留离线 CI 结果；
2. 记录具体异常类型与阶段；
3. 不声明 live PASS；
4. 不把 secret 写入日志或仓库；
5. 将状态标记为 `MVP offline GO / live acceptance BLOCKED`，等待可联网环境复验。

## 11. 最终验收事实

GitHub Actions run `29446553046` / run number `110`：

- Windows Server 2025；
- 405 passed；
- 0 failed；
- 0 skipped；
- Ruff high-signal gate PASS。

Mistral 真实预检使用供应的本地 key/base URL 发起 `/models` 请求，结果为：

```text
urllib.error.URLError
socket.gaierror
[Errno -3] Temporary failure in name resolution
```

因此最终状态是：**核心 MVP 离线验收通过；真实 Provider 验收被当前执行环境 DNS 阻塞；key 有效性未验证。**
