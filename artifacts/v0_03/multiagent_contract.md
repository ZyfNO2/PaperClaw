# PaperClaw v0.03 MultiAgent Contract

## 角色

- **Coordinator**：拥有团队状态，验证 DAG，调度 Worker，合并结果，请求 Reviewer。
- **Worker**：执行单个 AgentTask，受限于工具白名单、路径作用域和步数预算。
- **Reviewer**：只读审查任务结果、产物和 Trace，输出结构化 Finding。

## 核心数据契约

### AgentTask

```python
@dataclass
class AgentTask:
    task_id: str
    title: str
    objective: str
    acceptance_criteria: list[str]
    allowed_paths: list[str]
    writable_paths: list[str]
    allowed_tools: list[str]
    dependencies: list[str]
    input_artifact_ids: list[str]
    expected_artifacts: list[str]
    max_steps: int
    timeout_seconds: int
    priority: int
```

### WorkerResult

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
```

### AgentMessage

```python
@dataclass
class AgentMessage:
    message_id: str
    sender_id: str
    recipient_id: str
    message_type: str
    task_id: str
    payload: dict
    sequence: int
    timestamp: datetime
```

### ReviewFinding

```python
@dataclass
class ReviewFinding:
    finding_id: str
    severity: str  # blocker | high | medium | low
    title: str
    evidence: str
    file: str | None
    line: int | None
    requested_change: str
```

### FileLease

```python
@dataclass
class FileLease:
    path: str
    owner_agent_id: str
    task_id: str
    acquired_at: datetime
    expires_at: datetime
```

### TeamBudget

```python
@dataclass
class TeamBudget:
    max_agents: int = 3
    max_total_steps: int = 100
    max_total_model_calls: int = 200
    max_wall_time_seconds: int = 600
    max_fix_rounds: int = 2
```

## 关键规则

1. Worker tool call 必须经 PermissionGuardLite 检查。
2. 写文件前必须获得 FileLease；冲突时返回 `lease_conflict`。
3. 文件写入使用同目录临时文件 + `os.replace`，并支持 `expected_hash` CAS。
4. Worker 不能把模型 `done` 提议覆盖工具失败；scope/lease/cas 冲突会强制 FAILED。
5. Reviewer 只读，不修改实现；blocker/high 发现阻止完成。
6. 简单任务（<2 个独立子任务）保持单 Agent 路径。
