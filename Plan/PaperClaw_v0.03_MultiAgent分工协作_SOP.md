# PaperClaw v0.03：进程内 MultiAgent 协作 MVP SOP

> 版本：v0.03.1  
> 状态：**已完成 / GO（MultiAgent MVP）**  
> 类型：第三个工程实施 SOP  
> 前置：v0.02 Verify / Reflection Gate 通过验收  
> 目标：交付一个可测试、可审计、受预算和文件作用域约束的进程内 Coordinator / Worker / Reviewer 协作基线。

## 1. 版本定位

v0.03 不交付开放式 Swarm，也不承诺生产级沙箱、完整消息总线或 crash resume。它只建立后续版本可以复用的 MultiAgent Runtime 基线：

```text
User Goal
   ↓
Coordinator
   ├── validate Task DAG
   ├── choose sequential / parallel path
   ├── schedule bounded Workers
   ├── aggregate Result / Evidence / Trace
   └── invoke read-only Reviewer

Worker
   ├── execute one AgentTask
   ├── obey tool/path scope
   ├── obey task/team budget
   ├── use FileLease + CAS for file tools
   └── return WorkerResult

Reviewer
   ├── read Result / Artifact / local Evidence
   ├── emit structured findings
   └── request bounded Fix Tasks
```

## 2. 本版本实际交付范围

### 2.1 In Scope

- Coordinator / Worker / Reviewer 三角色；
- `AgentTask`、`WorkerResult`、`ReviewFinding` 等结构化契约；
- Task DAG 校验、依赖传播与死锁防护；
- 顺序执行与最多 3 Worker 并行执行；
- Worker 工具白名单、读取路径和写入路径作用域；
- 文件工具 `FileLease`、同目录原子替换与强制 `expected_hash` CAS；
- `file_read -> content_hash -> file_write/file_edit` 的 Agent 可用链路；
- 局部 Verify / Reflection Gate；
- 规则化只读 Reviewer 与最多两轮 Fix-Review；
- Task timeout、团队 step/model-call/wall-time 预算基线；
- 进程内取消、Shell 子进程 best-effort 终止与 `unknown_outcome`；
- EventEnvelope v1 和 MultiAgent Trace；
- Windows pytest CI 与 ruff CI。

### 2.2 Deferred

以下能力不再作为 v0.03 完成条件：

| 能力 | 目标版本 |
|---|---|
| Role Context、Session、SQLite、Checkpoint、Resume | v0.04 |
| 完整 AgentMessage mailbox / recipient 路由 | v0.04 |
| Global Verify | v0.04 |
| Reviewer 语义审查与 acceptance-claim 覆盖 | v0.04 |
| failed Worker 的完整 retry / repair 状态机 | v0.04 |
| 严格预算控制器与完整 Trace 字段 | v0.04–v0.07 |
| 完整 Permission Engine / HITL | v0.05 |
| OS / container 级 Shell Sandbox | v0.05 |
| 强 TOCTOU 防护和强制进程树终止 | v0.05 |
| Retrieval / RAG / Evidence Engine | v0.08 |

## 3. 核心契约

### 3.1 AgentTask

```python
@dataclass
class AgentTask:
    task_id: str
    title: str
    objective: str
    acceptance_criteria: list[str]
    dependencies: list[str]
    allowed_paths: list[str]
    writable_paths: list[str]
    allowed_tools: list[str]
    input_artifact_ids: list[str]
    expected_artifacts: list[str]
    max_steps: int
    timeout_seconds: int
    priority: int
```

### 3.2 WorkerResult

```python
@dataclass
class WorkerResult:
    task_id: str
    status: str  # completed | failed | blocked | cancelled
    summary: str
    changed_files: list[str]
    artifact_ids: list[str]
    verification_result: VerificationResult | None
    unresolved_items: list[str]
    handoff_notes: list[str]
    step_count: int
    model_call_count: int
    tool_call_count: int
```

### 3.3 TeamBudget

```python
@dataclass
class TeamBudget:
    max_agents: int = 3
    max_total_steps: int = 100
    max_total_model_calls: int = 200
    max_wall_time_seconds: int = 600
    max_fix_rounds: int = 2
```

## 4. 调度规则

- DAG 必须无环，依赖必须存在；
- 每个 Task 必须有可检查的 acceptance criteria；
- 两个以上独立且可隔离的任务才进入并行路径；
- 强依赖链按拓扑序执行全部任务；
- 上游失败时下游必须 blocked 或 cancelled；
- 顺序和并行路径均计入同一个 TeamBudget；
- Worker 不得自行生成子 Agent；
- Coordinator 不得在 Worker 运行时修改其 lease 文件。

## 5. 文件与 Bash 边界

### 5.1 文件工具强保证

