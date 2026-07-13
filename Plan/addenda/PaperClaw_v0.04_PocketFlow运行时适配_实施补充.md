# PaperClaw v0.04：PocketFlow 运行时适配实施补充

> 类型：v0.04 实施补充 Addendum  
> 状态：**立即生效 / IMPLEMENTATION REQUIRED**  
> 适用版本：v0.04 Context / Session / SQLite MVP  
> 前置状态：v0.04 主 SOP 已冻结并已开始实施  
> 目标：在不修改 PocketFlow vendored core、不扩大 v0.04 产品范围的前提下，为现有 Flow 增加稳定节点身份、可观测 step boundary、Checkpoint 对接和安全 resume 入口。

> 本文件是独立补充，不修改、不重开 `PaperClaw_v0.04_ContextSessionSQLite_SOP草案.md`。实现者应将本补充作为 v0.04 Runtime 集成层的约束执行。

---

## 1. 结论

PocketFlow 上游核心当前不需要升级，也不应修改：

- PaperClaw 继续使用仓库内 vendored `pocketflow`；
- 不引入外部 `pocketflow` PyPI 依赖；
- 不把 Session、Checkpoint、Trace、Context、Cancellation 或 MultiAgent 逻辑写入 `src/pocketflow/__init__.py`；
- 不用 `AsyncFlow` 或 `AsyncParallelBatchFlow` 重构当前 MultiAgent 调度；
- 所有 PaperClaw 特有能力放在 `src/paperclaw/` 下。

本补充只新增 PaperClaw 自己的适配层：

```text
PocketFlow Node / Flow
        ↓ wrapped by
PaperClaw InstrumentedFlowRunner
        ↓ emits
SessionEvent + step boundary metadata
        ↓ commits
Checkpoint / safe resume decision
```

这不是 PocketFlow 升级，而是 PaperClaw Runtime 集成修正。

---

## 2. 与 v0.04 主实施的关系

v0.04 已经开始实施，因此本补充不重排主 SOP 的 Phase A–F，也不要求回滚当前已完成工作。

执行插入点：

```text
当前 v0.04 实施继续
  ├── Phase A/B：Schema / Session Repository 可继续
  ├── 本补充 P0：稳定 node_id + InstrumentedFlowRunner 并行开发
  ├── Phase C/D：ContextBuilder / Compaction 可继续
  └── Phase E Safe Resume 接线前，本补充 P0 必须完成
```

硬依赖：

- SQLite schema 和 Repository 可以先做；
- ContextBuilder 和 Compaction 可以先做；
- 任何 `Checkpoint.next_node_id`、`resume_from_next_node`、step-boundary resume 测试，不得在稳定 node ID 和 InstrumentedFlowRunner 完成前宣告通过。

本补充不新增 v0.04.1 的任意时刻 crash recovery，也不实现 pending side-effect 自动协调。

---

## 3. P0：稳定 Node ID

### 3.1 问题

PocketFlow 原生图连接依赖 Python 对象引用。当前 Agent Flow 中存在动态创建节点和匿名终点：

```python
decide = DecideActionNode(...)
execute_nodes = {
    name: ExecuteToolNode(registry)
    for name in registry.names
}

decide - "done" >> Node()
reflect - "done" >> Node()
```

对象引用适合进程内运行，但不能作为持久化恢复标识：

- Python 对象地址不稳定；
- 匿名 `Node()` 无语义名称；
- 数据库无法可靠记录下一节点；
- Offline Replay 无法比较不同进程中的节点；
- Checkpoint 无法判断已经完成的是哪个节点。

### 3.2 稳定命名空间

v0.04 Agent Flow 至少使用以下稳定 ID：

```text
decide
tool:file_read
tool:file_write
tool:file_edit
tool:grep
tool:bash
verify_done
reflect
completed
```

规则：

- node ID 在同一 Flow definition 内唯一；
- node ID 是协议字段，不得使用 `id(node)`、对象 repr 或随机 UUID；
-工具节点使用 `tool:<tool_name>`；
-终点必须有显式 ID；
-节点重命名属于 schema / replay compatibility 变更；
- Checkpoint 只保存稳定 node ID，不序列化 Node 对象。

### 3.3 节点接口

优先采用 PaperClaw 侧协议，而不是修改 PocketFlow Node 基类：

```python
from typing import Protocol

class IdentifiedNode(Protocol):
    node_id: str
```

允许的实现方式：

```python
class DecideActionNode(Node):
    node_id = "decide"
```

或构建时注册：

```python
registry.register("decide", decide)
registry.register("tool:file_read", execute_nodes["file_read"])
```

无论使用类属性还是 registry，最终 Runner 必须能确定性完成：

```python
node_id -> Node
Node -> node_id
```

### 3.4 显式 CompletedNode

匿名终点替换为 PaperClaw 自己的终点：

