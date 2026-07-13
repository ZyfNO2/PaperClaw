# PaperClaw v0.04.1：Runtime Protocol Closure 与 Recovery Reconciliation SOP 草案

> 版本：v0.04.1-draft  
> 状态：**草案 / NOT READY FOR IMPLEMENTATION**  
> 前置：v0.04 Context / Session / SQLite MVP 完成并通过全部硬门槛  
> 目标：在 v0.04 的持久化 Session、Event、Checkpoint 与安全 step-boundary resume 基线上，补齐 MultiAgent 协议闭环、全局验收和未知副作用恢复协调。

> 本版本不建设生产级 Shell Sandbox、完整 HITL Permission Engine、跨机器分布式恢复或多用户隔离。上述能力仍属于 v0.05 及后续版本。

---

## 1. 版本定位

v0.04.1 不是重新实现 Agent Runtime，而是关闭 v0.03 与 v0.04 明确延后的两类工程缺口：

```text
Workstream A — Runtime Protocol Closure
    AgentMessage mailbox / routing / dedup
    Global Verify
    Semantic Reviewer
    failed Worker retry / repair state machine
    complete operation / trace correlation

Workstream B — Recovery Reconciliation
    durable operation ledger
    crash classification
    unknown side-effect reconciliation
    durable task / lease recovery decisions
    safe resume / manual recovery boundary
```

实施顺序必须是：

```text
v0.04 GO
  ↓
v0.04.1-A Protocol Closure GO
  ↓
v0.04.1-B Recovery Reconciliation GO
```

禁止在 A 未完成时开始 B。Recovery 不能建立在非持久、不可关联、没有幂等键的 tool call 之上。

---

## 2. 进入门槛

开始 v0.04.1 前，v0.04 必须已提供并验证：

- SQLite migration v1；
- append-only `SessionEvent`；
- 单调 `sequence`；
- `ContextSnapshot` 与 `Checkpoint` 分离；
- `Checkpoint.last_committed_sequence`；
- `pending_operations` 字段；
- Context role isolation；
- deterministic compaction；
- required constraint retention；
- clean Session reopen；
- safe step-boundary resume；
- pending mutating operation 时进入 `recovery_required`；
- Windows CI 中完整测试通过。

任意一项未满足，v0.04.1 状态保持 `NO-GO`。

---

## 3. In Scope 与 Out of Scope

### 3.1 In Scope

#### Workstream A

- durable `AgentMessage`；
- mailbox、recipient routing、ack 和 dedup；
- message sequence 与 causal reference；
- Coordinator 级 Global Verify；
-结构化 `GlobalVerificationReport`；
- Reviewer acceptance-claim 覆盖；
- Reviewer 对 Diff、Evidence、Trace、Global Verify 的语义审查；
- failed Worker 的 retry / repair 状态机；
- operation、tool call、message、artifact、verification 的关联 ID；
-完整 stop reason 和 provider/model/contract trace 字段；
- protocol-level offline replay fixture。

#### Workstream B

- durable `OperationRecord`；
- operation start / commit / fail / unknown 终局；
- crash 时 pending operation 分类；
- file tool 的确定性 reconciliation；
- Bash 和外部副作用的人工恢复边界；
- durable task state 恢复决策；
- stale FileLease 检测与显式恢复；
-恢复报告和审计日志；
- crash / kill / database fault injection。

### 3.2 Out of Scope

- OS 或 container 级 Shell Sandbox；
-完整 Permission Engine；
- GUI / TUI 人工审批界面；
-自动重放未知 Bash；
-自动重放无幂等保证的外部 API；
-跨机器 Worker 恢复；
-远程队列；
-多用户租户隔离；
-分布式锁；
-跨项目长期 Memory；
-Dense retrieval / RAG；
-自动 PR / push；
-通用工作流编排平台。

---

# Part A：Runtime Protocol Closure

## 4. AgentMessage 契约

