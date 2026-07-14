# PaperClaw

PaperClaw 是一个面向 Coding / Research 场景的轻量 Agent Runtime。当前实现重点是用 PocketFlow 风格控制流搭建一个可测试、可解释、可逐步扩展的编码 Agent，而不是直接堆一个重工作流框架。

当前仓库已完成：

- v0.01：最小 ReAct 编码 Agent；
- v0.02：Verify / Reflection Gate 基线；
- v0.03：Coordinator / Worker / Reviewer MultiAgent 分工协作基线；
- v0.04：Context / Session / SQLite MVP 闭环（持久化、角色裁剪、确定性压缩、安全恢复边界）。

尚未实现的设计项仍保持在 `Plan/` 和 `docs/desgin/` 中，不应视为已交付能力。

## 当前能力

### v0.01：最小 ReAct Loop

- 单步 `Reasoning -> Act -> Observation` 循环；
- 工具：`file_read`、`file_write`、`file_edit`、`grep`、`bash`；
- 工作区路径边界、显式覆盖写入、唯一精确替换；
- 命令超时、输出截断、基础 denylist；
- 非法 JSON、未知 action、工具错误、`max_steps` 有界退出；
- OpenAI-compatible 模型适配器；
- CLI 与 FakeModel 离线回归测试。

### v0.02：Verify / Reflection Gate

- `done` 从直接结束改为 `DoneProposal`；
- feature flag 控制的 Verify / Reflection Gate：`--enable-verification-gate`；
- VerificationPlan / VerificationEvidence / VerificationResult 契约；
- 文件存在、最新内容、验证命令时序检查；
- pytest / 相关命令摘要保留 `exit_code`、时长、截断标记与可解析统计；
- Reflection 只能消费已有 Evidence，不能伪造 Evidence 或删除 failed claims；
- 重复失败 signature 检测与 Reflection 轮数上限；
- 内存态结构化 trace，可导出 Verify / Reflection 事件。

### v0.03：MultiAgent 分工协作

- Coordinator / Worker / Reviewer 三角角色模型；
- `AgentTask` / `WorkerResult` / `AgentMessage` / `ReviewFinding` 结构化契约；
- Task DAG 校验（无环、依赖存在、写冲突、acceptance criteria）；
- 并行 vs 单 Agent 启发式决策 Gate；
- 最多 3 个 Worker 并发，线程隔离 + 共享事件 trace；
- `PermissionGuard Lite` 工具/路径权限检查；
- `FileLease` 文件写入所有权与同目录原子写入；
- `expected_hash` CAS 检测外部并发修改；
- 独立 Reviewer 与结构化 finding；
- `paperclaw agent` / `paperclaw team --plan plan.json` CLI。

### v0.04：Context / Session / SQLite MVP 闭环

> MVP 声明：v0.04 验证了 Context 持久化、角色裁剪、确定性压缩和安全恢复边界的最小闭环。

- **SQLite 持久化 Context 契约**：不可变 `ContextItem` / `ContextSource` / `ContextBudget` / `ContextSnapshot` / `SessionEvent` / `Checkpoint` 契约冻结于 `contracts.py`，SQLite append-only 事件日志 + 单写者 `SQLiteRepository` 保证 crash-safe 序列化与 session reopen。
- **ContextBuilder 与角色裁剪**：`ContextBuilder` 实现 collect → validate → scope → expire → dedup → conflict → estimate → select → compact → render → persist 全流程；`RoleContextView` 按 Coordinator / Worker / Reviewer 角色裁剪，`external_untrusted` 不入 L0/L1 硬 NO-GO。
- **确定性预算与结构化压缩**：`Char4TokenEstimator` 保守估算 + `CompactionPolicy` 无状态合并 evicted observation；摘要 `source_ref = compaction:item_id1,...` 可回溯原始 item，`hypothesis` 不被提升为 `fact`，超 protected 项预算时 fail-closed 抛 `ContextBudgetExhausted`。
- **安全恢复边界**：`CheckpointWriter` + `evaluate_resume_safety` 决策原语 + `ResumeCoordinator` 端到端 `decide_resume` + `FileSnapshotVerifier` hash 校验；检测到 pending mutation、active Worker、registry mismatch 或文件 hash 不匹配时返回 `recovery_required`，fail-closed 阻止不安全恢复。
- **PocketFlow 适配器**：`InstrumentedFlowRunner` 包裹 PocketFlow Flow，发射 `node.started` / `node.completed` 事件，`node.completed` 后提交 Checkpoint；parity 模式在 services 全 None 时退化为原生 `Flow.run`。
- **稳定 Node ID**：`NodeRegistry` 双向映射 + `compute_registry_hash`，`RegistryMismatch` 在恢复期暴露不兼容 Flow 定义。