```python
class CompletedNode(Node):
    node_id = "completed"

    def post(self, shared, prep_res, exec_res):
        shared["stop_reason"] = shared.get("stop_reason") or "done"
        return None
```

要求：

- `completed` 是稳定终点；
-进入终点前最后一个业务节点必须已经提交；
-终点不得产生文件、Shell 或外部 API 副作用；
- `flow.stopped` 必须引用 `completed` 或明确的失败节点。

---

## 4. P0：InstrumentedFlowRunner

### 4.1 文件位置

推荐新增：

```text
src/paperclaw/runtime/flow_runner.py
```

配套文件建议：

```text
src/paperclaw/runtime/
├── __init__.py
├── flow_runner.py
├── flow_contracts.py
├── node_registry.py
└── runtime_services.py
```

如果当前项目结构更适合放在 Agent 下，可使用：

```text
src/paperclaw/agent/instrumented_flow.py
```

但不得放入：

```text
src/pocketflow/__init__.py
```

### 4.2 Runner 职责

`InstrumentedFlowRunner` 负责：

1. 接收 Flow、shared state 和 RuntimeServices；
2. 解析稳定起始 node ID；
3. 在节点执行前持久化边界事件；
4. 执行节点原有 `prep -> exec -> post`；
5. 根据 action 选择 successor；
6. 解析 `next_node_id`；
7. 在节点完成后提交状态和 Checkpoint；
8. 在失败时记录 node failure；
9. 在安全条件满足时支持从 `next_node_id` 恢复；
10. 在关闭持久化时保持与原 PocketFlow Flow 行为一致。

### 4.3 最小接口

```python
@dataclass(frozen=True)
class FlowResumePoint:
    run_id: str
    completed_node_id: str | None
    last_action: str | None
    next_node_id: str
    last_committed_sequence: int
    state_revision: int


@dataclass
class RuntimeServices:
    event_sink: "SessionEventSink | None" = None
    checkpoint_writer: "CheckpointWriter | None" = None
    node_registry: "NodeRegistry | None" = None
    cancellation_token: "CancellationToken | None" = None


class InstrumentedFlowRunner:
    def run(
        self,
        flow,
        shared: dict[str, Any],
        *,
        services: RuntimeServices,
        resume_point: FlowResumePoint | None = None,
    ) -> Any:
        ...
```

`RuntimeServices` 用于替代向 `Flow.params` 塞入大量松散对象。

### 4.4 必须发出的事件

```text
flow.started
node.started
node.completed
node.failed
transition.selected
checkpoint.committed
flow.stopped
```

建议事件字段：

```python
{
    "schema_version": 1,
    "event_id": "...",
    "run_id": "...",
    "sequence": 12,
    "event_type": "node.completed",
    "node_id": "decide",
    "action": "file_read",
    "next_node_id": "tool:file_read",
    "step_count": 4,
    "state_revision": 7,
    "stop_reason": None,
}
```

要求：

- sequence 来自 v0.04 Session Repository；
-事件顺序不能仅依赖 timestamp；
- `node.started` 不等于节点已完成；
- `transition.selected` 必须记录 action 和 next node；
- `checkpoint.committed` 只能在节点结果和状态已提交后产生；
-异常不能被 Runner 吞掉；
-失败事件必须包含 error type 和稳定 error code。

### 4.5 原始 PocketFlow 语义保持

Runner 不得改变：

- `prep -> exec -> post` 顺序；
- `post` 返回 action 决定条件边；
- `None` 使用 default transition；
- Node retry 和 fallback 行为；
- shared state 是业务状态权威来源；
-原生 Flow 对节点进行浅复制的行为。

关闭事件和 Checkpoint 后，新 Runner 必须与原 Flow 产生相同业务结果。

---

## 5. P0：Checkpoint 与恢复语义

### 5.1 恢复对象

恢复的对象是 **下一节点**，不是重放上一节点。

Checkpoint 至少增加或确认以下字段：

```text
completed_node_id
last_action
next_node_id
last_committed_sequence
state_revision
pending_operations
file_snapshots
```

### 5.2 提交顺序

安全 step boundary：

```text
node.started 持久化
    ↓
节点执行 prep / exec / post
    ↓
节点业务结果持久化
    ↓
transition.selected 持久化
    ↓
Checkpoint(completed_node_id, next_node_id) 持久化
    ↓
checkpoint.committed
```

Checkpoint 不能在节点执行前预先宣称该节点完成。

### 5.3 恢复规则

```text
节点尚未开始
    → 可以执行该节点

节点已经完成并提交 Checkpoint
    → 从 next_node_id 继续

存在 node.started 但无 node.completed
    → recovery_required

存在 mutating operation.started 但无终局事件
    → recovery_required

next_node_id 不存在于当前 NodeRegistry
    → recovery_required / incompatible_flow_definition
```