```python
@dataclass(frozen=True)
class AgentMessage:
    message_id: str
    conversation_id: str
    run_id: str
    task_id: str | None
    sender_id: str
    recipient_id: str
    message_type: str
    payload: dict
    sequence: int
    causal_message_id: str | None
    idempotency_key: str
    attempt: int
    created_at: str
```

### 4.1 必须支持的消息类型

```text
task.assigned
task.accepted
task.progress
task.completed
task.failed
task.blocked
artifact.published
clarification.requested
clarification.answered
cancel.requested
cancel.acknowledged
review.requested
review.completed
verification.requested
verification.completed
recovery.required
recovery.resolved
```

### 4.2 消息规则

- message 必须先持久化，再投递；
-普通模型文本不等于 AgentMessage；
- `recipient_id` 必须存在或是受支持的系统 recipient；
-同一 `idempotency_key` 在同一 run / recipient 下只产生一次可见效果；
-重复投递允许，重复处理不允许；
- consumer 处理成功后写 `message.acknowledged` 或 ack 记录；
- ack 失败不能删除原 message；
- `causal_message_id` 用于 clarification、cancel、review 等请求/响应关联；
- message payload 必须带 schema version；
-未知 message type 默认拒绝，不静默忽略。

### 4.3 Mailbox 最小模型

```text
agent_messages
message_deliveries
message_acks
message_dedup
```

推荐状态：

```text
persisted → delivered → acknowledged
                   ↘ failed_delivery
```

不得使用“读出即删除”的易失队列。

---

## 5. Operation 与 ToolCall 关联契约

```python
@dataclass(frozen=True)
class OperationRecord:
    operation_id: str
    tool_call_id: str
    conversation_id: str
    run_id: str
    task_id: str
    agent_id: str
    tool_name: str
    operation_class: str   # read_only | deterministic_write | external_side_effect | unknown
    idempotency_key: str
    attempt: int
    arguments_hash: str
    status: str            # planned | started | committed | failed | cancelled | unknown_outcome
    started_sequence: int | None
    terminal_sequence: int | None
    result_hash: str | None
    error_code: str | None
    metadata: dict
```

规则：

-所有 tool call 必须有 `tool_call_id` 和 `operation_id`；
-所有 mutating tool 必须在执行前持久化 `operation.started`；
-成功后持久化 `operation.committed`；
-明确失败后持久化 `operation.failed`；
-进程中断或无法确认结果时标记 `unknown_outcome`；
- `arguments_hash` 用于检测相同 idempotency key 下参数漂移；
-相同 idempotency key 但参数不同必须拒绝；
- operation terminal state 不得回退为非终局状态；
- trace event、message、artifact 和 verification result 必须可通过 `operation_id` 关联。

---

## 6. Global Verify

### 6.1 定位

Local Verify 证明 Worker 的局部声明；Global Verify 证明合并后的项目状态满足用户目标和跨模块约束。

Global Verify 必须发生在：

```text
所有必要 Worker 终局
→ Artifact / Diff 汇总
→ Global Verify
→ Reviewer
→ Completed / Fix Task / Blocked
```

### 6.2 GlobalVerificationReport

```python
@dataclass(frozen=True)
class GlobalVerificationReport:
    report_id: str
    run_id: str
    status: str               # passed | failed | incomplete | blocked
    checks: list[dict]
    acceptance_claims: list[dict]
    covered_claim_ids: list[str]
    uncovered_claim_ids: list[str]
    commands: list[dict]
    artifact_hashes: list[dict]
    evidence_ids: list[str]
    started_sequence: int
    finished_sequence: int
```

### 6.3 最小检查集

-用户目标对应 acceptance claim 覆盖；
-所有 required artifact 存在且 hash 可重验；
-跨模块测试；
-项目级测试；
-配置、文档和实现一致性；
-越权写入和未解决 `unknown_outcome` 检查；
-所有 blocker/high finding 的处理状态；
-未完成 Task 和 cancelled dependency 检查。