`file_write` / `file_edit`：

- 写前必须通过 PermissionGuardLite；
- 必须取得 FileLease；
- 已有文件必须提供读取时的 `expected_hash`；
- 新文件使用空字符串 sentinel；
- hash 不一致返回 `cas_conflict`，不得覆盖；
- 写入使用同目录临时文件和 `os.replace`。

### 5.2 Bash 的准确声明

当前 Bash 策略是**防误操作基线，不是安全沙箱**：

- 静态分类 read-only / write / dangerous / unknown；
- 常见写命令提取目标并检查 writable scope 与 lease；
- 动态执行构造默认拒绝；
- unknown 命令在受限 scope 下拒绝；
- 间接脚本写入、复杂 PowerShell 语义和 OS 级隔离留到 v0.05。

因此 v0.03 只应用于受信任的本地仓库、计划和模型配置。

## 6. Verify 与 Reviewer

- 每个 Worker 使用 v0.02 Local Verify / Reflection；
- 默认 Verify Gate 下只读任务不得被无意义 Bash 验证阻塞；
- Reviewer 只读；
- Reviewer 检查 Worker 状态、局部 VerificationResult 和 expected artifacts；
- blocker/high finding 可转为 Fix Task；
- Fix-Review 最多两轮；
- Reviewer 的复杂语义判断和项目级 Global Verify 延后到 v0.04。

## 7. Timeout、取消与恢复边界

- Task timeout 在 Agent step 间检查；
- Bash tool 有独立命令 timeout；
- cancel 设置协作式事件，并 best-effort 终止注册的 Shell 子进程树；
- lease 在线程退出后释放，不提前释放；
- 无法确定副作用是否完成时返回 `unknown_outcome`；
- v0.03 不支持进程崩溃后的 durable recovery；
- checkpoint、pending tool reconciliation 和幂等 resume 属于 v0.04。

## 8. 验收矩阵

| 编号 | 场景 | v0.03 通过标准 |
|---|---|---|
| M-01 | 两个独立只读任务 | 默认 Verify Gate 下并行完成 |
| M-02 | 两个独立文件修改 | 各自拥有 lease 并完成局部验证 |
| M-03 | 两个任务写同一文件 | DAG 或 lease 阶段阻止冲突 |
| M-04 | Task DAG 有环 | validator 拒绝 |
| M-05 | 文件工具越权路径 | `scope_violation` |
| M-06 | Task timeout | 最终不能 completed，保留 timeout 语义 |
| M-07 | 父任务取消 | 待执行子任务取消，活跃任务 best-effort 有界停止 |
| M-09 | Reviewer high/blocker | 创建受限 Fix Task |
| M-10 | 多轮 Reviewer 不通过 | 达到上限后 blocked / reflection_limit |
| M-11 | 简单任务 | 保持单 Agent 路径 |
| M-13 | 危险或不可分析 Bash | 按当前策略拒绝或标记受限 |
| M-14 | 外部编辑或无 hash 覆盖 | `cas_conflict` / `cas_missing`，不覆盖 |
| M-15 | Tool 超时且结果未知 | `unknown_outcome`，不自动重试 |

以下原验收项正式迁移：

- M-08 局部通过、全局失败阻断 → v0.04 Global Verify；
- 完整 AgentMessage 路由 → v0.04；
- 强 Shell 隔离和强 TOCTOU → v0.05。

## 9. 交付物

```text
artifacts/v0_03/
├── implementation_summary.md
├── multiagent_contract.md
├── task_dag_examples.json
├── collaboration_trace.json
├── conflict_test_report.md
├── reviewer_findings.json
├── test_report.md
└── file_manifest.txt
```

## 10. 完成定义

- [x] Coordinator 能判断顺序或并行；
- [x] Task DAG 有确定性 validator；
- [x] 顺序路径执行完整拓扑链；
- [x] Worker 有独立工具、路径和任务预算；
- [x] 文件工具具备 lease、atomic replace 和强制 CAS；
- [x] Agent 能通过 file_read 获得 CAS hash；
- [x] 顺序与并行路径计入团队预算；
- [x] 默认 Verify Gate 下核心只读/写入场景可运行；
- [x] Reviewer 独立且只读；
- [x] Fix-Review 轮数有上限；
- [x] 取消不提前释放 lease；
- [x] Trace、测试报告和 CI 配置齐全；
- [x] 未完成能力已明确迁移到后续版本；
- [x] 文档不再声称 v0.03 提供 Global Verify、完整消息通道、crash resume 或完整 Shell Sandbox。

## 11. 最终结论

v0.03 作为**进程内 MultiAgent 协作 MVP**通过验收，可以结束并进入 v0.04。后续版本不得把本文件 Deferred 项误写成 v0.03 已实现能力。