测试与产物：

- 实现摘要：`artifacts/v0_04/implementation_summary.md`
- 测试报告：`artifacts/v0_04/test_report.md`（M04-01 至 M04-08 Gate 全 PASS；7 个定向测试文件合计 193 passed / 0 failed）
- 已知限制：`artifacts/v0_04/known_limitations.md`
- 集成演示：`tests/integration/test_v0_04_mvp_demo.py` → `artifacts/v0_04/mvp_demo_trace.json`（SOP §9 五阶段闭环可复现证据）
- 定向测试：`tests/unit/test_context_contracts.py`、`tests/unit/test_context_session.py`、`tests/unit/test_context_builder.py`、`tests/unit/test_compaction.py`、`tests/unit/test_checkpoint_wiring.py`、`tests/unit/test_resume_coordinator.py`、`tests/unit/test_instrumented_flow_runner.py`、`tests/unit/test_node_registry.py`

不在 v0.04 Gate 内的增强项（LLM 压缩、精确 tokenizer、Prompt Cache、自动长期 Memory、向量检索、任意时刻 crash 自动恢复、MultiAgent 端到端演示、完整 idempotency ledger）仍为 v0.04.1 候选，详见 `artifacts/v0_04/known_limitations.md`。

## 安装与测试

```powershell
python -m pip install -e ".[dev]"
python -m pytest -q --basetemp=tmp/pytest
```

当前基线测试结果：

- `344 passed, 1 skipped`

## 运行

CLI 会自动读取仓库根目录 `.env` 中的：

- `PAPERCLAW_API_KEY`
- `PAPERCLAW_BASE_URL`
- `PAPERCLAW_MODEL`
- `PAPERCLAW_TIMEOUT_SECONDS`（可选）

最小运行示例（v0.02 Verify Gate 默认开启）：

```powershell
paperclaw agent "创建 hello.py，使其输出 PaperClaw v0.01 OK，并运行验证" --workspace . --max-steps 8
```

如需显式关闭 Verify Gate（兼容性 / 低成本测试）：

```powershell
paperclaw agent "创建 hello.py，使其输出 PaperClaw v0.01 OK" --workspace . --max-steps 8 --no-enable-verification-gate
```

如需在测试 / 调试时观察过程日志，可显式开启：

```powershell
paperclaw agent "修复当前目录代码并运行验证" --workspace . --max-steps 10 --verbose-events
```

MultiAgent 团队运行（需准备 JSON plan，Verify Gate 同样默认开启）：

```powershell
paperclaw team --plan plan.json --workspace . --verbose-events
```

旧式无子命令调用仍默认进入 agent 路径：

```powershell
paperclaw "修复当前目录代码并运行验证" --workspace . --max-steps 10
```

`--verbose-events` 只用于测试 / 调试观测；默认运行仍只输出最终 JSON。

## 重要限制

- 当前 `bash` 安全策略只是 v0.01/v0.03 的最小边界，不是完整 Permission Engine；
- v0.02 Verify 仍主要依赖本地可确定性检查，尚未接入完整 Session / Memory / 持久 Trace；
- v0.03 MultiAgent 是进程内协作基线，不支持 crash 后自动恢复、跨机器分布式执行或自动 PR/push；
- Worker 取消为协作式：长耗时 `bash` 调用通过进程注册 + `taskkill /T /F` 终止子进程树；lease 在 Worker 线程自然退出后释放，不提前释放；
- 强制 CAS（write/edit 已有文件必须携带 `expected_hash`）已落地；新文件使用空字符串 sentinel；
- 顺序 DAG 执行、团队 model-call 预留预算、Task timeout、绝对 wall-time deadline 已落地；
- Reviewer Fix Task 闭环已落地；Global Verify、Reviewer 语义收紧、完整消息通道仍在后续 SOP 中；
- Context MVP（持久化、角色裁剪、确定性压缩、安全恢复边界）已在 v0.04 落地；Permission Engine、Eval、RAG、自动长期 Memory、向量检索仍在后续 SOP 中。

## 上游

PocketFlow 来源与固定提交见 [UPSTREAM.md](./UPSTREAM.md)，许可证见 [LICENSE](./LICENSE)。