### 6.4 完成门槛

以下任一情况禁止 `completed`：

- Global Verify `failed`；
- Global Verify `incomplete` 且存在 required claim；
- required claim 未覆盖；
-存在 unresolved blocker/high；
-存在未协调的 `unknown_outcome`；
- artifact hash 与 Verify 时不一致；
- verification command 未实际执行。

---

## 7. Semantic Reviewer

Reviewer 输入只能包含：

-用户目标；
- acceptance claims；
- Task DAG；
- WorkerResult；
- Diff / File Manifest；
- local verification evidence；
- GlobalVerificationReport；
- operation / message / artifact trace；
-已知限制和 deferred items。

Reviewer 默认不读取 Worker 自由推理。

### 7.1 ReviewFinding

```python
@dataclass(frozen=True)
class ReviewFinding:
    finding_id: str
    run_id: str
    severity: str             # blocker | high | medium | low
    category: str             # correctness | safety | compatibility | evidence | docs | protocol
    title: str
    claim_id: str | None
    evidence_ids: list[str]
    file: str | None
    line: int | None
    requested_change: str
    status: str               # open | fixed | accepted_risk | deferred
```

规则：

- blocker/high 默认阻止完成；
- finding 必须绑定 Evidence、文件位置或明确缺失项；
-不能仅凭“感觉不对”创建 blocker；
- `accepted_risk` 需要 Coordinator 或用户明确决策；
- `deferred` 只能用于不属于当前版本完成定义的能力；
- fix 后必须关联原 finding 并重新 review。

---

## 8. failed Worker Retry / Repair 状态机

```text
pending
  ↓ scheduled
running
  ├── completed
  ├── failed_retryable
  ├── failed_non_retryable
  ├── blocked
  ├── cancelled
  └── unknown_outcome
```

### 8.1 RetryPolicy

```python
@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int
    retryable_error_codes: list[str]
    backoff_seconds: list[int]
    requires_new_context: bool
    requires_reverify: bool
```

### 8.2 规则

- retry 必须创建新 attempt，不覆盖原 attempt；
-同一 operation 未终局时禁止自动 retry；
- `unknown_outcome` 禁止自动 retry；
- CAS conflict 可在重新读取后创建新 attempt；
- scope violation、permission denied、invalid DAG 默认 non-retryable；
- model transient error 可 retry；
- failed Worker 的 Fix Task 继承原依赖，但不依赖失败 task 的“completed”状态；
-修复后必须重新执行 local verify、Global Verify 和 Reviewer；
- retry / repair 总次数计入团队预算。

---

## 9. Trace 完整性

所有事件至少包含：

```text
schema_version
event_id
conversation_id
run_id
agent_id
task_id
sequence
event_type
message_id
operation_id
tool_call_id
artifact_id
provider
model
contract_id
attempt
stop_reason
payload
```

不是每个事件都必须填写全部关联字段，但适用字段不得缺失。

### 9.1 强制关联

- model call → provider / model / contract_id；
- tool call → tool_call_id / operation_id；
- message → message_id；
- artifact publish → artifact_id / content_hash；
- verification → report_id / evidence_ids；
- stop event → stop_reason；
- retry → parent attempt / new attempt；
- recovery → checkpoint_id / affected operation IDs。

---

# Part B：Recovery Reconciliation

## 10. 恢复原则

Recovery 的目标不是“尽量继续跑”，而是：

> 在不重复副作用、不覆盖外部修改、不伪造完成状态的前提下，确定可以自动继续、必须人工确认或必须终止。

恢复决策只有三类：

```text
auto_resume
manual_reconciliation_required
abort_run
```

禁止把不确定状态默认归为成功或失败。

---

## 11. RecoveryDecision