禁止：

-恢复后重新执行 `completed_node_id`；
-仅根据 shared 中的 step count 猜测节点；
-序列化并恢复 Python Node 对象；
-对未知 Bash 或文件写入自动重放；
-遇到不兼容 Flow definition 时静默回到起点。

### 5.4 Flow Definition 兼容性

Checkpoint 建议记录：

```text
flow_definition_id
flow_definition_version
node_registry_hash
```

若当前运行时节点图与 Checkpoint 不一致：

-默认停止自动恢复；
-输出旧/新 registry hash；
-标记 `incompatible_flow_definition`；
-不得自动映射到“最接近”的节点名。

完整跨版本迁移留到后续版本。

---

## 6. P1：PocketFlow 契约测试

新增：

```text
tests/test_pocketflow_contract.py
```

最小测试矩阵：

| 测试 | 验证内容 |
|---|---|
| `test_prep_exec_post_order` | 严格执行 `prep -> exec -> post` |
| `test_post_action_selects_successor` | `post` 返回值决定条件边 |
| `test_none_action_uses_default` | `None` 使用 default transition |
| `test_unknown_action_stops_flow` | 未注册 action 不误走其他节点 |
| `test_retry_then_success` | `Node.max_retries` 生效 |
| `test_retry_fallback` | 最后失败进入 fallback |
| `test_flow_copies_nodes` | Flow 浅复制节点行为稳定 |
| `test_shared_state_is_authoritative` | 状态通过 shared 更新 |
| `test_instrumented_flow_parity` | 关闭持久化后与原 Flow 行为一致 |
| `test_resume_from_next_node` | 已提交节点不被重复执行 |
| `test_started_without_completed_requires_recovery` | 半完成节点不自动重放 |
| `test_unknown_next_node_requires_recovery` | registry 不兼容时停止 |

`test_instrumented_flow_parity` 和 `test_resume_from_next_node` 是 v0.04 硬门槛。

---

## 7. P1：Vendored Core 完整性

### 7.1 测试文件

新增：

```text
tests/test_pocketflow_vendor_integrity.py
```

固定已审核版本：

```python
EXPECTED_UPSTREAM_COMMIT = "43ef382bb0c9dae8167528618bb40f5a3f9a28a5"
EXPECTED_CORE_BLOB_SHA = "0b71858bfb9c0d8d02c5eb0b692d8b788af342e3"
```

### 7.2 检查内容

- `UPSTREAM.md` 固定 commit 与预期一致；
- vendored `src/pocketflow/__init__.py` blob/content hash 与预期一致；
- PaperClaw Session、Checkpoint、Trace 等字段没有进入 vendored core；
-安装后 `import pocketflow` 加载路径位于当前项目；
-环境中存在同名外部包时，不得优先加载外部版本；
-完整性检查离线运行，不在 CI 中临时访问上游网络。

### 7.3 变更流程

未来确需升级 PocketFlow 时：

1. 单独提交 vendored core 升级；
2. 更新 `UPSTREAM.md`；
3. 更新 expected commit 和 blob SHA；
4. 运行全部 contract tests；
5. 生成行为差异报告；
6. 不得与 PaperClaw Runtime 功能修改混在一个提交中。

---

## 8. P1：类型契约修正

当前本地 `__init__.pyi` 的 `Params` 类型比运行时更窄。

建议改为：

```python
from typing import Any

SharedData = dict[str, Any]
Params = dict[str, Any]
```

更推荐 PaperClaw Runtime 使用：

```python
@dataclass
class RuntimeServices:
    session_repository: SessionRepository | None = None
    context_builder: ContextBuilder | None = None
    event_handler: Callable[..., None] | None = None
    cancellation_token: CancellationToken | None = None
    checkpoint_writer: CheckpointWriter | None = None
```

规则：

-业务服务优先放 `RuntimeServices`；
- `params` 只保留 PocketFlow 兼容入口；
-不得依靠错误的 stub 限制运行时值；
- `.pyi` 是 PaperClaw 自己维护的资产，不视为上游文件；
-增加最小 mypy、pyright 或 stubtest 检查；
-类型检查失败不得通过删除类型标注规避。

---

## 9. 实施阶段

### Addendum Phase P0-A：Node Identity

- [x] PA1. 建立 NodeRegistry；
- [x] PA2. 为 Agent Flow 所有节点分配稳定 node ID；
- [x] PA3. 新增 `CompletedNode`；
- [x] PA4. 移除 Agent Flow 中匿名终点；
- [x] PA5. 生成 node registry hash。

### Addendum Phase P0-B：Instrumented Runner