```python
@dataclass(frozen=True)
class RecoveryDecision:
    decision_id: str
    run_id: str
    checkpoint_id: str
    decision: str             # auto_resume | manual_reconciliation_required | abort_run
    affected_task_ids: list[str]
    affected_operation_ids: list[str]
    reasons: list[str]
    required_actions: list[dict]
    file_revalidation: list[dict]
    created_sequence: int
```

规则：

- decision 必须可审计；
-不得仅由模型自由文本决定；
-必须由确定性规则先分类；
-模型只能协助解释或提出人工处置建议；
- `auto_resume` 必须证明没有未知副作用；
- `manual_reconciliation_required` 必须列出具体 operation；
- `abort_run` 不能删除历史数据。

---

## 12. Operation Recovery Matrix

| operation_class | crash 后状态 | 自动动作 |
|---|---|---|
| read_only | started，无 terminal | 可重新执行并生成新 attempt |
| deterministic_write | started，无 terminal | 先检查目标 hash、temp file、result marker，再决定 committed / failed / manual |
| external_side_effect | started，无 terminal | 默认 manual，不自动重放 |
| unknown | started，无 terminal | manual 或 abort |
| committed | 有 terminal | 不重放，读取既有结果 |
| failed | 有 terminal | 按 RetryPolicy 决定新 attempt |
| cancelled | 有 terminal | 不自动继续，除非 Coordinator 创建新 task |
| unknown_outcome | terminal | manual，不自动 retry |

### 12.1 FileRead / Grep

-可重新执行；
-新结果形成新 Evidence；
-旧结果保留；
-若文件 hash 变化，必须标记 Context stale。

### 12.2 FileWrite

自动确认 committed 需要同时满足：

-目标文件存在；
-内容 hash 与 planned/result hash 一致；
- operation idempotency marker 一致；
-没有外部修改冲突；
- lease 所有权记录与 operation 一致。

否则进入 manual reconciliation。

### 12.3 FileEdit

-必须重新读取目标文件；
-若目标 hash 等于 expected post-write hash，可确认 committed；
-若等于 original expected_hash，可确认未执行并允许新 attempt；
-两者都不等于时进入 manual；
-禁止在未知状态下再次应用同一 text replacement。

### 12.4 Bash

-默认 `external_side_effect` 或 `unknown`；
-进程不存在不代表命令未产生副作用；
-无工具特定幂等证明时禁止自动重放；
-只读验证命令可由 allowlist 标为 read_only；
-写入型 Bash 即使目标在 workspace，也默认 manual，除非 v0.05 Permission Engine 提供可验证 operation contract。

### 12.5 外部 API

-只有 provider 提供 idempotency key 且可查询 operation status 时，才允许自动 reconciliation；
-否则默认 manual；
-v0.04.1 不实现通用外部 API reconciler，只定义接口。

---

## 13. Durable Task Recovery

恢复时根据持久化 TaskState 分类：

| 原状态 | 恢复行为 |
|---|---|
| pending | 可重新进入 scheduler |
| ready | 重新验证 dependencies 后调度 |
| running | 检查 operation ledger；不得直接改为 pending |
| completed | 重验 artifact 和 verification hash |
| failed | 保留原 attempt，由 RetryPolicy 决定新 attempt |
| blocked | 重新计算 blocker 是否仍存在 |
| cancelled | 默认保持 cancelled |
| unknown_outcome | manual reconciliation |

### 13.1 running Task

只有在以下条件全部满足时才能自动恢复：

-没有 pending mutating operation；
-所有 started operation 已被确定性归类；
-文件快照重验通过；
-团队预算可恢复；
-依赖状态一致；
-没有有效 cancel request；
-不存在 stale lease 冲突。

否则进入 `recovery_required`。

---

## 14. Durable FileLease Recovery

v0.04.1 不允许仅凭 lease 过期时间自动接管文件。

恢复流程：

1. 读取 lease record；
2. 检查 owner run / task 是否仍活跃；
3. 检查关联 operation 是否 terminal；
4. 重验文件 hash；
5. 检查 temp file / journal marker；
6. 生成 RecoveryDecision；
7. 只有确定原 writer 不再运行且无未知写入时才释放或重建 lease。

状态建议：

```text
active
stale_candidate
revalidated
released
recovery_blocked
```

禁止：

-进程不存在即直接释放；
- lease TTL 到期即覆盖；
-未知 Bash 仍可能写入时转移 lease；
-跳过文件 hash 重验。

---

## 15. Recovery Coordinator

```python
class RecoveryCoordinator:
    def inspect(run_id: str) -> RecoveryDecision: ...
    def reconcile_operation(operation_id: str, action: str) -> None: ...
    def resume(run_id: str, decision_id: str) -> None: ...
    def abort(run_id: str, reason: str) -> None: ...
```

最小 action：

```text
confirm_committed
confirm_not_executed
mark_failed
mark_unknown_outcome
release_stale_lease
keep_blocked
create_new_attempt
abort_run
```

每个 action 必须生成不可变 audit event。

---

## 16. 数据库与事务要求

新增或扩展表：

```text
agent_messages
message_deliveries
message_acks
message_dedup
operations
operation_attempts
operation_reconciliation
verification_reports
review_findings
recovery_decisions
lease_records
```

### 16.1 Migration

-必须从 v0.04 schema 做顺序 migration；
-升级前创建备份；
- migration 在 transaction 中执行；
-不支持 downgrade 时明确拒绝旧二进制打开新库；
- migration failure 不得留下半 schema；
- migration report 记录 before/after schema hash。

### 16.2 写入顺序

对于 mutating operation：

```text
BEGIN DB transaction
  insert operation.started
  append SessionEvent
  update TaskState revision
COMMIT

execute external/file side effect

BEGIN DB transaction
  insert terminal operation event
  update operation status
  update TaskState / Artifact / Evidence
  create Checkpoint when safe
COMMIT
```

数据库事务不能包住长时间外部调用。外部副作用与 DB 之间的不原子窗口必须通过 operation ledger 和 reconciliation 处理。

---

## 17. 安全与信任边界

-外部文本不能影响 RecoveryDecision 规则；
-模型不能自行把 `unknown_outcome` 改成 committed；
-人工 reconciliation action 需要明确 actor 和理由；
- recovery log 不得包含 secret 明文；
- message payload、tool arguments 和 external data 必须按 trust level 渲染；
-恢复后所有 ContextSnapshot 必须重新执行 role isolation；
-旧 Snapshot 不能直接作为新模型调用上下文；
-恢复时必须重新应用当前 Runtime Constitution 和 Permission policy。

---

## 18. 分阶段实施

### Phase A1：消息协议

-定义 AgentMessage；
- mailbox repository；
- recipient routing；
- ack；
- dedup；
- causal message；
-离线 delivery fixture。

### Phase A2：Operation Ledger

- tool_call_id / operation_id；
- operation lifecycle；
- idempotency 参数漂移检查；
- artifact/evidence/trace 关联；
- stop reason 完整化。

### Phase A3：Global Verify

- acceptance claim registry；
- project-level command plan；
- artifact hash verification；
- GlobalVerificationReport；
- completion gate。

### Phase A4：Semantic Reviewer 与 Repair

- Reviewer context；
- semantic finding；
- failed Worker retry/repair；
- finding/fix/re-review 关联；
- bounded attempts 和预算。

### Phase A5：Protocol Gate

-协议测试；
- replay；
- trace completeness；
- CI；
- v0.04.1-A GO/NO-GO。

### Phase B1：Recovery Inspection

- crash classifier；
- pending operation scan；
- file revalidation；
- RecoveryDecision；
- recovery report。

### Phase B2：Tool-specific Reconciliation

- file_read；
- file_write；
- file_edit；
- read-only Bash；
- unknown Bash manual path；
- external API interface placeholder。

### Phase B3：Task 与 Lease Recovery