- [ ] PB1. 新增 `InstrumentedFlowRunner`；
- [ ] PB2. 保持 PocketFlow prep/exec/post 和 transition 语义；
- [ ] PB3. 发出 flow/node/transition 事件；
- [ ] PB4. 对接 v0.04 SessionEvent sequence；
- [ ] PB5. 支持关闭持久化的 parity 模式；
- [ ] PB6. 失败时保留异常和稳定 error code。

### Addendum Phase P0-C：Checkpoint Wiring

- [ ] PC1. Checkpoint 记录 completed/next node；
- [ ] PC2. 节点完成后再提交 Checkpoint；
- [ ] PC3. resume 从 next node 开始；
- [ ] PC4. 半完成节点进入 recovery_required；
- [ ] PC5. pending mutating operation 阻止恢复；
- [ ] PC6. registry hash 不一致阻止恢复。

### Addendum Phase P1-D：Contracts and Integrity

- [ ] PD1. PocketFlow contract tests；
- [ ] PD2. instrumented parity test；
- [ ] PD3. resume no-replay test；
- [ ] PD4. vendored core integrity test；
- [ ] PD5. import source test；
- [ ] PD6. `.pyi` Params 修正；
- [ ] PD7. 类型检查进入 CI。

---

## 10. 验收矩阵

| 编号 | 场景 | 通过标准 |
|---|---|---|
| PF-01 | Stable node ID | 所有可运行节点和终点都有唯一稳定 ID |
| PF-02 | CompletedNode | 不再使用匿名终点 |
| PF-03 | Event order | `node.started` 先于执行，`node.completed` 后于结果 |
| PF-04 | Transition trace | action 与 next_node_id 可重建 |
| PF-05 | PocketFlow parity | 关闭持久化时业务结果与原 Flow 一致 |
| PF-06 | Resume next node | 已完成节点不被重复执行 |
| PF-07 | Partial node | started 无 completed 时返回 recovery_required |
| PF-08 | Pending write | 未终局写操作阻止自动恢复 |
| PF-09 | Registry mismatch | 节点图不兼容时停止恢复 |
| PF-10 | Retry parity | retry/fallback 语义不变 |
| PF-11 | Shared authority | shared 仍是业务状态权威来源 |
| PF-12 | Vendor integrity | vendored core hash 与固定值一致 |
| PF-13 | Import provenance | import 加载项目 vendored package |
| PF-14 | Params typing | RuntimeServices 可通过类型检查 |
| PF-15 | Core untouched | 本补充实施不修改 `src/pocketflow/__init__.py` |

硬门槛：

```text
已提交副作用节点重复执行 = 0
匿名可恢复节点 = 0
无 node_id 的 Checkpoint = 0
PocketFlow core 非计划修改 = 0
instrumented parity 回归 = 0
未知 next node 自动回起点 = 0
```

---

## 11. 交付物

```text
artifacts/v0_04/pocketflow_adapter/
├── implementation_summary.md
├── node_registry.json
├── flow_event_trace.json
├── parity_test_report.md
├── resume_no_replay_report.md
├── vendor_integrity_report.md
└── file_manifest.txt
```

`implementation_summary.md` 必须说明：

- PocketFlow core 是否保持原样；
- stable node ID 列表；
- Runner 与原 Flow 的行为差异；
- Checkpoint 提交边界；
-不能自动恢复的情况；
- vendor commit 和 blob SHA；
-类型契约修改；
-未完成项和后续版本归属。

---

## 12. 非目标

本补充明确不做：

-更新或重写 PocketFlow core；
-引入外部 PocketFlow dependency；
-使用 AsyncFlow 重构 MultiAgent；
-任意时刻 crash recovery；
-未知 Bash 自动重放；
-pending side-effect reconciliation engine；
-Global Verify；
-AgentMessage mailbox；
-Semantic Reviewer；
-完整 Permission Engine；
-OS/container Shell Sandbox。

上述能力仍按 v0.04.1、v0.05 等既定版本推进。

---

## 13. 完成定义

本补充完成必须同时满足：

- [ ] PocketFlow vendored core 未修改；
- [ ] 所有 Agent Flow 节点拥有稳定 node ID；
- [ ] 匿名终点替换为 `CompletedNode`；
- [ ] InstrumentedFlowRunner 保持原 Flow 行为；
- [ ] flow/node/transition/checkpoint 事件可持久化；
- [ ] Checkpoint 保存 completed node 和 next node；
- [ ] safe resume 从 next node 开始；
- [ ] 半完成节点和 pending write 不自动重放；
- [ ] PocketFlow contract tests 全部通过；
- [ ] vendored integrity 和 import provenance 通过；
- [ ] `.pyi` Params 类型与运行时一致；
- [ ] CI 包含 parity、no-replay 和 vendor integrity 防线；
- [ ] artifacts/v0_04/pocketflow_adapter 完整生成。

完成后，本补充状态可以改为 `DONE`；v0.04 主 SOP 的完成状态仍由其自身全部验收门槛决定。