- durable TaskState；
- running task recovery；
- stale lease inspection；
- explicit lease action；
- dependency revalidation。

### Phase B4：Fault Injection

- kill before tool start；
- kill after operation.started；
- kill after side effect before terminal event；
- kill after terminal event before checkpoint；
- database locked；
- migration failure；
- file externally modified；
- duplicate message delivery。

### Phase B5：Recovery Gate

-自动恢复安全性；
-人工协调路径；
-重复副作用验证；
-audit completeness；
-v0.04.1-B GO/NO-GO。

---

## 19. 测试矩阵

### 19.1 Message / Protocol

| 编号 | 场景 | 通过标准 |
|---|---|---|
| MP-01 | 定向消息 | 只有目标 recipient 可见 |
| MP-02 | 重复 delivery | handler 只产生一次效果 |
| MP-03 | 同 key 参数漂移 | 拒绝并记录 protocol_error |
| MP-04 | clarification request/answer | causal_message_id 正确闭环 |
| MP-05 | cancel request | ack、Task 状态和 trace 一致 |
| MP-06 | 未知 message type | 默认拒绝 |
| MP-07 | crash after persist before delivery | restart 后继续 delivery，不重复处理 |

### 19.2 Global Verify / Reviewer

| 编号 | 场景 | 通过标准 |
|---|---|---|
| GV-01 | local pass / global fail | run 不得完成 |
| GV-02 | required claim 未覆盖 | status=incomplete，阻止完成 |
| GV-03 | artifact 被外部修改 | hash mismatch，阻止完成 |
| GV-04 | verification command 未执行 | 不得生成 passed |
| RV-01 | blocker finding | 创建可运行 Fix Task |
| RV-02 | failed Worker retryable | 新 attempt，不覆盖旧 attempt |
| RV-03 | unknown_outcome | 禁止自动 retry |
| RV-04 | fix 完成 | local/global/reviewer 全部重跑 |
| RV-05 | medium finding | 可进入 known issues，不阻断 |

### 19.3 Operation Ledger

| 编号 | 场景 | 通过标准 |
|---|---|---|
| OP-01 | mutating tool | side effect 前存在 operation.started |
| OP-02 | tool success | committed 与 result hash 可关联 |
| OP-03 | tool failure | failed terminal event 唯一 |
| OP-04 | crash window | operation 进入 pending/unknown，不伪造终局 |
| OP-05 | duplicate idempotency key | 返回既有结果或拒绝参数漂移 |

### 19.4 Recovery

| 编号 | 场景 | 通过标准 |
|---|---|---|
| RC-01 | read-only operation 中断 | 新 attempt 安全重跑 |
| RC-02 | file_write 已落盘未记 terminal | 通过 hash 确认 committed |
| RC-03 | file_write 未执行 | 确认 not_executed 后允许新 attempt |
| RC-04 | file_edit 目标被第三方修改 | manual reconciliation |
| RC-05 | Bash started 无 terminal | 不自动重放 |
| RC-06 | external API 状态不可查 | manual reconciliation |
| RC-07 | running Task 无 pending mutation | 可 auto_resume |
| RC-08 | running Task 有 unknown mutation | recovery_required |
| RC-09 | stale lease + hash 一致 | 按规则显式释放 |
| RC-10 | stale lease + hash 不一致 | recovery_blocked |
| RC-11 | checkpoint 后 DB corruption | 从备份/日志恢复或 abort，不静默继续 |
| RC-12 | duplicate recovery action | 幂等，不产生二次副作用 |

### 19.5 Trace / Audit

| 编号 | 场景 | 通过标准 |
|---|---|---|
| TA-01 | model call | provider/model/contract_id 完整 |
| TA-02 | tool call | tool_call_id/operation_id 完整 |
| TA-03 | stop event | stop_reason 完整 |
| TA-04 | recovery | checkpoint/decision/operation 可关联 |
| TA-05 | fix review | finding/fix/reverify/review 链完整 |

---

## 20. 硬门槛

v0.04.1-A GO 必须满足：

-跨 recipient 消息泄漏：0；
-重复消息产生重复效果：0；
- mutating tool 无 operation.started：0；
- local pass / global fail 却 completed：0；
- required claim 未覆盖却 completed：0；
- blocker/high 未处理却 completed：0；
- `unknown_outcome` 自动 retry：0；
- trace 关键关联字段缺失：0。

v0.04.1-B GO 必须满足：

-未知副作用自动重放：0；
-外部修改被覆盖：0；
- stale lease 无重验直接接管：0；
- crash 后重复 file mutation：0；
- recovery action 无审计事件：0；
- migration 半升级：0；
- recovery decision 仅由模型自由文本决定：0；
-无法证明安全却 auto_resume：0。

---

## 21. GO / 降级 / NO-GO

### 21.1 Workstream A

- `GO`：message、operation、Global Verify、Reviewer 和 repair 状态机全部有可复现测试；
- `降级`：clarification UI 延后，但 durable mailbox 和 routing 必须保留；
- `NO-GO`：消息会串 recipient、Global Verify 可被绕过、unknown operation 会自动 retry、finding 无 Evidence。

### 21.2 Workstream B

- `GO`：所有支持的 operation class 都能确定性分类，未知副作用进入 manual，fault injection 可复现；
- `降级`：只自动协调 file tools，Bash 和外部 API 全部 manual；
- `NO-GO`：Bash/外部 API 被自动重放、文件状态不一致仍继续、lease 自动接管无重验。

### 21.3 总体

v0.04.1 只有 A 和 B 都 GO 才可标记完成。A GO、B 未完成时可发布 `v0.04.1-A` 内部里程碑，但不得宣称 crash recovery 已完成。

---

## 22. 预期交付

```text
artifacts/v0_04_1/
├── protocol_contract.md
├── message_delivery_report.md
├── operation_ledger_schema.md
├── global_verify_report.md
├── reviewer_semantic_eval.json
├── retry_repair_state_machine.md
├── recovery_matrix.md
├── recovery_fault_injection.md
├── durable_lease_report.md
├── trace_completeness.json
├── migration_report.md
└── implementation_summary.md
```

测试 fixture：

```text
tests/fixtures/v0_04_1/
├── duplicate_delivery/
├── local_pass_global_fail/
├── failed_worker_repair/
├── crash_before_side_effect/
├── crash_after_side_effect/
├── unknown_bash/
├── external_file_change/
├── stale_lease/
└── migration_failure/
```

---

## 23. 完成定义

### v0.04.1-A

- [ ] durable AgentMessage mailbox；
- [ ] recipient routing 和 dedup；
- [ ] tool_call_id / operation_id 全链路；
- [ ] Global Verify completion gate；
- [ ] Semantic Reviewer；
- [ ] failed Worker retry/repair；
- [ ]完整 Trace correlation；
- [ ] protocol CI 和 artifacts。

### v0.04.1-B

- [ ] RecoveryDecision；
- [ ] operation recovery matrix；
- [ ] file tool reconciliation；
- [ ] unknown Bash manual path；
- [ ] durable TaskState recovery；
- [ ] stale FileLease recovery；
- [ ] fault injection；
- [ ] recovery audit artifacts。

---

## 24. 实施禁令

-不得把 v0.04.1 草稿视为已完成能力；
-不得在 v0.04 未 GO 时启动实现；
-不得自动重放 `unknown_outcome`；
-不得以进程不存在作为副作用未发生的证明；
-不得以 lease TTL 到期作为安全接管证明；
-不得让模型单独决定 committed / failed / auto_resume；
-不得跳过 Global Verify 直接完成；
-不得在同一 retry attempt 中覆盖原始失败记录；
-不得把完整 Permission Engine 或 OS Sandbox 混入本版本；
-不得声称支持跨机器、跨用户或生产级 durable execution。
